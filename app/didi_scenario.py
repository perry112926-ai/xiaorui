"""Beijing ride workflow. Queries are tools; mutations belong to transaction host."""
from app.money import format_cents
import copy
import time
from decimal import Decimal, InvalidOperation
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from app.life_services import OfficialMcp, ServiceUnavailable


class Args(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Place(Args):
    purpose: Literal['origin', 'destination']
    keyword: str = Field(min_length=1, max_length=120)


class Route(Args):
    origin_index: int = Field(ge=1, le=5, strict=True)
    destination_index: int = Field(ge=1, le=5, strict=True)


class Ride(Args):
    vehicle_index: int = Field(ge=1, le=10, strict=True)


class Order(Args):
    action_id: str = Field(min_length=1, max_length=128)


class Cancel(Order):
    reason: str = Field(default='用户不再需要用车', min_length=1, max_length=100)


SCHEMAS = {
    'didi_current_location': (Args, '读取用户刚授权的浏览器定位作为本轮起点候选，不能当作家。必须向用户确认平台实际上车点；过期或未授权时询问地标。'),
    'didi_search_places': (Place, '在北京搜索本次起点或目的地。起点必须来自本轮真实定位或用户陈述，家可来自明确保存的地址。'),
    'didi_estimate_ride': (Route, '用户确认本轮起终点后查询真实车型估价，同时说明平台实际接送点可能与原地点不同。'),
    'didi_prepare_ride': (Ride, '用户选定车型后准备待确认叫车方案，不发单。会提示免密扣款、真实上车点和估价。'),
    'didi_query_ride': (Order, '查询本人的小瑞叫车记录对应的实际订单状态和司机信息，不可使用他人记录。'),
    'didi_driver_location': (Order, '查询本人进行中订单的司机位置；没有位置不推测距离或到达时间。'),
    'didi_prepare_cancel': (Cancel, '查询本人订单与明确取消费用后，准备待确认取消方案；费用未知时停止，不能保证免费取消。'),
    'didi_list_rides': (Args, '列出本人小瑞滴滴任务记录，结果未知不能当失败或自动重新叫车。'),
}


def cents(value):
    try:
        amount = Decimal(str(value)) * 100
        if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
            raise ValueError()
        return int(amount)
    except (InvalidOperation, ValueError, TypeError):
        raise ServiceUnavailable('平台价格不是明确金额，无法准备叫车或取消方案。') from None


class DidiOutcomeUnknown(ServiceUnavailable):
    def __init__(self, message, response):
        super().__init__(message)
        self.provider_response = copy.deepcopy(response)


def place_fingerprint(place):
    # Ignore incidental fields in POIs; keep actual endpoint identity and location.
    result = {key:str(place[key]).strip() for key in ('name','address') if key in place}
    for key in ('longitude','latitude'):
        if key in place:
            value = Decimal(str(place[key]))
            if not value.is_finite():
                raise ServiceUnavailable('平台接送点坐标异常。')
            result[key] = str(value.quantize(Decimal('0.000001')))
    return result


def choose(items, index):
    if not isinstance(items, list) or index > len(items):
        raise ServiceUnavailable('请先查询，并从本轮候选中选择。')
    return copy.deepcopy(items[index-1])


def clean_order(data):
    if not isinstance(data, dict):
        raise ServiceUnavailable('订单结果格式异常，不能判断车辆状态。')
    result = {k: data[k] for k in ('statusCode','statusText','status','from','to','cancelFee','cancelFeeCents','canCancel') if k in data}
    driver = data.get('driver')
    if isinstance(driver, dict):
        result['driver'] = {k:driver[k] for k in ('name','carModel','carPlate') if k in driver}
    if isinstance(data.get('map'), dict):
        result['map'] = {k:data['map'][k] for k in ('distanceKm','eta') if k in data['map']}
    return result


class DidiScenario:
    schemas = SCHEMAS

    def __init__(self, transactions, provider=None, location_provider=None):
        self.transactions = transactions
        self.provider = provider or OfficialMcp('didi')
        self.location_provider = location_provider

    def _order(self, owner, action_id):
        plan = self.transactions.get(owner, action_id)
        if plan.get('provider') != 'didi' or plan.get('action') != 'create':
            raise ServiceUnavailable('请选择本人的滴滴叫车记录。')
        order = plan.get('order') or {}
        if not order.get('order_id'):
            raise ServiceUnavailable('这笔记录尚无可查询订单号；结果未知时不能重新叫车。')
        return str(order['order_id'])

    async def quote(self, action, request):
        request = copy.deepcopy(request)
        if action == 'cancel':
            data = clean_order(await self.provider.call('taxi_query_order', {'order_id':request['order_id']}))
            if data.get('canCancel') is False:
                raise ServiceUnavailable('平台表示当前订单不可取消，请到滴滴官方订单页核对状态。')
            if str(data.get('statusCode')) in {'4','5'}:
                raise ServiceUnavailable('行程中或已完成的订单不能取消。')
            if 'cancelFeeCents' in data:
                amount = cents(Decimal(str(data['cancelFeeCents']))/100)
            elif 'cancelFee' in data:
                amount = cents(data['cancelFee'])
            else:
                raise ServiceUnavailable('平台未返回明确取消费，不能保证免费。请到滴滴官方订单页核对取消条件。')
            return {'request':request, 'amount_cents':amount,
                    'summary':{'操作':'取消滴滴订单','取消费用':f'{format_cents(amount)}元','原因':request['reason']},
                    'comparison':{'order_id':request['order_id'],'reason':request['reason'],'cancel_fee_cents':amount}}
        if action != 'create':
            raise ServiceUnavailable('不支持这个操作。')
        if request.get('location_expires_at',float('inf')) < time.time():
            raise ServiceUnavailable('起点定位已过期，请重新定位并核对上车点，没有发起叫车。')
        data = await self.provider.call('taxi_estimate', request['route'])
        return self._create_quote(request, data)

    @staticmethod
    def _create_quote(request, data):
        request = copy.deepcopy(request)
        if not isinstance(data, dict) or not data.get('traceId'):
            raise ServiceUnavailable('没有取得有效报价凭据，尚未叫车。')
        item = next((i for i in data.get('items', []) if str(i.get('productCategory')) == request['product_category']), None)
        if not item or not item.get('productName'):
            raise ServiceUnavailable('所选车型已不可用，请重新选择。')
        amount = cents(item.get('priceText'))
        actual = {k:copy.deepcopy(data.get(k)) for k in ('from','to')}
        if any(not isinstance(actual[k],dict) or not actual[k].get('name') for k in actual):
            raise ServiceUnavailable('平台没有返回明确接送点，不能准备叫车。')
        request['estimate_trace_id'] = data['traceId']
        comparison = {'route':request['route'], 'product_category':request['product_category'],
                      'vehicle':item['productName'],'amount_cents':amount,'actual_places':{key:place_fingerprint(value) for key,value in actual.items()}}
        summary = {'操作':'叫滴滴','车型':item['productName'],'预估费用':f'{format_cents(amount)}元',
                   '实际上车点':actual['from']['name'],'实际下车点':actual['to']['name'],
                   '支付提醒':'确认后会真实叫车，关联账号可能免密扣款；实际车费以平台结算为准。'}
        return {'request':request,'summary':summary,'amount_cents':amount,'comparison':comparison}

    async def execute(self, action, request):
        if action == 'create':
            data = await self.provider.call_confirmed('taxi_create_order', {
                'product_category':request['product_category'],'estimate_trace_id':request['estimate_trace_id']})
            if not isinstance(data,dict) or not data.get('orderId'):
                raise DidiOutcomeUnknown('叫车结果未知，请核查，不要重新发单。', data)
            return {'order_id':str(data['orderId']), **clean_order(data), 'paid':None}
        if action == 'cancel':
            data = await self.provider.call_confirmed('taxi_cancel_order', {
                'order_id':request['order_id'],'reason':request['reason']})
            if not isinstance(data,dict) or data.get('success') is not True:
                raise DidiOutcomeUnknown('取消结果未确认，不能声称已取消。', data)
            return {'order_id':request['order_id'],'status':'cancelled','cancelled':True}
        raise ServiceUnavailable('不支持这个操作。')

    async def query_order(self, order_id):
        return clean_order(await self.provider.call('taxi_query_order', {'order_id': str(order_id)}))

    async def dispatch(self, session, owner, name, arguments, events):
        try:
            args = self.schemas[name][0].model_validate(arguments)
            state = session.services.setdefault('didi', {})
            if name == 'didi_current_location':
                point=self.location_provider(owner) if self.location_provider else None
                if not point:
                    events.append({'type':'location_request'})
                    return {'error':'没有当前有效定位，请点击定位授权，或说出附近地标。'}
                if not (115.4<=point['longitude']<=117.6 and 39.4<=point['latitude']<=41.1):
                    return {'error':'定位不在北京附近，当前叫车仅支持北京。请提供北京起点地标，不能假装在北京。'}
                self.transactions.invalidate_pending(owner)
                state.pop('estimate',None);state.pop('route',None)
                state['origin']=[{'display_name':'本次浏览器定位附近（上车点待核对）',
                    'location':{'lng':point['longitude'],'lat':point['latitude']},
                    'location_expires_at':point['received_at']+120}]
                return {'places':[dict(state['origin'][0],index=1)],'purpose':'origin',
                    'accuracy_meters':point['accuracy'],'next':'这是定位附近，不是精确上车点。确认使用这里作起点后再估价，并核对平台实际接送点。'}
            if name == 'didi_search_places':
                self.transactions.invalidate_pending(owner)
                state.pop(args.purpose, None); state.pop('estimate', None); state.pop('route', None)
                data = await self.provider.call('maps_textsearch', {'keywords':args.keyword,'city':'北京市'})
                if not isinstance(data,list) or any(not isinstance(i,dict) for i in data):
                    raise ServiceUnavailable('地点查询结果异常。')
                state[args.purpose] = data[:5]
                return {'places':[dict(p,index=i+1) for i,p in enumerate(data[:5])], 'purpose':args.purpose,
                        'next':'请用户确认具体地点。'}
            if name == 'didi_estimate_ride':
                self.transactions.invalidate_pending(owner)
                state.pop('estimate',None); state.pop('route',None)
                origin=choose(state.get('origin'),args.origin_index)
                if origin.get('location_expires_at',float('inf')) < time.time():
                    raise ServiceUnavailable('起点定位已过期，请重新定位或提供地标。')
                destination=choose(state.get('destination'),args.destination_index)
                route={}
                for prefix,place in [('from',origin),('to',destination)]:
                    route.update({prefix+'_lng':str(place['location']['lng']),prefix+'_lat':str(place['location']['lat']),prefix+'_name':place['display_name']})
                data=await self.provider.call('taxi_estimate',route)
                if not isinstance(data,dict) or not isinstance(data.get('items'),list) or not data['items']:
                    raise ServiceUnavailable('没有可用车型或报价。')
                state.update(route=route,estimate={
                    'location_expires_at':origin.get('location_expires_at'),
                    'items': copy.deepcopy(data['items'][:10]),
                    'traceId': data.get('traceId'), 'from': copy.deepcopy(data.get('from')),
                    'to': copy.deepcopy(data.get('to')), 'received_at': time.time()})
                items=[{k:p[k] for k in ('productName','productCategory','priceText','priceDiscounted') if k in p} for p in data['items'][:10]]
                return {'vehicles':[dict(p,index=i+1) for i,p in enumerate(items)],'actual_places':{k:data.get(k) for k in ('from','to')},'order_created':False,'next':'核对实际接送点与车型；选择后准备确认方案。'}
            if name == 'didi_prepare_ride':
                selected=choose((state.get('estimate') or {}).get('items'),args.vehicle_index)
                request={'route':state['route'],'product_category':str(selected['productCategory'])}
                expiry=(state.get('estimate') or {}).get('location_expires_at')
                if expiry is not None and expiry!=float('inf'):
                    request['location_expires_at']=expiry
                    if expiry<time.time():raise ServiceUnavailable('起点定位已过期，请重新定位。')
                # Reuse this turn's recent estimate for the selection card.
                # Host confirmation still calls quote() for a fresh estimate.
                cached=state['estimate']
                age=time.time()-cached.get('received_at',0)
                if cached.get('traceId') and 0 <= age <= 30:
                    quote=self._create_quote(request,cached)
                else:
                    quote=await self.quote('create',request)
                plan=self.transactions.prepare(owner,provider='didi',action='create',request=quote['request'],quote=quote)
                events.append({'type':'action_plan','plan':plan})
                return {'plan':plan,'order_created':False}
            if name == 'didi_list_rides':
                return {'rides':[self.transactions.public(p) for p in self.transactions.list(owner,provider='didi')]}
            order_id=self._order(owner,args.action_id)
            if name == 'didi_query_ride':
                data=clean_order(await self.provider.call('taxi_query_order',{'order_id':order_id}))
                events.append({'type':'service_result','provider':'didi','data':data})
                return {'order':data}
            if name == 'didi_driver_location':
                status=clean_order(await self.provider.call('taxi_query_order',{'order_id':order_id}))
                if str(status.get('statusCode')) not in {'1','2','4'}:
                    raise ServiceUnavailable('当前状态没有可查询的接驾司机位置。')
                data=await self.provider.call('taxi_get_driver_location',{'order_id':order_id})
                if not isinstance(data,dict) or 'longitude' not in data or 'latitude' not in data:
                    raise ServiceUnavailable('司机位置暂不可用。')
                return {'driver_location':{k:data[k] for k in ('longitude','latitude')},'note':'仅为司机位置，不是老人位置。'}
            if name == 'didi_prepare_cancel':
                request={'order_id':order_id,'reason':args.reason}
                quote=await self.quote('cancel',request)
                plan=self.transactions.prepare(owner,provider='didi',action='cancel',request=request,quote=quote)
                events.append({'type':'action_plan','plan':plan})
                return {'plan':plan,'cancelled':False}
            raise ServiceUnavailable('未开放该滴滴操作。')
        except ValidationError:
            return {'error':'参数不正确，请选择当前候选或本人叫车记录。'}
        except ServiceUnavailable as exc:
            return {'error':str(exc)}
        except Exception:
            return {'error':'滴滴处理未完成，请核对当前结果，不要重复叫车。'}
