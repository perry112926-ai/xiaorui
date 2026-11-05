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
