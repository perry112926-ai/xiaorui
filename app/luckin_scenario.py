"""Beijing Luckin workflow; writes are reachable only through host transactions."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from app.life_services import OfficialMcp, ServiceUnavailable
from app.actions import ActionError


class Args(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Stores(Args):
    longitude: float | None = Field(default=None, ge=115.4, le=117.6, allow_inf_nan=False)
    latitude: float | None = Field(default=None, ge=39.4, le=41.1, allow_inf_nan=False)
    origin_index: int | None = Field(default=None, ge=1, le=5, strict=True)
    keyword: str = Field(default='', max_length=80)

class Products(Args):
    store_index: int = Field(ge=1, le=5, strict=True)
    query: str = Field(min_length=1, max_length=150)

class Product(Args):
    product_index: int = Field(ge=1, le=5, strict=True)

class Switch(Product):
    attribute: str = Field(min_length=1, max_length=40)
    value: str = Field(min_length=1, max_length=40)

class Prepare(Product):
    quantity: int = Field(default=1, ge=1, le=5, strict=True)
    budget_cents: int | None = Field(default=None, ge=0, le=100000, strict=True)

class Order(Args):
    transaction_id: str = Field(min_length=1, max_length=128)


SCHEMAS = {
    'luckin_search_stores':(Stores,'查北京瑞幸自取门店。先用高德查用户指定地标或读取授权定位作为起点，再传已核对的 origin_index。禁止猜坐标。open为null时营业状态未知。'),
    'luckin_search_products':(Products,'用户选择门店后，按用户原话查饮品候选；使用当前门店序号。'),
    'luckin_product_detail':(Product,'查看当前饮品真实规格；不修改或下单。'),
    'luckin_switch_product':(Switch,'按用户指定的温度、糖度、杯型等切换真实可用规格，找不到选项时不能假装修改。'),
    'luckin_prepare_order':(Prepare,'用户选定实际饮品规格和数量后预览真实价格，预算内准备待确认自取方案，不创建订单、不付款。'),
    'luckin_query_order':(Order,'通过本人瑞幸事务编号查询真实订单和取餐信息；无订单号的未知结果不可重试。'),
    'luckin_prepare_cancel':(Order,'为本人待付款瑞幸订单准备取消确认；不能直接取消，已付款退款规则不明时拒绝自动取消。'),
    'luckin_order_records':(Args,'只读查看本人瑞幸任务记录，未知结果不能冒充失败或重新下单。'),
}


def cents(value):
    try:
        amount=Decimal(str(value))*100
        if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
            raise ValueError()
        return int(amount)
    except (InvalidOperation,ValueError,TypeError):
        raise ServiceUnavailable('瑞幸报价无效，无法生成确认方案。') from None


def pick(items,index):
    if index > len(items):
        raise ServiceUnavailable('请先查询，并选择当前返回的门店或饮品。')
    return items[index-1]


def candidates(data):
    if not isinstance(data,list) or any(not isinstance(x,dict) for x in data):
        raise ServiceUnavailable('瑞幸候选格式异常，请重新查询。')
    return deepcopy(data[:5])


def attributes(product):
    result=[]
    for group in product.get('productAttrs',[]):
        values=group.get('productSubAttrs',[])
        selected=[v.get('attributeName') for v in values if v.get('selected') is True]
        # Official search returns a singleton selected SKU with selected=null.
        if not selected and len(values)==1:
            selected=[values[0].get('attributeName')]
        result.append({'attribute':group.get('attributeName'),'selected':selected,
                       'options':[v.get('attributeName') for v in values]})
    return result


def store_status(store):
    tags=store.get('deptTags') or []
    text=[tag for tag in tags if isinstance(tag,str)]
    closed=any(tag in {'打烊中','已打烊','休息中','暂停营业','暂停接单','已闭店'} for tag in text)
    opened=any(tag in {'营业中','正常营业'} for tag in text)
    return {'open':False if closed else True if opened else None,
            'status_text':'、'.join(text) or '营业状态未明确返回',
            'work_time_start':store.get('workTimeStart'), 'work_time_end':store.get('workTimeEnd')}


class LuckinScenario:
    schemas=SCHEMAS
    def __init__(self,transactions,provider=None):
        self.transactions=transactions
        self.provider=provider or OfficialMcp('luckin')

    def _order(self,owner,transaction_id):
        plan=self.transactions.get(owner,transaction_id)
        if plan.get('provider')!='luckin':
            raise ServiceUnavailable('这不是本人的瑞幸订单。')
        order=plan.get('order') or {}
        oid=order.get('order_id')
        if not oid:
            raise ServiceUnavailable('这笔任务尚无可核实订单号；结果未知时请查官方订单，不能重复下单。')
        return str(oid)

    async def dispatch(self,session,owner,name,args,events):
        try:
            arg=self.schemas[name][0].model_validate(args)
            if name in {'luckin_search_stores','luckin_search_products','luckin_switch_product','luckin_prepare_order'}:
                self.transactions.invalidate_pending(owner)
            state=session.services.setdefault('luckin',{})
            if name=='luckin_search_stores':
                if arg.longitude is None or arg.latitude is None:
                    raise ServiceUnavailable('请先核对北京附近地标，再查瑞幸门店。')
                session.services['luckin']={}
                stores=candidates(await self.provider.call('queryShopList',{
                    'longitude':arg.longitude,'latitude':arg.latitude,'deptName':arg.keyword}))
                session.services['luckin']={'stores':stores,'products':[]}
                return {'stores':[{'index':i+1,'name':s.get('deptName'),'address':s.get('address'),**store_status(s)} for i,s in enumerate(stores)],'next':'请选择门店；尚未下单。'}
            if name=='luckin_search_products':
                store=pick(state.get('stores',[]),arg.store_index)
                state['products']=[];state.pop('selected_store',None)
                products=candidates(await self.provider.call('searchProductForMcp',{'deptId':store['deptId'],'query':arg.query}))
                state.update(selected_store=store,products=products)
                return {'products':[{'index':i+1,'name':p.get('productName'),'image':p.get('pictureUrl'),'attributes':attributes(p)} for i,p in enumerate(products)],'next':'请确认饮品及规格，价格需预览。'}
            if name in {'luckin_product_detail','luckin_switch_product','luckin_prepare_order'}:
                product=pick(state.get('products',[]),arg.product_index)
                store=state['selected_store']
                if name=='luckin_product_detail':
                    data=await self.provider.call('queryProductDetailInfo',{'deptId':store['deptId'],'productId':product['productId']})
                    return {'name':data.get('productName'),'attributes':attributes(data),'note':'查看规格未修改当前SKU。'}
                if name=='luckin_switch_product':
                    # Fetch full selectable options, while retaining the current SKU.
                    detail=await self.provider.call('queryProductDetailInfo',{'deptId':store['deptId'],'productId':product['productId']})
                    if not isinstance(detail,dict) or detail.get('productId')!=product['productId']:
                        raise ServiceUnavailable('官方规格详情与商品不一致，请重新查询。')
                    group=next((g for g in detail.get('productAttrs',[]) if g.get('attributeName')==arg.attribute),None)
                    option=next((v for v in (group or {}).get('productSubAttrs',[]) if v.get('attributeName')==arg.value),None)
                    if not group or not option or option.get('canSelected')==0:
                        raise ServiceUnavailable('当前商品没有这个可用规格，请选择实际返回的选项。')
                    data=await self.provider.call('switchProduct',{'deptId':store['deptId'],'productId':product['productId'],
                        'skuCode':product['skuCode'],'amount':1,'attrOperationParam':{'attributeId':group['attributeId'],
                        'subAttr':{'attributeId':option['attributeId'],'operation':3}}})
                    if not isinstance(data,dict) or not data.get('skuCode') or data.get('productId')!=product['productId']:
                        raise ServiceUnavailable('规格切换未得到有效SKU，请重新选择。')
                    state['products'][arg.product_index-1]=deepcopy(data)
                    return {'product_index':arg.product_index,'name':data.get('productName'),'attributes':attributes(data),'next':'已切换当前候选规格，需重新核价和确认。'}
                if store_status(store)['open'] is False:
                    raise ServiceUnavailable('这家瑞幸当前明确显示打烊或暂停接单，不能准备即时下单；请换营业中的门店。')
                if any(len(a['options'])>1 and not a['selected'] for a in attributes(product)):
                    raise ServiceUnavailable('当前饮品规格尚未明确，请先选择温度、糖度等实际选项。')
                request={'deptId':store['deptId'],'productList':[{'productId':product['productId'],'skuCode':product['skuCode'],'amount':arg.quantity}],
                    'longitude':store['longitude'],'latitude':store['latitude'],
                    '_summary':{'store':store['deptName'],'address':store.get('address'),'product':product.get('productName'),
                                'attributes':attributes(product),'quantity':arg.quantity,'fulfillment':'到店自取'}}
                quote=await self.quote('create',request)
                if arg.budget_cents is not None and quote['amount_cents']>arg.budget_cents:
                    return {'over_budget':True,'amount_cents':quote['amount_cents'],'next':'超过预算，尚未生成下单方案，请换商品或明确调整预算。'}
                quote['request']['_budget_cents']=arg.budget_cents
                quote['comparison']['budget_cents']=arg.budget_cents
                plan=self.transactions.prepare(owner,provider='luckin',action='create',request=quote['request'],quote=quote)
                events.append({'type':'action_plan','plan':plan})
                return {'plan':plan,'next':'请核对门店、规格、数量、价格后明确确认；尚未创建订单或支付。'}
            if name=='luckin_order_records':
                records=self.transactions.list(owner,provider='luckin')
                return {'records':[{k:p[k] for k in ('id','provider','action','summary','amount_cents','status','created_at','error') if k in p} for p in records]}
            oid=self._order(owner,arg.transaction_id)
            if name=='luckin_query_order':
                data=await self.provider.call('queryOrderDetailInfo',{'orderId':oid})
                return {'order':{k:data[k] for k in ('orderStatus','orderStatusName','takeMealCodeInfo','takeMealTime','aboutTime','orderPayAmount') if k in data},'note':'只报告官方返回的状态；待付款不等于门店已接单。'}
            quote=await self.quote('cancel',{'order_id':oid})
            plan=self.transactions.prepare(owner,provider='luckin',action='cancel',request=quote['request'],quote=quote)
            events.append({'type':'action_plan','plan':plan})
            return {'plan':plan,'next':'请明确确认取消；尚未取消。'}
        except (ServiceUnavailable,ActionError) as exc:
            return {'error':str(exc)}
        except ValidationError:
            return {'error':'请填写真实位置、当前候选序号和有效数量，尚未执行交易。'}
        except Exception:
            return {'error':'瑞幸任务未完成，请核对当前候选、账号状态或本人订单；没有自动下单、取消或付款。'}

    async def query_order(self,order_id):
        data=await self.provider.call('queryOrderDetailInfo',{'orderId':str(order_id)})
        return {k:data[k] for k in ('orderStatus','orderStatusName','takeMealCodeInfo','takeMealTime','aboutTime','orderPayAmount') if k in data}

    async def quote(self,action,request):
        request=deepcopy(request)
        if action=='cancel':
            data=await self.provider.call('queryOrderDetailInfo',{'orderId':request['order_id']})
            if str(data.get('orderStatus'))!='10':
                raise ServiceUnavailable('只支持为待付款订单准备取消；已付款订单退款规则需到官方渠道核实。')
            raise ServiceUnavailable('官方接口未提供可核实的取消费用规则，请到瑞幸官方渠道处理，不能假定免费取消。')
        if action!='create':
            raise ServiceUnavailable('不支持的瑞幸交易动作。')
        preview={k:request[k] for k in ('deptId','productList')}
        data=await self.provider.call('previewOrder',preview)
        current_store=data.get('shopInfo')
        if isinstance(current_store,dict) and store_status(current_store)['open'] is False:
            raise ServiceUnavailable('重新核价时门店已打烊或暂停接单，不能继续下单，请更换门店。')
        amount=cents(data.get('discountPrice'))
        budget=request.get('_budget_cents')
        if budget is not None:
            if type(budget) is not int or budget < 0:
                raise ServiceUnavailable('原始预算无效，请重新明确预算并生成方案。')
            if amount>budget:
                raise ServiceUnavailable('最新应付价格已超过原定预算，不能继续下单；请换商品或明确修改预算后重新准备。')
        request['couponCodeList']=data.get('couponCodeList') or []
        summary={**request['_summary'],'amount_cents':amount,'payment':'官方支付入口，尚未支付；不支持自动付款或外送承诺。'}
        return {'request':request,'summary':summary,'amount_cents':amount,'comparison':{
            'deptId':request['deptId'],'productList':request['productList'],'amount_cents':amount,
            'couponCodeList':request['couponCodeList'],'summary':request['_summary'],'budget_cents':budget}}

    async def execute(self,action,request):
        if action=='create':
            payload={k:request[k] for k in ('deptId','productList','longitude','latitude','couponCodeList') if k in request}
            data=await self.provider.call_confirmed('createOrder',payload)
            try:
                oid=data.get('orderIdStr') or data.get('orderId')
                if not oid:raise ValueError('missing order id')
                return {'order_id':str(oid),'payment_url':data.get('payOrderQrCodeUrl') or data.get('payOrderUrl'),
                        'need_pay':data.get('needPay'),'status':'created','provider_response':data}
            except (AttributeError,ValueError) as cause:
                error=ServiceUnavailable('瑞幸创建结果待核查，不能重复提交。')
                error.provider_response=data
                raise error from cause
        if action=='cancel':
            data=await self.provider.call_confirmed('cancelOrder',{'orderId':request['order_id']})
            if data is not True:
                error=ServiceUnavailable('瑞幸取消结果待核查，请勿重复操作。');error.provider_response=data;raise error
            return {'order_id':request['order_id'],'status':'cancelled'}
        raise ServiceUnavailable('不支持的瑞幸交易动作。')
