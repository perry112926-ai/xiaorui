"""Host handling for leaving a workflow; never confuse drafts with merchant orders."""
import re


def reminder_request(text):
    return bool(re.search(r'提醒我|提醒一下我|叫我',text)) and not re.search(r'不要|不用|别|取消',text)


def clear_drafts(session):
    # Actual and unknown transactions remain in the durable, owner-bound ledger.
    session.services.clear()
    session.stores.clear()
    session.meals.clear()


async def cancel_mcd_order(agent,session,owner,events):
    orders=[p for p in agent.actions.list(owner) if p['action']=='create' and (p.get('order') or {}).get('order_id')]
    if orders and orders[0]['provider']!='mcd':
        return None
    if orders:
        plan=orders[0]
        result=await agent.scenarios['mcd'].dispatch(session,owner,'mcd_order_status',{'plan_id':plan['id']},events)
        if result.get('error'):return result['error']
        order=result.get('order',{})
        status=next((str(order[k]) for k in ('orderStatusName','statusName','orderStatus','status') if order.get(k) and not str(order[k]).isdigit()),'')
        if re.search('已取消|已关闭|已退款|已完成',status):
            agent.actions.invalidate_pending(owner,status='cancelled')
            clear_drafts(session)
            return f'麦当劳官方显示这笔订单“{status}”，不需要再取消。已退出这次点餐，您可以直接说新的需求。'
        result=await agent.scenarios['mcd'].dispatch(session,owner,'mcd_prepare_cancel',{'plan_id':plan['id']},events)
        if result.get('plan'):return agent.proposal_text(result['plan'])
        return f'官方当前状态：{status or "暂未明确"}。'+result.get('error','暂时无法核实取消条件，请到麦当劳官方订单页处理。')+' 您可以直接说新的需求，不必继续付款。'
    pending=agent.actions.pending(owner)
    if pending and pending['provider']=='mcd' and pending['action']=='create':
        events.append({'type':'action_plan','plan':agent.actions.cancel_local(owner,pending['id'])})
    clear_drafts(session)
    return '本次没有可核实的真实麦当劳订单。已放弃本地待确认方案和购物车，您可以直接说新的需求。'


def release_completed_drafts(agent,session,owner):
    for provider,state in list(session.services.items()):
        plan_id=state.get('checkout_plan_id') if isinstance(state,dict) else None
        if not plan_id:continue
        plan=agent.actions.get(owner,plan_id)
        if plan['status']=='created':
            session.services.pop(provider,None)
            if provider=='mcd':session.stores.clear();session.meals.clear()


# Fulfillment-only follow-ups inherit the last user-selected merchant, never a
# merchant mentioned by the assistant or a saved cart from another task.
_FULFILLMENT_FOLLOWUP = re.compile(
    r'(?:(?:那|那就|请问|改成|改为|换成|我想|可以|能不能|能|支持)\s*)*'
    r'(?:外卖|外送|配送|送餐|送过来|送上门|送到家)'
    r'(?:可以吗|行吗|可以么|行不行|吗|呢|可以不|能不能|可不可以)?[。！？!?\s]*'
)
_MERCHANT = re.compile(r'瑞幸|麦当劳|肯德基|星巴克|美团|饿了么')
_NEGATED_MERCHANT = re.compile(r'(?:不是(?:要|想要)?|不要|别点|不点)\s*(?:瑞幸|麦当劳|肯德基|星巴克|美团|饿了么)')
_DELIVERY = re.compile(r'外卖|外送|配送|送到|送来|送过来|送上门|送我|到[^，。！？!?]{1,60}(?:楼下|门口|家里|前台)')


def turn_domain(text, history):
    """Resolve a short reply against the latest user task, not saved carts."""
    def explicit(value):
        value = _NEGATED_MERCHANT.sub('', value)
        matches = set()
        for domain, pattern in (
            ('luckin', '瑞幸'), ('mcd', '麦当劳|麦乐送|购物车'),
            ('didi', '滴滴|打车|叫车'), ('amap', '路线|导航|怎么走|怎么去|天气|下雨|公厕|厕所|药店'),
        ):
            if re.search(pattern, value):
                matches.add(domain)
        return next(iter(matches)) if len(matches) == 1 else None

    domain = explicit(text)
    if domain:
        return domain
    last = history[-1] if history else {}
    if (last.get('role')=='assistant'
            and last.get('text','').endswith('您愿意改成自取吗？')
            and re.fullmatch(r'(?:可以|好|对|行|愿意)[。！？!?\s]*',text.strip())):
        return 'luckin'
    followup = re.compile(r'(?:查一下|查查|继续(?:吧|呀)?|可以|对|好的?|就这个|就这份|第?[一二三四五12345](?:个|份)?|选[一二三四五12345]|不要冰的|热的|我已授权本次定位，请继续当前任务并核对实际地址；先不要提交交易)[。！？!?\s]*')
    if not followup.fullmatch(text.strip()):
        if (last.get('role')=='assistant'
                and last.get('text','').startswith('这次想在哪家瑞幸取餐')
                and re.fullmatch(r'[\w\s]{0,20}(?:楼下|门口|广场|中心|地铁站|世界)', text.strip())):
            return 'luckin'
        return None
    for message in reversed(history):
        if message.get('role') == 'user':
            previous = message.get('text', '')
            domain = explicit(previous)
            if domain:
                return domain
            if not followup.fullmatch(previous.strip()):
                break
    return None


def luckin_delivery_boundary(text, history):
    if re.search(r'不(?:要|用|想)?(?:外送|外卖|配送)|自取还是',text):
        return None
    merchants=set(_MERCHANT.findall(_NEGATED_MERCHANT.sub('',text)))
    if merchants:
        matches=merchants=={'瑞幸'} and bool(_DELIVERY.search(text))
    else:
        matches=False
        last_reply = next((m.get('text', '') for m in reversed(history) if m.get('role')=='assistant'), '')
        if ('不能帮您点瑞幸外送' in last_reply
                and re.fullmatch(r'[\w\s]{0,20}(?:楼下|门口|广场|中心|地铁站|世界)|可以|就那里', text.strip())
                and not re.search(r'自取|到店|打车|路线|天气', text)):
            return '瑞幸目前仅支持到店自取。您愿意改成自取吗？'
        if _FULFILLMENT_FOLLOWUP.fullmatch(text.strip()):
            for message in reversed(history):
                if message.get('role')!='user':continue
                previous=message.get('text','').strip()
                if _FULFILLMENT_FOLLOWUP.fullmatch(previous):continue
                matches=set(_MERCHANT.findall(_NEGATED_MERCHANT.sub('',previous)))=={'瑞幸'}
                break
    if matches and _FULFILLMENT_FOLLOWUP.fullmatch(text.strip()):
        return '您问的是刚才那杯瑞幸。小瑞不能帮您点瑞幸外送，送到您说的位置能不能配送，要在瑞幸 App 或小程序里查。'
    if matches:
        return '小瑞目前只支持瑞幸到店自取，不能帮您点瑞幸外送。想送到您说的地点，可以在瑞幸官方 App 或小程序里查看是否能配送。'
    return None
