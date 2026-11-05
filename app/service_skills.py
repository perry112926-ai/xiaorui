"""Owner-scoped candidates for Luckin and DiDi. All remote calls are read-only."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from app.life_services import OfficialMcp, ServiceUnavailable
from app.fliggy import Fliggy, SCHEMAS as FLIGGY_SCHEMAS


class Query(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class LuckinStores(Query):
    longitude: float = Field(ge=115.4, le=117.6, allow_inf_nan=False)
    latitude: float = Field(ge=39.4, le=41.1, allow_inf_nan=False)
    keyword: str = Field(default='', max_length=80)


class LuckinProducts(Query):
    store_index: int = Field(ge=1, le=5, strict=True)
    query: str = Field(min_length=1, max_length=150)


class LuckinPreview(Query):
    product_index: int = Field(ge=1, le=5, strict=True)
    quantity: int = Field(default=1, ge=1, le=5, strict=True)


class DidiPlaces(Query):
    purpose: Literal['origin', 'destination']
    keyword: str = Field(min_length=1, max_length=120)


class DidiEstimate(Query):
    origin_index: int = Field(ge=1, le=5, strict=True)
    destination_index: int = Field(ge=1, le=5, strict=True)


SERVICE_SCHEMAS = {
    **FLIGGY_SCHEMAS,
    'luckin_search_stores': (LuckinStores, '查询北京瑞幸门店。经纬度必须来自本轮用户明确提供的位置或真实定位结果，不可猜测；当前无自动定位工具，缺坐标先询问。'),
    'luckin_search_products': (LuckinProducts, '用户选定当前瑞幸门店后，按用户原话查询真实饮品及规格候选。store_index为本轮返回的门店序号。'),
    'luckin_preview': (LuckinPreview, '按用户选定的当前饮品序号预览订单、核价；规格取候选实际返回值，未满足温度糖度要求时不能擅自预览。这不会下单或支付。'),
    'didi_search_places': (DidiPlaces, '在北京市搜索本次起点或终点。origin是起点，destination是目的地。家可使用明确保存的家庭地址，当前位置必须来自用户本轮陈述，不得用旧地点推测。'),
    'didi_estimate_ride': (DidiEstimate, '用户确认起终点后，使用本次地点候选序号查询真实可用车型和估价；这不会呼叫车辆。'),
}


def rows(data):
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ServiceUnavailable('官方候选数据格式与文档不一致，请稍后重试。')
    return data[:5]


class LifeSkills:
    def __init__(self):
        self.fliggy = Fliggy()
        self.luckin, self.didi = OfficialMcp('luckin'), OfficialMcp('didi')

    @staticmethod
    def choice(items, index):
        if index > len(items):
            raise ServiceUnavailable('请先查询，并选择当前返回的候选。')
        return items[index - 1]

    async def dispatch(self, session, name, arguments):
        if name in FLIGGY_SCHEMAS:
            return await self.fliggy.dispatch(arguments)
        try:
            args = SERVICE_SCHEMAS[name][0].model_validate(arguments)
            state = session.services
            if name == 'luckin_search_stores':
                state.pop('luckin', None)
                data = await self.luckin.call('queryShopList', {
                    'longitude': args.longitude, 'latitude': args.latitude, 'deptName': args.keyword})
                stores = rows(data)
                state['luckin'] = {'stores': stores, 'products': []}
                return {'stores': [{'index': i+1, 'name': s.get('deptName'), 'address': s.get('address')}
                                   for i, s in enumerate(stores)], 'next': '请用户选择门店。'}
            if name == 'luckin_search_products':
                luckin = state.get('luckin', {})
                store = self.choice(luckin.get('stores', []), args.store_index)
                luckin['products'] = []
                luckin.pop('selected_store', None)
                data = await self.luckin.call('searchProductForMcp', {'deptId': store['deptId'], 'query': args.query})
                products = rows(data)
                luckin.update(products=products, selected_store=store)
                return {'products': [dict(p, index=i+1) for i, p in enumerate(products)],
                        'next': '说明实际规格，请用户选择；最终价格需预览。尚未下单。'}
            if name == 'luckin_preview':
                luckin = state.get('luckin', {})
                product = self.choice(luckin.get('products', []), args.product_index)
                store = luckin['selected_store']
                data = await self.luckin.call('previewOrder', {'deptId': store['deptId'], 'productList': [{
                    'productId': product['productId'], 'skuCode': product['skuCode'], 'amount': args.quantity}]})
                return {'preview': data, 'order_created': False, 'paid': False,
                        'note': '本工具只提供官方订单预览，不创建订单，不承诺外送；如需继续瑞幸自取，使用luckin场景的受控确认流程。'}
            if name == 'didi_search_places':
                didi = state.setdefault('didi', {})
                didi.pop(args.purpose, None)
                data = await self.didi.call('maps_textsearch', {'keywords': args.keyword, 'city': '北京市'})
                places = rows(data)
                didi[args.purpose] = places
                return {'purpose': args.purpose, 'places': [dict(p, index=i+1) for i,p in enumerate(places)],
                        'next': '请用户确认具体地点；起点应确认方便上车的位置。'}
            if name == 'didi_estimate_ride':
                didi = state.get('didi', {})
                origin = self.choice(didi.get('origin', []), args.origin_index)
                destination = self.choice(didi.get('destination', []), args.destination_index)
                params = {}
                for prefix, place in [('from', origin), ('to', destination)]:
                    params.update({f'{prefix}_lng': str(place['location']['lng']),
                                   f'{prefix}_lat': str(place['location']['lat']),
                                   f'{prefix}_name': place['display_name']})
                data = await self.didi.call('taxi_estimate', params)
                if not isinstance(data, dict) or not isinstance(data.get('items'), list) or not data['items']:
                    raise ServiceUnavailable('滴滴未返回可用车型，尚未叫车。')
                # The platform may snap POIs to different pickup/drop-off points.
                # Keep these visible; omit phone suffixes, links, trace IDs and
                # hundreds of route coordinates from the model context.
                estimate = {key: data[key] for key in ('from', 'to', 'distanceKm', 'eta') if key in data}
                estimate['items'] = [{key: item[key] for key in (
                    'productName', 'productCategory', 'priceText', 'priceDiscounted') if key in item}
                    for item in data['items'] if isinstance(item, dict)]
                if not estimate['items']:
                    raise ServiceUnavailable('滴滴车型数据格式异常，尚未叫车。')
                return {'estimate': estimate, 'order_created': False,
                        'requested_places': {'origin': origin['display_name'], 'destination': destination['display_name']},
                        'note': '仅为车型和价格预估，尚未叫车；必须核对平台返回的实际起终点，不能将吸附后的地点冒充用户原选地点。优惠条件与实际车费以平台为准。'}
        except ValidationError:
            return {'error': '查询参数不正确，请补充真实位置或选择本轮候选。'}
        except ServiceUnavailable as exc:
            return {'error': str(exc)}
        except Exception:
            return {'error': '服务数据暂时无法识别，请重新查询。尚未下单或叫车。'}
