"""Official Luckin/DiDi read adapters. No remote transaction entry points.

Tool schemas are discovered from the user's account, rather than assumed from
public examples. Missing permissions and credentials never fall back to data.
"""
import asyncio
import json
import logging
import os
import re
import traceback
import httpx
from urllib.parse import quote, quote_plus
from datetime import timedelta
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import dotenv_values
from jsonschema import validate, ValidationError
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from app.service_transport import service_http_client
from app.mcp_payload import extract_payload, PayloadError

ROOT = Path(__file__).resolve().parents[1]
SPECS = {
    'luckin': {'label': '瑞幸', 'env': 'LUCKIN_MCP_TOKEN',
               'url': 'https://gwmcp.lkcoffee.com/order/user/mcp',
               'reads': {'queryShopList', 'searchProductForMcp', 'queryProductDetailInfo', 'previewOrder',
                         'switchProduct', 'queryOrderDetailInfo'},
               'writes': {'createOrder', 'cancelOrder'}},
    'didi': {'label': '滴滴', 'env': 'DIDI_MCP_KEY',
             'url': 'https://mcp.didichuxing.com/mcp-servers',
             'reads': {'maps_textsearch', 'taxi_estimate', 'taxi_query_order', 'taxi_get_driver_location', 'maps_regeocode'},
             'writes': {'taxi_create_order', 'taxi_cancel_order'}},
}


class ServiceUnavailable(RuntimeError):
    pass


def transport_diagnostic(error):
    """Return credential-free diagnostics, including nested MCP failures."""
    pending, kinds, statuses, codes, seen = [error], set(), set(), set(), set()
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        kinds.add(type(item).__name__)
        code = getattr(getattr(item, 'error', None), 'code', None)
        if type(code) is int:
            codes.add(code)
        if isinstance(item, httpx.HTTPStatusError):
            statuses.add(item.response.status_code)
        pending.extend(getattr(item, 'exceptions', ()))
        if item.__cause__ is not None:
            pending.append(item.__cause__)
    return {'error_types': sorted(kinds), 'http_statuses': sorted(statuses), 'mcp_codes': sorted(codes)}


class CredentialFilter(logging.Filter):
    """MCP/httpx may log exception URLs containing DiDi's query-string Key."""
    def __init__(self):
        super().__init__()
        self.secrets = set()

    def filter(self, record):
        message = record.getMessage()
        exception = ''.join(traceback.format_exception(*record.exc_info)) if record.exc_info else record.exc_text
        def redact(value):
            if not value:
                return value
            for secret in self.secrets:
                if secret:
                    for form in {secret, quote(secret, safe=''), quote_plus(secret, safe='')}:
                        value = value.replace(form, '[REDACTED]')
            # Protect encoded key parameters even if their escape case differs.
            return re.sub(r'''([?&](?:key|api_key)=)[^&\s'"<>]+''',
                          r'\1[REDACTED]', value, flags=re.IGNORECASE)
        message, exception = redact(message), redact(exception)
        record.msg, record.args = message, ()
        if record.exc_info or record.exc_text:
            record.exc_info, record.exc_text = None, exception
        return True


_credential_filter = CredentialFilter()
for _name in ('httpx', 'mcp.client.streamable_http'):
    logging.getLogger(_name).addFilter(_credential_filter)


class OfficialMcp:
    def __init__(self, provider):
        self.spec = SPECS[provider]
        self.provider = provider

    def _credential(self):
        name = self.spec['env']
        return str(os.environ.get(name, dotenv_values(ROOT / '.env').get(name) or '')).strip()

    @property
    def configured(self):
        return bool(self._credential())

    @asynccontextmanager
    async def connection(self):
        credential = self._credential()
        label = self.spec['label']
        if not credential:
            raise ServiceUnavailable(f'{label}尚未配置，请由家人在本机填写 {self.spec["env"]}。')
        _credential_filter.secrets.add(credential)
        # DiDi's official authentication uses a query parameter. Never log this URL.
        from urllib.parse import urlencode
        url, headers = self.spec['url'], {}
        if self.provider == 'didi':
            url += '?' + urlencode({'key': credential})
        else:
            headers['Authorization'] = 'Bearer ' + credential
        try:
            async with asyncio.timeout(55):
                async with streamablehttp_client(url, headers=headers, timeout=15, sse_read_timeout=25,
                                                httpx_client_factory=service_http_client) as (read, write, _):
                    async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=25)) as session:
                        await session.initialize()
                        tools, cursor = {}, None
                        for _ in range(10):
                            page = await session.list_tools(cursor=cursor)
                            tools.update((t.name, t) for t in page.tools)
                            if not page.nextCursor:
                                break
                            if page.nextCursor == cursor:
                                raise ServiceUnavailable(f'{label}工具目录异常。')
                            cursor = page.nextCursor
                        else:
                            raise ServiceUnavailable(f'{label}工具目录异常。')
                        yield session, tools
        except ServiceUnavailable:
            raise
        except Exception as cause:
            error = ServiceUnavailable(f'{label}连接或查询失败，请检查账号权限、网络和凭据。尚未下单。')
            error.diagnostic = transport_diagnostic(cause)
            if self.provider == 'didi' and -32001 in error.diagnostic['mcp_codes']:
                error.args = ('滴滴查询过于频繁，请稍后重新查询或确认；本次没有自动重试，也不能据此判断已有订单的结果。',)
            raise error from None

    async def discover(self):
        async with self.connection() as (_, tools):
            return {'provider': self.provider, 'connected': True,
                    'read_tools': sorted(self.spec['reads'] & tools.keys()),
                    'order_tool_available': ('taxi_create_order' if self.provider == 'didi' else 'createOrder') in tools,
                    'order_execution_enabled': False,
                    'note': '目录可见不代表交易权限已通过实测。'}

    async def call(self, name, arguments):
        # Enforce the allowlist before opening a connection, even for a known tool.
        if name not in self.spec['reads']:
            raise ServiceUnavailable('此接入阶段只允许查询与核价，不能创建、取消订单或支付。')
        return await self._invoke(name, arguments)

    async def call_confirmed(self, name, arguments):
        """Host-only adapter method, never registered as a model tool or API."""
        if name not in self.spec['writes']:
            raise ServiceUnavailable('该写操作不在受控白名单内。')
        return await self._invoke(name, arguments)

    async def _invoke(self, name, arguments):
        async with self.connection() as (session, tools):
            if name not in tools:
                raise ServiceUnavailable(f'当前账号未开放所需的{self.spec["label"]}工具。')
            try:
                validate(arguments, tools[name].inputSchema)
            except ValidationError:
                raise ServiceUnavailable('参数与官方接口不一致，请重新选择地点、门店或商品。') from None
            result = await session.call_tool(name, arguments=arguments)
            def failure(message):
                exc = ServiceUnavailable(message)
                if name in self.spec['writes']:
                    raw = json.dumps(result.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False)
                    exc.provider_response = json.loads(raw.replace(self._credential(), '[REDACTED]'))
                return exc
            if result.isError:
                raise failure(f'{self.spec["label"]}未返回可确认结果，请检查官方订单，暂不重复提交。')
            try:
                payload = extract_payload(result)
            except PayloadError:
                raise failure('无法识别官方返回结果，请核查，不能推断交易是否成功。') from None
            if self.provider == 'luckin':
                if not isinstance(payload, dict) or payload.get('code') != 0 or payload.get('success') is False or 'data' not in payload:
                    raise failure('瑞幸请求未返回成功，请核查账号和官方订单。')
                payload = payload['data']
            elif isinstance(payload, dict) and ('error' in payload or payload.get('success') is False):
                raise failure('滴滴请求未返回成功，请检查权限和官方订单。')
            # Do not forward account credentials even if a provider echoes them.
            if self._credential() in json.dumps(payload, ensure_ascii=False):
                raise ServiceUnavailable('官方结果包含敏感信息，已停止展示。')
            return payload


def connection_status():
    return {p: {'configured': OfficialMcp(p).configured, 'order_execution_enabled': False,
                'status_scope': 'credential-presence-only'} for p in SPECS}
