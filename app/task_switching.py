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
_DELIVERY = re.compile(r'外卖|外送|配送|送到|送来|送过来|送上门|送我|到[^，。！？!?]{1,60}(?:楼下|门口|家里|前台)')


def luckin_delivery_boundary(text, history):
    if re.search(r'不(?:要|用|想)?(?:外送|外卖|配送)|自取还是',text):
        return None
    merchants=set(_MERCHANT.findall(text))
    if merchants:
        matches=merchants=={'瑞幸'} and bool(_DELIVERY.search(text))
    else:
        matches=False
        if _FULFILLMENT_FOLLOWUP.fullmatch(text.strip()):
            for message in reversed(history):
                if message.get('role')!='user':continue
                previous=message.get('text','').strip()
                if _FULFILLMENT_FOLLOWUP.fullmatch(previous):continue
                matches=set(_MERCHANT.findall(previous))=={'瑞幸'}
                break
    if matches:
        return '小瑞目前只支持瑞幸到店自取，不能帮您点瑞幸外送。想送到您说的地点，可以在瑞幸官方 App 或小程序里查看是否能配送。'
    return None
