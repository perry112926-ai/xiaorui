"""Business text is a projection of host facts, never a model status claim."""
import re
from app.latency import terminal_reply
from app.speech import action_speech, progress_speech, dining_preferences

BUSINESS_WORDS = re.compile(r'麦当劳|瑞幸|滴滴|点餐|外卖|套餐|购物车|下单|订单|单子|叫车|打车|司机|师傅|付款|支付|取消订单|机票|航班|订票|出票|飞猪')


def business_turn(text, services):
    from app.text_delivery import lightweight_chat
    return bool(BUSINESS_WORDS.search(text)) or (bool(set(services)&{'mcd','didi','luckin'}) and not lightweight_chat(text))


def business_reply(text, services, facts, events, profile=None):
    flights=[e for e in events if e.get('type')=='flight_result']
    if flights:
        from app.fliggy import flight_reply
        return flight_reply(flights[-1]['data'])
    plans=[e['plan'] for e in events if e.get('type') in {'plan','action_plan'}]
    if plans:
        return action_speech(plans[-1])
    if facts:
        name,data=facts[-1]
        if isinstance(data,dict):
            if data.get('order'):
                return progress_speech(name.split('_')[0],data['order'])
            reply=terminal_reply(name,data,text)
            if reply:
                return reply
            if data.get('next'):
                return str(data['next'])
            for key,label in [('stores','门店'),('addresses','配送地址'),('products','餐品'),('vehicles','车型'),('places','地点')]:
                if key in data:
                    rows=data[key]
                    if not rows:
                        return f'本次没有查到可用的{label}，您想换个地点或条件再查吗？'
                    if key=='stores' and all(row.get('open') is False for row in rows):
                        return '这次查到的门店目前都未营业。您想换个地点再查，还是稍后再试？'
                    names='、'.join(str(row.get('name') or row.get('productName') or row.get('display_name') or row.get('address') or '') for row in rows[:3])
                    return f'本次查到的{label}：{names}。请核对卡片，告诉我您想选哪一个。'
            if data.get('rounds') is not None:
                return f"{data.get('name','这份餐品')}的搭配以本次查询选项为准，您想选哪一种？"
    # No tool evidence: the model may ask for missing data, but cannot report a
    # successful operation. This host question covers the next supported step.
    if re.search(r'机票|航班|订票|出票|飞猪',text):
        return '您这次从哪个城市出发？我可以先查航班和预订入口，尚未订票或付款。'
    mcd=services.get('mcd',{})
    draft=mcd.get('address_draft',{})
    if draft:
        for key,question in [('city','这次在哪个城市收餐？'),('address','请告诉我收餐的小区或大楼名称。'),
                             ('addressDetail','这次送到几号楼、几单元、几室？'),('contactName','收餐联系人怎么称呼？'),('phone','骑手联系您用哪个完整手机号？')]:
            if not draft.get(key):return question
    if mcd.get('cart'):
        return '购物车里的餐品尚未下单。您想修改哪一项，还是继续核价？'
    if mcd.get('products') or mcd.get('recommended_meals'):
        return '请从这次查到的餐品里选一份，或者告诉我想换什么。尚未下单。'
    if 'didi' in services or re.search(r'叫车|打车|司机|师傅',text):
        return '目前没有新的叫车结果。您这次从哪里出发、要去哪里？'
    if 'luckin' in services or '瑞幸' in text:
        return '这次想在哪家瑞幸取餐，或附近是什么地标？'
    return '我现在可以帮您查麦当劳。请告诉我这次收餐的城市或附近地标。'
