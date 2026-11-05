"""Small adapter around the real official McDonald's MCP service.

There is no mock fallback. Only the confirmation service may call create_order;
the application does not expose an arbitrary MCP tool execution endpoint.
"""

from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from app import read_only
from pathlib import Path
import asyncio
import os

from dotenv import dotenv_values
from jsonschema import ValidationError, validate
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from app.service_transport import service_http_client

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'https://mcp.mcd.cn'


def mcd_token():
    """Environment overrides local configuration, including an explicit empty value."""
    local = dotenv_values(ROOT / '.env').get('MCD_MCP_TOKEN') or ''
    return os.environ.get('MCD_MCP_TOKEN', local).strip()


class McdRejectedError(RuntimeError):
    """Explicit business refusal; not a transport timeout or unknown outcome."""


from app.mcp_payload import extract_payload, PayloadError


def _payload(result):
    if result.isError:
        raise RuntimeError('麦当劳工具返回错误，请稍后重新查询。')
    try:
        value = extract_payload(result, envelope=lambda item:
            isinstance(item, dict) and isinstance(item.get('success'), bool))
    except PayloadError:
        raise RuntimeError('暂时无法识别麦当劳返回结果，请勿重复下单。') from None
    if value['success'] is not True:
        raise McdRejectedError('麦当劳未接受本次请求，请重新查询可售商品。')
    if 'data' not in value:
        raise RuntimeError('麦当劳返回结果缺少业务数据。')
    return value['data']


def _amount(data):
    try:
        amount = Decimal(str(data['price']))
    except (KeyError, InvalidOperation, TypeError):
        raise RuntimeError('核价结果缺少有效金额。') from None
    if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
        raise RuntimeError('核价金额格式不正确，无法创建订单。')
    return int(amount)


class McdService:
    def __init__(self):
        self.stores = {}

    @asynccontextmanager
    async def _connection(self):
        token = mcd_token()
        if not token:
            raise ValueError('请先在本地 .env 配置麦当劳 MCP Token。')
        try:
            async with asyncio.timeout(60):
                async with streamablehttp_client(
                    ENDPOINT, headers={'Authorization': 'Bearer ' + token},
                    timeout=20, sse_read_timeout=30,
                    httpx_client_factory=service_http_client,
                ) as (read, write, _):
                    async with ClientSession(
                        read, write, read_timeout_seconds=timedelta(seconds=30),
                    ) as session:
                        await session.initialize()
                        tools, cursor = {}, None
                        for _ in range(20):
                            page = await session.list_tools(cursor=cursor)
                            tools.update((t.name, t) for t in page.tools)
                            if not page.nextCursor:
                                break
                            if page.nextCursor == cursor:
                                raise RuntimeError('工具目录分页异常。')
                            cursor = page.nextCursor
                        else:
                            raise RuntimeError('工具目录过大，请稍后再试。')

                        async def call(name, arguments):
                            if name not in tools:
                                raise RuntimeError('当前账号尚未开放所需的麦当劳工具。')
                            try:
                                validate(arguments, tools[name].inputSchema)
                            except ValidationError:
                                raise ValueError('商品或门店参数不符合官方接口要求，请重新选择。') from None
                            return _payload(await session.call_tool(name, arguments=arguments))

                        yield call
        except (ValueError, RuntimeError):
            raise
        except Exception:
            # Never return provider response bodies, tokens, or account data.
            raise RuntimeError('麦当劳连接或请求异常；若正在下单，请先核查订单，勿重复提交。') from None

    async def search_stores(self, city, keyword):
        if not city.strip() or not keyword.strip():
            raise ValueError('请填写城市和附近地点。')
        async with self._connection() as call:
            data = await call('query-nearby-stores', {
                'beType': 1, 'searchType': 2, 'city': city.strip(), 'keyword': keyword.strip(),
            })
        if not isinstance(data, list):
            raise RuntimeError('门店数据格式异常。')
        stores = []
        for row in data:
            if not row.get('storeCode') or not row.get('storeName'):
                continue
            item = {'code': row['storeCode'], 'name': row['storeName'],
                    'address': row.get('address', ''), 'distance': row.get('distance'),
                    'open': row.get('businessStatus', False)}
            self.stores[item['code']] = item
            stores.append(item)
        return stores

    @staticmethod
    def _base(store_code):
        return {'storeCode': store_code, 'orderType': 1, 'beType': 1}

    async def menu(self, store_code):
        async with self._connection() as call:
            data = await call('query-meals', self._base(store_code))
        meals = data.get('meals') if isinstance(data, dict) else None
        if not isinstance(meals, dict):
            raise RuntimeError('菜单数据格式异常。')
        # Exclude member-card purchase bundles from the first milestone.
        return [{'code': code, 'name': item['name'],
                 'price_yuan': str(item.get('currentPrice', '')),
                 'image': item.get('image'), 'product_type': item.get('productType')}
                for code, item in meals.items()
                if item.get('name') and not item.get('canWithOrder')]

    async def detail(self, store_code, product_code):
        async with self._connection() as call:
            data = await call('query-meal-detail', {
                **self._base(store_code), 'code': product_code,
            })
        if not isinstance(data, dict) or str(data.get('code')) != product_code:
            raise RuntimeError('商品详情与选择不一致，请重新选择。')
        return data

    async def prepare_plan(self, request):
        store_code, product_code = request['store_code'], request['product_code']
        store = self.stores.get(store_code)
        if not store:
            raise ValueError('请先搜索并选择门店。服务重启后需要重新选择。')
        if store.get('open') is False:
            raise ValueError('当前门店未营业，请选择营业中的门店。')
        quantity = request.get('quantity', 1)
        if type(quantity) is not int or not 1 <= quantity <= 5:
            raise ValueError('本阶段支持购买 1 至 5 份同款餐品。')
        async with self._connection() as call:
            menu = await call('query-meals', self._base(store_code))
            item = menu.get('meals', {}).get(product_code)
            if not item or item.get('canWithOrder'):
                raise ValueError('此餐品当前不可用，或需要随单购买会员卡，暂不支持。')
            detail = await call('query-meal-detail', {
                **self._base(store_code), 'code': product_code,
            })
            if not isinstance(detail, dict) or str(detail.get('code')) != product_code:
                raise RuntimeError('商品详情与选择不一致。')
            rounds = detail.get('rounds', [])
            supplied = request.get('rounds', [])
            selections = {}
            for selected in supplied:
                rid = str(selected['round_id'])
                if rid in selections or selected.get('quantity', 1) != 1:
                    raise ValueError('套餐选项重复或数量不受支持。')
                selections[rid] = str(selected['code'])
            if set(selections) != {str(r['id']) for r in rounds}:
                raise ValueError('请为套餐的每一项选择内容。')
            round_list, labels = [], []
            for current in rounds:
                if current.get('minQuantity') != 1 or current.get('maxQuantity') != 1:
                    raise ValueError('该餐品需要多选组合，当前阶段暂不支持。')
                code = selections[str(current['id'])]
                choice = next((c for c in current['choices'] if str(c['code']) == code), None)
                if not choice:
                    raise ValueError('套餐选项已变化，请重新选择。')
                labels.append(choice['name'])
                round_list.append({'round': str(current['id']),
                                   'comboItemList': [{'code': code, 'quantity': 1}]})
            selected_item = {'productCode': product_code, 'quantity': quantity}
            if round_list:
                selected_item['roundList'] = round_list
            payload = {**self._base(store_code), 'items': [selected_item]}
            quoted = await call('calculate-price', payload)
            amount = _amount(quoted)
            ways = quoted.get('takeWayList', [])
            if not ways or not ways[0].get('code'):
                raise RuntimeError('未找到可用取餐方式，暂时不能继续。')
            way = ways[0]
            payload['takeWayCode'] = way['code']
        return {'request': payload, 'amount_cents': amount,
                'take_way_code': way['code'],
                'summary': {'store_name': store['name'], 'store_address': store['address'],
                            'product_name': item['name'], 'quantity': quantity,
                            'choices': labels,
                            'take_way': ' · '.join(filter(None, [way.get('title'), way.get('subtitle')]))}}

    async def requote(self, payload):
        query = {k: v for k, v in payload.items() if k != 'takeWayCode'}
        async with self._connection() as call:
            data = await call('calculate-price', query)
        return {'amount_cents': _amount(data),
                'take_way_codes': [w['code'] for w in data.get('takeWayList', []) if w.get('code')]}

    async def create_order(self, payload):
        if read_only.READ_ONLY:
            raise RuntimeError(read_only.MESSAGE)
        # Sole remote mutation path, called only after PlanService authorizes it.
        async with self._connection() as call:
            data = await call('create-order', payload)
        if not isinstance(data, dict):
            raise RuntimeError('订单结果无法识别，需要人工核查，请勿重试。')

        def find(keys, value):
            if isinstance(value, dict):
                for key in keys:
                    if isinstance(value.get(key), (str, int)) and value[key]:
                        return str(value[key])
                for child in value.values():
                    found = find(keys, child)
                    if found:
                        return found
            return None

        order_id = find(('orderId', 'orderCode', 'orderNo', 'orderNumber'), data)
        payment_url = find(('payH5Url', 'payUrl', 'paymentUrl', 'payLink', 'paymentLink'), data)
        if payment_url and not payment_url.startswith('https://'):
            payment_url = None
        return {'order_id': order_id, 'payment_url': payment_url, 'raw': data}
