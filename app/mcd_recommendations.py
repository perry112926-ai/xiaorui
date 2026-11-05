"""Preflighted single-person meals; selecting a card only prepares a proposal."""
from app.money import format_cents
import copy
import re
import secrets
import time
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RecommendationArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    store_index: int | None = Field(default=None, ge=1, le=20, strict=True)
    budget_cents: int | None = Field(default=None, ge=1, le=100000, strict=True)
    quantity: int = Field(default=1, ge=1, le=5, strict=True)
    meal_type: Literal['meal','single'] = 'meal'
    keyword: str = Field(default='', max_length=60)
    avoid_keywords: list[str] = Field(default_factory=list, max_length=10)
    avoid_iced_drinks: bool = False
    need_tableware: bool = True
    remark: str = Field(default='', max_length=50)


class RecommendedChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    recommendation_id: str = Field(min_length=1, max_length=80)
    choice_overrides: dict[str,str] = Field(default_factory=dict, max_length=20)
    need_tableware: bool | None = None
    remark: str | None = Field(default=None,max_length=50)
    quantity: int | None = Field(default=None,ge=1,le=5,strict=True)
    budget_cents: int | None = Field(default=None,ge=1,le=100000,strict=True)


def default_item(product, detail, args):
    """Only supported single-choice rounds; never advertise an unbuildable combo."""
    selections, labels = [], []
    rounds = detail.get('rounds', [])
    if not isinstance(rounds, list) or len(rounds)>20:
        raise ValueError('套餐规则暂不支持。')
    seen=set()
    for row in rounds:
        if not isinstance(row,dict) or row.get('id') is None or str(row['id']) in seen:raise ValueError('套餐项目格式未知。')
        seen.add(str(row['id']))
        if row.get('minQuantity') != 1 or row.get('maxQuantity') != 1:
            raise ValueError('套餐多选规则暂不支持。')
        choices=[c for c in row.get('choices',[]) if isinstance(c,dict) and c.get('code') is not None and c.get('name')
                 and not any(word and word in c['name'] for word in args.avoid_keywords)]
        if args.avoid_iced_drinks and re.search(r'饮料|饮品|咖啡',row.get('name','')):
            choices=[c for c in choices if re.search('热|温',c['name']) and not re.search('冰|雪',c['name'])]
        if not choices:
            raise ValueError('没有符合本次要求的套餐选项。')
        choice=next((c for c in choices if c.get('quantity')==1), choices[0])
        selections.append({'round':str(row['id']),'comboItemList':[{'code':str(choice['code']),'quantity':1}]})
        labels.append(choice['name'])
    item={'productCode':product['code'],'quantity':1}
    if selections:item['roundList']=selections
    return item, labels


def public_recommendations(state):
    return [{'index':i+1,'meal_type':r.get('meal_type','meal'), 'recommendation_id':r['id'], 'name':r['name']+(f" × {r['request']['labels']['quantity']}" if r['request']['labels']['quantity']>1 else ''), 'image':r['image'],
             'menu_price_yuan':r.get('menu_price_yuan'), 'quoted_price_yuan':format_cents(r['quote']['amount_cents']),
             'choices':r['request']['labels']['choices'],'fee_breakdown':r.get('fee_breakdown',''),
             'rounds':[{'id':str(row['id']),'name':row.get('name',''),'choices':[{'code':str(c['code']),'name':c.get('name','')} for c in row.get('choices',[])[:50]]} for row in r['detail'].get('rounds',[])], 'fulfillment':r['request']['labels']['fulfillment']}
            for i,r in enumerate(state.get('recommended_meals',[]))]


async def recommend(scenario, state, args):
    state.pop('recommended_meals',None)
    if not state.get('stores') and not state.get('selected_store'):
        raise ValueError('请先提供收餐地址或自取地标，我来查可用门店。')
    # One official MCP session for the batch, avoiding repeated discovery/connects.
    async with scenario.provider._connection() as read:
        result=await _recommend(scenario,state,args,read)
        if not result['products'] and state.get('mode')=='pickup':
            alternative=next((i+1 for i,s in enumerate(state.get('stores',[])) if s!=state.get('selected_store') and s.get('open') is not False),None)
            if alternative is not None:result=await _recommend(scenario,state,args.model_copy(update={'store_index':alternative}),read)
        return result


async def _recommend(scenario,state,args,read):
    state.pop('recommended_meals',None)
    if args.store_index is not None:
        stores=state.get('stores',[])
        if args.store_index>len(stores):raise ValueError('请先确认本次收餐位置。')
        store=stores[args.store_index-1]
    else:
        store=state.get('selected_store') or next((s for s in state.get('stores',[])
            if s.get('open') is not False and s.get('businessStatus') is not False),None)
    if not store:raise ValueError('请先提供收餐地址或自取地标，我来查可用门店。')
    if state.get('mode')!='delivery' and (store.get('open') is False or store.get('businessStatus') is False):
        store=next((s for s in state.get('stores',[]) if s.get('open') is not False and s.get('businessStatus') is not False),None)
        if not store:raise ValueError('附近暂时没有营业门店，请稍后再试。')
    if state.get('selected_store') != store:state.pop('cart',None)
    state['selected_store']=copy.deepcopy(store)
    if args.budget_cents is not None:state['budget_cents']=args.budget_cents
    base=scenario._base(state,store)
    if state.get('mode')=='delivery':
        address=state.get('selected_address')
        if not address:raise ValueError('还需要确认本次收餐地址。')
        # Reuse the same delivery eligibility check as final confirmation.
        data=await read('delivery-query-stores',{'addressId':address['addressId'],'beType':2})
        stores=data if isinstance(data,list) else next((data[k] for k in ('stores','storeList','list') if isinstance(data.get(k),list)),[])
        available=[s for s in stores if isinstance(s,dict) and s.get('storeCode') and s.get('beCode') and s.get('businessStatus') is not False]
        matching=next((s for s in available if s['storeCode']==base['storeCode'] and s['beCode']==base.get('beCode')),None)
        if not matching:
            if not available:raise ValueError('这个地址目前没有可配送的营业门店，请稍后再试或提供其他收餐地址。')
            store=available[0];state['selected_store']=copy.deepcopy(store);base=scenario._base(state,store)
    data=await read('query-meals',base)
    if not isinstance(data,dict) or not isinstance(data.get('meals'),dict):raise ValueError('菜单暂时未能读取。')
    candidates=[]
    for code,p in data['meals'].items():
        if not isinstance(p,dict) or not p.get('name') or not str(p.get('image','')).startswith('https://') or p.get('canWithOrder'):continue
        name=p['name']
        if re.search(r'双人|[二两三四五六七八九十2-9]人|多人|分享|全家|儿童|生日|派对|桶|会员|月卡|年卡|周卡|季卡|次卡|礼品卡|储值|券|订阅|兑换',name):continue
        if args.meal_type=='meal' and not re.search(r'套餐|单人|[三四两]件套',name):continue
        if args.meal_type=='single' and re.search(r'套餐|件套',name):continue
        if args.keyword and args.keyword not in name:continue
        if any(word and word in name for word in args.avoid_keywords):continue
        candidates.append(dict(p,code=str(code)))
    # Prefer explicitly single meals, without inventing nutritional suitability.
    candidates.sort(key=lambda p:('单人' not in p['name'],len(p['name'])))
    found=[]
    for product in candidates[:12]:
        try:
            detail=await read('query-meal-detail',{**base,'code':product['code']})
            scenario._check_detail(product,detail)
            if args.meal_type=='single' and detail.get('rounds'):continue
            item,labels=default_item(product,detail,args)
            item['quantity']=args.quantity
            payload={**base,'items':[item]}
            if state.get('mode')=='delivery':
                payload.update(addressId=state['selected_address']['addressId'],needTableware=args.need_tableware,remark=args.remark)
            priced=await read('calculate-price',scenario._price_payload(payload))
            if state.get('mode')=='pickup':
                way=next((w for w in priced.get('takeWayList',[]) if '外带' in str(w) or '自提' in str(w)),None)
                if not way:continue
                payload['takeWayCode']=way['code'];fulfillment='外带 · 店内自提'
            else:fulfillment='麦乐送到家'
            address=state.get('selected_address',{})
            request={'guided_order':True,'payload':payload,'budget_cents':state.get('budget_cents'),'labels':{
                'store':store.get('storeName') or store.get('name'),'product':product['name'], 'quantity':args.quantity,
                'choices':labels,'fulfillment':fulfillment,'address':address.get('address',''),
                'address_detail':address.get('addressDetail',''),'image':product['image'],
                'tableware':('需要餐具' if args.need_tableware else '不需要餐具') if state.get('mode')=='delivery' else '',
                'remark':args.remark,'defaults':'按当前套餐可用搭配准备，可直接说要换哪一项。'}}
            quote=scenario._quoted(request,priced)
            found.append({'id':secrets.token_urlsafe(16),'meal_type':args.meal_type,'name':product['name'],'image':product['image'],
                'menu_price_yuan':product.get('currentPrice'),
                'product':{key:product[key] for key in ('code','name','image')},
                'detail':{'rounds':[{'id':str(row['id']),'name':row.get('name',''),'minQuantity':1,'maxQuantity':1,
                    'choices':[{'code':str(c['code']),'name':c['name']} for c in row.get('choices',[]) if c.get('code') is not None and c.get('name')]} for row in detail.get('rounds',[])]},
                'request':request,'fee_breakdown':quote['summary'].get('fee_breakdown',''),'quote':{'amount_cents':quote['amount_cents']},'expires_at':time.time()+300})
            if len(found)==3:break
        except (ValueError,RuntimeError,KeyError,TypeError):
            # Failed detail/build/price is excluded before the user sees a recommendation.
            continue
    state['recommended_meals']=found
    state['products']=[copy.deepcopy(r['product']) for r in found]
    state['recommendation_args']=args.model_dump()
    return {'products':public_recommendations(state),'preflighted':True,
            'next':'只推荐以上已核价的单人套餐，图片、搭配与总额一并展示。用户选一份后调用mcd_choose_recommendation直接准备最终确认，不再逐项追问；可按用户要求调整。' if found else
                   '当前没有查到有图且能按本次要求核价的单人套餐；不要推荐未通过的套餐，可换店或放宽用户明确允许的条件。'}


async def choose(scenario,state,owner,id,events,overrides=None,need_tableware=None,remark=None,quantity=None,budget_cents=None):
    meal=next((r for r in state.get('recommended_meals',[]) if r['id']==id),None)
    if not meal:raise ValueError('这组推荐已失效，请重新查几份带图片的套餐。')
    if meal['expires_at']<=time.time():
        updated={key:value for key,value in {'need_tableware':need_tableware,'remark':remark,'quantity':quantity,'budget_cents':budget_cents}.items() if value is not None}
        args=RecommendationArgs.model_validate({**state.get('recommendation_args',{}),**updated})
        fresh=await recommend(scenario,state,args)
        replacement=next((r for r in state.get('recommended_meals',[]) if r['name']==meal['name']),None)
        if replacement:
            replacement['request']['labels']['信息更新']='等待时间较长，搭配与费用已重新核对，请以这份确认卡为准。'
            return await choose(scenario,state,owner,replacement['id'],events,overrides,need_tableware,remark,quantity,budget_cents)
        fresh['note']='原套餐现在不可选，我已重新核对这些带图套餐。'
        return fresh
    request=copy.deepcopy(meal['request'])
    changes={key:value for key,value in {'need_tableware':need_tableware,'remark':remark,'quantity':quantity,'budget_cents':budget_cents}.items() if value is not None}
    state.setdefault('recommendation_args',{}).update(changes)
    if budget_cents is not None:
        state['budget_cents']=budget_cents;request['budget_cents']=budget_cents
    if quantity is not None:
        request['payload']['items'][0]['quantity']=quantity;request['labels']['quantity']=quantity
    if request['payload']['orderType']==2:
        if need_tableware is not None:
            request['payload']['needTableware']=need_tableware;request['labels']['tableware']='需要餐具' if need_tableware else '不需要餐具'
        if remark is not None:request['payload']['remark']=remark;request['labels']['remark']=remark
    if overrides:
        detail=await scenario._read('query-meal-detail',{**scenario._base(state,state['selected_store']),'code':meal['product']['code']})
        scenario._check_detail(meal['product'],detail)
        rows={str(row['id']):row for row in detail.get('rounds',[])}
        if not set(overrides)<=set(rows):raise ValueError('套餐选项已改变，请重新推荐。')
        selections=request['payload']['items'][0].get('roundList',[])
        for selection in selections:
            rid=selection['round']
            if rid in overrides:
                if not any(str(c.get('code'))==overrides[rid] for c in rows[rid].get('choices',[])):
                    raise ValueError('这个配餐当前不能选，请重新查询。')
                selection['comboItemList'][0]['code']=overrides[rid]
        request['labels']['choices']=[next(c['name'] for c in rows[s['round']]['choices'] if str(c['code'])==s['comboItemList'][0]['code']) for s in selections]
    try:
        quote=await scenario.quote('create',request)
    except (ValueError,RuntimeError) as exc:
        result=await recommend(scenario,state,RecommendationArgs.model_validate(state.get('recommendation_args',{})))
        result['note']='门店刚更新了可售或费用，我重新核对了可选套餐，请看新图片。'
        if not result['products']:result['error']=str(exc)
        return result
    if quote['amount_cents']!=meal['quote']['amount_cents']:
        quote['summary']['quote_change']=f"推荐时 {format_cents(meal['quote']['amount_cents'])} 元，现在 {format_cents(quote['amount_cents'])} 元，请核对新总价。"
    plan=scenario.transactions.prepare(owner,provider='mcd',action='create',request=quote['request'],quote=quote)
    selected=quote['request']['payload']['items'][0]
    state['cart']=[{'product':copy.deepcopy(meal['product']),'quantity':selected['quantity'],
        'choices':[{'round_id':row['round'],'code':row['comboItemList'][0]['code']} for row in selected.get('roundList',[])]}]
    if quote['request']['payload']['orderType']==2:
        state['selected_address'].update(address=quote['request']['labels']['address'],addressDetail=quote['request']['labels'].get('address_detail',''))
        state['selected_address'].pop('phone_tail',None)
        if quote['request']['labels'].get('phone_tail'):state['selected_address']['phone_tail']=quote['request']['labels']['phone_tail']
    state['checkout_preferences']={key:quote['request']['payload'][key] for key in ('needTableware','remark','takeWayCode') if key in quote['request']['payload']}
    events.append({'type':'action_plan','plan':plan})
    return {'plan':plan,'order_created':False,'note':'套餐已搭配并核价，请最后核对总额与收餐信息；确认后才创建真实待支付订单。'}


def resolve_selection(session,text):
    match=re.fullmatch(r'(?:选择|我选|选|就选|就要|我要|就|要)?第?([123一二三])(?:份|个|款)?(?:推荐)?(?:套餐|餐品)?(?:[：:]([^。]+))?(?:就行|就好)?[吧呀啊呢。！!？?]*',text.strip())
    phrase=text.strip().rstrip('。！!，, ')
    delegated=phrase in {'你帮我选','你来选','帮我选一份','随便来一份','就按默认','按默认来','你选吧'}
    cheapest=phrase in {'选最便宜的','给我最便宜的','就最便宜的'}
    if not match and not delegated and not cheapest:return None
    number=1 if not match else int(match[1]) if match[1].isdigit() else '一二三'.index(match[1])+1
    # Only the most recent visible choice group can authorize a selection.
    cards=None
    for message in reversed(session.display):
        for event in reversed(message.get('events',[])):
            if event.get('type')=='service_choices':cards=event.get('choices',[]);break
        if cards is not None:break
    if not cards or not all(c.get('recommendation_id') for c in cards) or number>len(cards):return None
    if cheapest:
        priced=[(Decimal(c['price_yuan']),i) for i,c in enumerate(cards) if c.get('price_yuan')]
        if not priced:return None
        number=min(priced)[1]+1
    card=cards[number-1]
    if match and match[2] and match[2]!=card['label']:return None
    return card['recommendation_id']
