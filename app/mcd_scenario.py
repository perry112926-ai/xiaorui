"""Beijing McDonald's scenario, provider-owned quotes and host-owned approval.

Model tools can prepare, inspect and query. Only the host transaction manager
may call execute; no model tool submits an order or cancels a remote order.
"""
import copy
import re
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from app.mcd import McdService, _amount
from app.mcd_recommendations import RecommendationArgs, RecommendedChoice, recommend, choose


class Args(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Stores(Args):
    keyword: str = Field(min_length=1, max_length=120)
    city: str = Field(default='北京', min_length=2, max_length=30, pattern=r'^[\u4e00-\u9fff]+$')


class DeliveryStores(Args):
    address_index: int = Field(ge=1, le=20, strict=True)


class DeliveryAddresses(Args):
    city: str = Field(default='北京', min_length=2, max_length=30, pattern=r'^[\u4e00-\u9fff]+$')


class NewAddress(Args):
    city: str = Field(min_length=2, max_length=30, pattern=r'^[\u4e00-\u9fff]+$')
    contactName: str = Field(min_length=1, max_length=50)
    phone: str = Field(pattern=r'^1[0-9]{10}$')
    address: str = Field(min_length=1, max_length=200)
    addressDetail: str = Field(min_length=1, max_length=100)
    gender: Literal['先生', '女士'] | None = None


class AddressDraft(Args):
    city: str | None = Field(default=None, min_length=2, max_length=30, pattern=r'^[\u4e00-\u9fff]+$')
    contactName: str | None = Field(default=None, min_length=1, max_length=50)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = Field(default=None, min_length=1, max_length=200)
    addressDetail: str | None = Field(default=None, min_length=1, max_length=100)
    gender: Literal['先生', '女士'] | None = None
    reset: bool = False


class Menu(Args):
    store_index: int = Field(ge=1, le=20, strict=True)
    keyword: str = Field(default='', max_length=100)


class Detail(Args):
    product_index: int = Field(ge=1, le=20, strict=True)


class Choice(Args):
    round_id: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1, max_length=80)


class Prepare(Detail):
    budget_cents: int | None = Field(default=None, ge=1, le=100000, strict=True)
    quantity: int = Field(default=1, ge=1, le=5, strict=True)
    choices: list[Choice] = Field(default_factory=list, max_length=20)
    take_way_index: int | None = Field(default=None, ge=1, le=10, strict=True)
    need_tableware: bool | None = Field(default=None, strict=True)
    remark: str = Field(default='', max_length=50)


class Cart(Args):
    action: Literal['add', 'update', 'remove', 'clear', 'show'] = 'show'
    product_index: int | None = Field(default=None, ge=1, le=20, strict=True)
    line_index: int | None = Field(default=None, ge=1, le=10, strict=True)
    quantity: int = Field(default=1, ge=1, le=5, strict=True)
    choices: list[Choice] = Field(default_factory=list, max_length=20)


class PrepareCart(Args):
    budget_cents: int | None = Field(default=None, ge=1, le=100000, strict=True)
    take_way_index: int | None = Field(default=None, ge=1, le=10, strict=True)
    need_tableware: bool | None = Field(default=None, strict=True)
    remark: str = Field(default='', max_length=50)


class Order(Args):
    plan_id: str = Field(min_length=1, max_length=128)


class Cancel(Order):
    reason: Literal['1', '2', '3', '4', '5', '-1'] = '1'


SCHEMAS = {
    'mcd_recommend_meals': (RecommendationArgs, '默认点餐入口：按本次已确认地址／地标查到的门店，自动推荐最多三个有图片、套餐规则可构建且真实核价通过的单人套餐。用户明确只要单品、少量餐品时可传meal_type=single，不强推套餐。无需让老人先选门店或逐项搭配；可带预算、不喝冰饮和避开食材关键词。返回具体默认搭配和含费总额，不创建订单。'),
    'mcd_choose_recommendation': (RecommendedChoice, '选本轮已预检套餐，直接准备完整待确认方案；不再逐项询问套餐内容或餐具，不会创建订单。'),
    'mcd_address_draft': (AddressDraft, '分步收集本次新收餐地址，不写入官方账号。每次只传用户本轮提供或核对的字段，保留已说过的信息，一次只追问一个缺项。用户换地方或换收餐人用reset=true。收齐后仍需mcd_prepare_address和独立确认。'),
    'mcd_cart': (Cart, '本轮购物车。add按当前菜单序号加入用户选择的餐品及数量和套餐选项；update按购物车行序号修改数量或套餐选项；remove按购物车行序号删除；clear清空；show查看。支持同店分次搜餐后加入；换店或换地址会清空，绝不下单。'),
    'mcd_prepare_cart': (PrepareCart, '核价整个当前购物车，含全部餐品和数量；外送必须核对餐具，预算传分。生成一个待确认方案，不执行下单。'),
    'mcd_current_location': (Args, '读取本次已授权定位，通过地图查询附近地址供用户核对；不是精确门牌，不是家，不能据此猜联系人、电话或门牌。'),
    'mcd_prepare_address': (NewAddress, '准备新增麦当劳配送地址的确认卡片，不写入。仅填用户明确提供或核对的城市、地址、门牌、联系人和完整手机号码；不得用旧地址或掩码电话猜填。用户确认新增地址后由宿主写入，再查询地址列表选择新地址继续点餐。'),
    'mcd_search_pickup': (Stores, '按用户明确城市搜索麦当劳到店门店，开始新的麦当劳候选；不是外卖。'),
    'mcd_delivery_addresses': (DeliveryAddresses, '查询本人麦乐送已有地址供用户选择。城市来自用户本轮陈述或核对的定位；默认北京，不因旧地址自动换城市，不创建地址。'),
    'mcd_delivery_stores': (DeliveryStores, '按用户选择的本轮配送地址查询可配送麦当劳门店，不猜地址或配送范围，不自动换城市。'),
    'mcd_menu': (Menu, '用户选当前门店序号后查询菜单，可按餐品名称筛选；重查会使旧餐品候选失效。'),
    'mcd_product_detail': (Detail, '查看当前餐品序号的真实套餐选项。可选项不能擅自猜测，不保证不辣或过敏安全。'),
    'mcd_prepare_order': (Prepare, '按用户明确选择的餐品、数量和套餐选项真实核价，并准备本地待确认方案。预算必须传budget_cents（分）；外送必须明确是否需要餐具，备注仅记录明确要求，不保证商家接受。未选择堂食/外带时返回方式列表。这不会下单或支付。'),
    'mcd_orders': (Args, '列出当前本人麦当劳交易记录，不查询其他用户订单。'),
    'mcd_order_status': (Order, '根据本人交易记录的plan_id查询真实麦当劳订单状态，不代表已支付。'),
    'mcd_prepare_cancel': (Cancel, '查询本人订单取消条件，仅在官方明确返回可取消及取消费用时准备取消确认方案；不会直接取消。'),
}


def _rows(data, keys):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)][:20]
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)][:20]
    raise ValueError('官方返回列表格式暂不支持，请稍后重试。')


def _pick(items, index):
    if index > len(items):
        raise ValueError('请先查询，并选择本轮候选中的序号。')
    return copy.deepcopy(items[index - 1])


def _in_city(address,expected):
    expected = expected.removesuffix('市')
    city = address.get('city','').strip().removesuffix('市')
    if city:
        return city == expected
    # Match the city at the administrative prefix, never an incidental road name.
    prefix = r'^(?:中国)?(?:(?:[^市]{1,12}省)|(?:(?:内蒙古|广西壮族|西藏|宁夏回族|新疆维吾尔)自治区))?'
    return bool(re.match(prefix + re.escape(expected) + r'(?:市|自治州|地区|盟)',
                         address.get('address','').strip()))


def _safe_order(data):
    detail = data.get('orderDetail', data) if isinstance(data, dict) else {}
    result = {k: copy.deepcopy(detail[k]) for k in (
        'orderStatus', 'orderStatusName', 'status', 'statusName', 'totalAmount',
        'realTotalAmount', 'pickupCode', 'expectDeliveryTime', 'takeWay') if k in detail}
    delivery = detail.get('deliveryInfo')
    if isinstance(delivery, dict):
        for key in ('expectDeliveryTime', 'riderNickName'):
            if delivery.get(key):
                result[key] = copy.deepcopy(delivery[key])
    # Prefer official human text. Numeric status fields have differed in live
    # responses, so never infer payment or fulfillment from an ambiguous code.
    return result


class McdScenario:
    schemas = SCHEMAS

    def __init__(self, transactions, provider=None, location_provider=None, map_provider=None):
        self.transactions = transactions
        self.provider = provider or McdService()
        self.location_provider = location_provider
        self.map_provider = map_provider

    async def _read(self, name, args):
        async with self.provider._connection() as call:
            return await call(name, args)

    def _owned(self, owner, plan_id):
        plan = self.transactions.get(owner, plan_id)
        if plan.get('provider') != 'mcd' or not (plan.get('order') or {}).get('order_id'):
            raise ValueError('没有属于当前用户的已创建麦当劳订单；结果未知时不能凭空补订单号。')
        return plan

    async def dispatch(self, session, owner, name, arguments, events):
        try:
            args = self.schemas[name][0].model_validate(arguments)
            if name in {'mcd_search_pickup','mcd_delivery_addresses','mcd_delivery_stores','mcd_menu','mcd_prepare_order','mcd_prepare_cart'}:
                self.transactions.invalidate_pending(owner)
            state = session.services.setdefault('mcd', {})
            if name=='mcd_recommend_meals':
                self.transactions.invalidate_pending(owner)
                return await recommend(self,state,args)
            if name=='mcd_choose_recommendation':
                self.transactions.invalidate_pending(owner)
                return await choose(self,state,owner,args.recommendation_id,events,args.choice_overrides,args.need_tableware,args.remark,args.quantity,args.budget_cents)
            if name in {'mcd_menu','mcd_search_pickup','mcd_delivery_addresses','mcd_delivery_stores'}:
                state.pop('recommended_meals',None)
            if name == 'mcd_address_draft':
                draft = state.setdefault('address_draft', {})
                values = args.model_dump(exclude_none=True, exclude={'reset'})
                if args.reset:
                    draft.clear()
                # Only changes invalidate an existing confirmation; showing progress does not.
                if values or args.reset:
                    self.transactions.invalidate_pending(owner)
                draft.update({key:value for key,value in values.items() if key != 'phone'})
                if 'phone' in values:
                    digits = str.maketrans('零〇一幺二两三四五六七八九', '0011223456789')
                    phone = re.sub(r'[\s-]', '', values['phone'].translate(digits))
                    if not re.fullmatch(r'1[0-9]{10}', phone):
                        return {'error':'手机号还没听清，请再说一遍11位完整手机号，原来已核对的信息还保留。'}
                    values['phone'] = phone
                draft.update(values)
                fields = [('city','请问这次在哪个城市收餐？'), ('address','请告诉我收餐的小区、酒店或大楼名称。'),
                    ('addressDetail','送到几号楼、几单元、几室？也可以明确说送到前台或门口。'),
                    ('contactName','收餐联系人怎么称呼？'), ('phone','骑手联系您用哪个11位手机号？')]
                missing = [key for key,_ in fields if not draft.get(key)]
                return {'draft':copy.deepcopy(draft), 'missing_fields':missing, 'ready':not missing,
                    'next':next((question for key,question in fields if key in missing),
                        '信息已齐，请复述核对后用mcd_prepare_address生成确认卡片，尚未保存地址。')}
            if name == 'mcd_cart':
                if args.action != 'show':
                    self.transactions.invalidate_pending(owner)
                cart = state.setdefault('cart', [])
                if args.action == 'clear':
                    cart.clear()
                elif args.action == 'remove':
                    if args.line_index is None:
                        raise ValueError('请说要去掉购物车中的第几项。')
                    _pick(cart, args.line_index)
                    cart.pop(args.line_index-1)
                elif args.action == 'update':
                    if args.line_index is None:
                        raise ValueError('请说要修改购物车中的第几项。')
                    _pick(cart, args.line_index)
                    line = cart[args.line_index-1]
                    if 'quantity' in args.model_fields_set:
                        line['quantity'] = args.quantity
                    if 'choices' in args.model_fields_set:
                        line['choices'] = [c.model_dump() for c in args.choices]
                elif args.action == 'add':
                    if args.product_index is None:
                        raise ValueError('请先选择当前菜单中的餐品。')
                    if not state.get('selected_store'):
                        raise ValueError('请先选收餐地址、门店和餐品。')
                    if len(cart) >= 10:
                        raise ValueError('本次购物车最多10项，请先删除不需要的餐品。')
                    product = _pick(state.get('products', []), args.product_index)
                    # Store the selected product, not an index that a later menu search changes.
                    cart.append({'product':product, 'quantity':args.quantity,
                                 'choices':[c.model_dump() for c in args.choices]})
                return {'cart':[{'index':i+1,'name':line['product']['name'], 'quantity':line['quantity'],
                                 'choices':line['choices']} for i,line in enumerate(cart)],
                        'next':'还没下单；可继续加餐、删除或核价整个购物车。' if cart else '购物车是空的，请先选餐。'}
            if name == 'mcd_current_location':
                point = self.location_provider(owner) if self.location_provider else None
                if not point:
                    events.append({'type':'location_request'})
                    return {'error':'没有当前有效定位，请授权定位或提供收餐地址。'}
                if not self.map_provider:
                    return {'error':'地址解析暂不可用，请提供城市和收餐地址。'}
                data = await self.map_provider.call('maps_regeocode', {
                    'location': f'{point["longitude"]},{point["latitude"]}'})
                return {'nearby_address':data, 'accuracy_meters':point['accuracy'],
                        'next':'请用户核对城市及附近地址，补充实际楼栋门牌、收餐联系人和完整手机号；定位不能代替门牌，不保存为家庭地址。'}
            if name == 'mcd_prepare_address':
                request = args.model_dump(exclude_none=True)
                quote = await self.quote('create_address', request)
                plan = self.transactions.prepare(owner, provider='mcd', action='create_address', request=request, quote=quote)
                events.append({'type':'action_plan','plan':plan})
                return {'plan':plan,'address_created':False,
                        'next':'请核对地址和联系方式，确认新增地址后才发送给麦当劳；这不会下单或付款。'}
            if name == 'mcd_search_pickup':
                state.clear()
                stores = await self.provider.search_stores(args.city, args.keyword)
                state.update(stores=stores[:20], mode='pickup')
                return {'stores': [dict(s, index=i+1) for i,s in enumerate(state['stores'])]}
            if name == 'mcd_delivery_addresses':
                state.clear()
                data = await self._read('delivery-query-addresses', {})
                addresses = _rows(data, ('addresses', 'addressList', 'deliveryAddressList', 'list'))
                # Keep identifiers private; do not store contact names or phones.
                candidates = [{'addressId': a.get('addressId'),
                    'address': a.get('fullAddress') or a.get('deliveryAddress') or a.get('address') or a.get('addressName') or '',
                    'addressDetail':a.get('addressDetail',''), 'city':a.get('city') or a.get('cityName') or ''}
                    for a in addresses if a.get('addressId')]
                state['addresses'] = [a for a in candidates if _in_city(a,args.city)]
                state['mode'] = 'delivery'
                state['city'] = args.city
                if not state['addresses']:
                    return {'addresses':[], 'needs_setup':True,
                        'next':f'当前接口没有返回可确认的{args.city}配送地址。可使用本次定位或用户提供的新地址，核对城市、地址、门牌、联系人及完整手机号后调用mcd_prepare_address；不要用其他城市旧地址代替。'}
                return {'addresses':[{'index':i+1,'address':a['address'], 'detail':a['addressDetail'], 'city':a['city']}
                    for i,a in enumerate(state['addresses'])],
                    'next':f'请确认{args.city}配送地址；若本次在新地方，请核对新地址及联系方式后准备新增地址确认卡片。'}
            if name == 'mcd_delivery_stores':
                address = _pick(state.get('addresses',[]), args.address_index)
                state.pop('stores',None); state.pop('products',None); state.pop('selected_store',None); state.pop('cart',None); state.pop('checkout_preferences',None)
                # Require explicit Beijing evidence rather than quietly delivering in another city.
                if not _in_city(address,state.get('city','北京')):
                    raise ValueError('当前地址未能确认属于所选城市，请核实地址后再查询，不自动更换城市。')
                data = await self._read('delivery-query-stores', {'addressId':address['addressId'],'beType':2})
                stores = _rows(data, ('stores','storeList','list'))
                state.update(stores=stores, mode='delivery', selected_address=address)
                return {'stores':[{'index':i+1,'name':s.get('storeName'), 'address':s.get('address',''),
                    'open':s.get('businessStatus'), 'hours':'–'.join(str(s.get(k) or '') for k in ('businessStartTime','businessEndTime'))}
                    for i,s in enumerate(stores)], 'next':'请用户选择营业中的可配送门店；暂不营业不能当成即时配送。' if stores else '该地址当前没有可配送门店，请换地址或稍后再查，不会改成到店自取。'}
            if name == 'mcd_menu':
                store = _pick(state.get('stores',[]),args.store_index)
                if state.get('selected_store') != store:
                    state.pop('cart',None); state.pop('checkout_preferences',None)
                state.pop('products',None); state.pop('selected_store',None)
                if store.get('open') is False or store.get('businessStatus') is False:
                    raise ValueError('当前门店显示未营业，请选择营业中的门店或稍后再试。')
                base = self._base(state,store)
                data = await self._read('query-meals',base)
                if not isinstance(data,dict) or not isinstance(data.get('meals'),dict):
                    raise ValueError('菜单格式暂不支持。')
                products = [dict(p, code=str(code)) for code,p in data['meals'].items()
                    if isinstance(p,dict) and p.get('name') and not p.get('canWithOrder')
                    and (not args.keyword or args.keyword in p['name'])][:20]
                state.update(selected_store=store, products=products)
                return {'products':[{'index':i+1,'name':p['name'],'image':p.get('image'),
                    'menu_price_yuan':p.get('currentPrice')} for i,p in enumerate(products)],
                    'note':'菜单价不是含配送费的最终报价；口味和健康安全不能从名称推断。'}
            if name == 'mcd_product_detail':
                product = _pick(state.get('products',[]),args.product_index)
                data = await self._read('query-meal-detail', {**self._base(state,state['selected_store']),'code':product['code']})
                self._check_detail(product,data)
                return {'name':product['name'],'rounds':data.get('rounds',[]),
                        'modification':data.get('modification'),
                        'note':'仅当前返回的套餐选项可选；特制改配尚未实现，不保证不辣或过敏安全。'}
            if name in {'mcd_prepare_order','mcd_prepare_cart'}:
                if args.budget_cents is not None:
                    state['budget_cents'] = args.budget_cents
                store = state.get('selected_store')
                if not store:
                    raise ValueError('请先选好本次门店和餐品。')
                if store.get('open') is False or store.get('businessStatus') is False:
                    raise ValueError('当前门店显示未营业，请选择营业中的门店，或稍后再试；不会准备可提交订单。')
                if name == 'mcd_prepare_cart':
                    lines = copy.deepcopy(state.get('cart', []))
                    if not lines:
                        raise ValueError('购物车是空的，请先选餐，不会创建空订单。')
                else:
                    lines = [{'product':_pick(state.get('products',[]),args.product_index),
                              'quantity':args.quantity, 'choices':[c.model_dump() for c in args.choices]}]
                base = self._base(state,store)
                items, all_labels = [], []
                for line in lines:
                    product = line['product']
                    line_choices = [Choice.model_validate(c) for c in line['choices']]
                    detail = await self._read('query-meal-detail',{**base,'code':product['code']})
                    self._check_detail(product,detail)
                    supplied = {c.round_id:c.code for c in line_choices}
                    rounds = detail.get('rounds',[])
                    if len(supplied)!=len(line_choices) or set(supplied)!={str(r['id']) for r in rounds}:
                        return {'needs_choices':True,'product':product['name'],'rounds':rounds,'next':'请用户选择每个套餐项目，不自动代选。'}
                    selection, labels = [], []
                    for row in rounds:
                        if row.get('minQuantity')!=1 or row.get('maxQuantity')!=1:
                            raise ValueError('该套餐多选规则暂不支持，请选择单品或其他套餐。')
                        choice = next((c for c in row.get('choices',[]) if str(c.get('code'))==supplied[str(row['id'])]),None)
                        if not choice: raise ValueError('套餐选项已变化，请重新选择。')
                        labels.append(choice.get('name',''))
                        selection.append({'round':str(row['id']),'comboItemList':[{'code':str(choice['code']),'quantity':1}]})
                    item={'productCode':product['code'],'quantity':line['quantity']}
                    if selection:item['roundList']=selection

                    items.append(item)
                    all_labels.extend(labels)
                payload={**base,'items':items}
                known=state.get('checkout_preferences',{})
                need_tableware=args.need_tableware if args.need_tableware is not None else known.get('needTableware')
                remark=args.remark if 'remark' in args.model_fields_set else known.get('remark','')
                if state['mode']=='delivery':
                    payload['addressId']=state['selected_address']['addressId']
                    if need_tableware is None:
                        return {'needs_tableware':True,'next':'请问需要餐具吗？餐具费以核价为准。'}
                    payload['needTableware']=need_tableware
                    payload['remark']=remark
                priced=await self._read('calculate-price',self._price_payload(payload))
                if state['mode']=='pickup':
                    ways=priced.get('takeWayList',[])
                    saved_way=next((i+1 for i,w in enumerate(ways) if w.get('code')==known.get('takeWayCode')),None)
                    take_way_index=args.take_way_index if args.take_way_index is not None else saved_way
                    if take_way_index is None:
                        return {'take_ways':[dict(w,index=i+1) for i,w in enumerate(ways)], 'next':'请用户明确选择堂食或外带等实际方式。'}
                    way=_pick(ways,take_way_index)
                    payload['takeWayCode']=way['code']
                    way_name=' · '.join(str(way.get(k,'')) for k in ('title','subtitle')).strip(' ·')
                else:way_name='麦乐送到家'
                request={'guided_order':bool(known),'payload':payload,'budget_cents':state.get('budget_cents'),'labels':{'store':store.get('storeName') or store.get('name'),
                    'product':'；'.join(f"{line['product']['name']} × {line['quantity']}" for line in lines) if len(lines)>1 else lines[0]['product']['name'],
                    'quantity':sum(line['quantity'] for line in lines),'choices':all_labels,
                    'image':lines[0]['product'].get('image'),
                    'images':[{'name':line['product']['name'],'image':line['product'].get('image'),'quantity':line['quantity']} for line in lines],'fulfillment':way_name,
                    'address':state.get('selected_address',{}).get('address',''),
                    'address_detail':state.get('selected_address',{}).get('addressDetail',''),
                    **({'phone_tail':state['selected_address']['phone_tail']} if state.get('selected_address',{}).get('phone_tail') else {}),
                    'tableware':('需要餐具' if need_tableware else '不需要餐具') if state['mode']=='delivery' else '',
                    'remark':remark if state['mode']=='delivery' else ''}}
                quote=await self.quote('create',request) if known and state['mode']=='delivery' else self._quoted(request,priced)
                plan=self.transactions.prepare(owner,provider='mcd',action='create',request=quote['request'],quote=quote)
                events.append({'type':'action_plan','plan':plan})
                return {'plan':plan,'order_created':False,'note':'尚未下单。需核对方案并明确确认；创建后仍需官方支付。'}
            if name == 'mcd_orders':
                return {'orders':[self.transactions.public(p) for p in self.transactions.list(owner,provider='mcd') if p.get('action')!='create_address']}
            if name in {'mcd_order_status','mcd_prepare_cancel'}:
                plan=self._owned(owner,args.plan_id)
                order_id=plan['order']['order_id']
                if name=='mcd_order_status':
                    data=await self._read('query-order',{'orderId':order_id})
                    return {'order':_safe_order(data),'note':'只报告官方状态，待支付不等于已付款、备餐或配送。'}
                request={'order_id':order_id,'reason':args.reason}
                quote=await self.quote('cancel',request)
                action=self.transactions.prepare(owner,provider='mcd',action='cancel',request=request,quote=quote)
                events.append({'type':'action_plan','plan':action})
                return {'plan':action,'cancelled':False}
            return {'error':'该麦当劳任务尚不支持。'}
        except ValidationError:
            return {'error':'请补充城市、收餐地址、具体门牌、联系人和11位完整手机号；性别不明确可不填。'} if name=='mcd_prepare_address' else {'error':'请使用本轮候选序号，并补充正确的商品数量或选项。'}
        except ValueError as exc:
            return {'error':str(exc)}
        except Exception:
            return {'error':'麦当劳本次操作未完成；请核对地址、门店和套餐选项，或稍后重试。尚未通过本工具下单或取消。'}

    @staticmethod
    def _check_detail(product,data):
        if not isinstance(data,dict) or ('code' in data and str(data['code']) != product['code']):
            raise ValueError('官方餐品详情与选择不一致，请重新查询，不会准备订单。')

    @staticmethod
    def _price_payload(payload):
        # These are create-order fields, not calculate-price inputs.
        return {k:copy.deepcopy(v) for k,v in payload.items() if k not in ('addressId','takeWayCode','remark')}

    @staticmethod
    def _base(state,store):
        delivery=state.get('mode')=='delivery'
        payload={'storeCode':store.get('storeCode') or store.get('code'),'orderType':2 if delivery else 1,'beType':2 if delivery else 1}
        if delivery:
            if not store.get('beCode'):raise ValueError('配送门店缺少业务编码。')
            payload['beCode']=store['beCode']
        return payload

    @staticmethod
    def _quoted(request,data):
        payload=request['payload']
        amount=_amount(data)
        budget=request.get('budget_cents')
        if budget is not None and (type(budget) is not int or budget < 1 or amount > budget):
            raise ValueError('最终核价超过明确预算，不能准备或执行；请重新选餐，或由用户明确修改预算。')
        ways=data.get('takeWayList',[])
        if payload['orderType']==1 and payload.get('takeWayCode') not in [w.get('code') for w in ways]:
            raise ValueError('取餐方式已变化。')
        fees={key:data[key] for key in ('deliveryPrice','packingPrice','tablewarePrice','realDeliveryPrice','deliveryFee','packingFee','tablewareFee') if key in data}
        fee_parts=[]
        for key,label in (('deliveryPrice','配送费'),('packingPrice','打包费'),('tablewarePrice','餐具费')):
            if key not in data:
                continue
            value=Decimal(str(data[key]))
            if not value.is_finite() or value<0 or value!=value.to_integral_value():
                raise ValueError('官方费用分项格式未知，不能准备订单。')
            fee_parts.append(f'{label} {value/100:.2f} 元')
        summary={**request['labels'],'amount_yuan':f'{amount/100:.2f}','fees':fees,
                 'fee_breakdown':'；'.join(fee_parts),
                 'fee_note':'总额以官方核价为准；未返回的费用分项不视为零。', 'payment':'创建后需官方渠道付款'}
        return {'request':copy.deepcopy(request),'summary':summary,'amount_cents':amount,
                'comparison':{'payload':payload,'amount_cents':amount,'budget_cents':budget,'labels':request['labels'],'fees':fees}}

    async def quote(self,action,request):
        if action=='create_address':
            payload = NewAddress.model_validate(request).model_dump(exclude_none=True)
            return {'request':payload, 'amount_cents':0, 'comparison':payload,
                    'summary':{'action':'新增配送地址', 'city':payload['city'],
                        'address':payload['address'], 'address_detail':payload['addressDetail'],
                        'contact':payload['contactName'] + (f"（{payload['gender']}）" if payload.get('gender') else ''), 'phone':payload['phone'],
                        'privacy':'确认后将以上信息发送并保存至麦当劳账号；不修改小瑞家庭地址，不创建餐饮订单。'}}
        if action=='create':
            request=copy.deepcopy(request)
            payload=request['payload']
            if payload['orderType']==2:
                if request.get('guided_order'):
                    data=await self._read('delivery-query-addresses',{})
                    addresses=_rows(data,('addresses','addressList','deliveryAddressList','list'))
                    address=next((a for a in addresses if str(a.get('addressId'))==str(payload['addressId'])),None)
                    if not address:raise ValueError('这个收餐地址已变更或删除，请重新查询地址后推荐。')
                    display=address.get('fullAddress') or address.get('deliveryAddress') or address.get('address')
                    if not display:raise ValueError('收餐地址信息暂时不完整，请重新核对。')
                    request['labels']['address']=display
                    request['labels']['address_detail']=address.get('addressDetail','')
                    request['labels'].pop('phone_tail',None)
                    phone=str(address.get('phone',''))
                    if re.fullmatch(r'1(?:[0-9]{10}|[0-9]{2}\*{4}[0-9]{4})',phone):request['labels']['phone_tail']=phone[-4:]

                data=await self._read('delivery-query-stores',{'addressId':payload['addressId'],'beType':2})
                stores=_rows(data,('stores','storeList','list'))
                selected=next((s for s in stores if s.get('storeCode')==payload['storeCode'] and s.get('beCode')==payload['beCode']),None)
                if not selected or selected.get('businessStatus') is False:
                    raise ValueError('所选门店现在无法即时配送这个地址，请重新选店；没有提交订单。')
            query=self._price_payload(payload)
            return self._quoted(request,await self._read('calculate-price',query))
        if action=='cancel':
            data=await self._read('query-order',{'orderId':request['order_id']})
            detail=data.get('orderDetail',data)
            # Public MCP does not guarantee a fee/eligibility contract. Fail closed.
            if detail.get('canCancel') is not True or 'cancelFee' not in detail:
                raise ValueError('官方没有明确返回可取消条件和取消费用，请到麦当劳官方渠道办理。')
            fee=Decimal(str(detail['cancelFee']))*100
            if not fee.is_finite() or fee<0 or fee!=fee.to_integral_value():raise ValueError('取消费用格式未知。')
            comparison={'order_id':request['order_id'],'cancel_fee_cents':int(fee),'status':detail.get('status') or detail.get('orderStatus')}
            return {'request':request,'summary':{'action':'取消麦当劳订单','cancel_fee_yuan':str(fee/100)},
                    'amount_cents':int(fee),'comparison':comparison}
        raise ValueError('不支持的交易动作。')

    async def query_order(self, order_id):
        return _safe_order(await self._read('query-order', {'orderId':order_id}))

    async def execute(self,action,request):
        if action=='create_address':
            payload = NewAddress.model_validate(request).model_dump(exclude_none=True)
            async with self.provider._connection() as call:
                data = await call('delivery-create-address', payload)
            if not isinstance(data,dict) or not data.get('addressId'):
                raise RuntimeError('新增地址结果未知，请重新查询地址列表核查，不得自动重试。')
            return {'address_id':str(data['addressId']), 'status':'address_created',
                    'note':'配送地址已创建，请重新查询配送地址并选择新地址继续点餐；尚未下单。'}
        if action=='create':
            data=await self.provider.create_order(request['payload'])
            if not data.get('order_id'):raise RuntimeError('创建结果未知，不得重试。')
            return {'order_id':data['order_id'],'payment_url':data.get('payment_url'),
                    'status':'created','note':'订单已创建，是否待支付需查询，尚未执行付款。'}
        if action=='cancel':
            # Only transaction manager invokes this after a freshly checked quote.
            async with self.provider._connection() as call:
                data=await call('cancel-order',{'orderId':request['order_id'],'cancelReasonCode':request['reason']})
            return {'order_id':request['order_id'],'status':'cancellation_requested',
                    'note':'取消请求已返回，最终状态请查询官方订单。'}
        raise ValueError('不支持的交易动作。')
