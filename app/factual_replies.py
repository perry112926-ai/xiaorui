"""Business text is a projection of host facts, never a model status claim."""
import re
from app.latency import terminal_reply
from app.speech import action_speech, progress_speech, dining_preferences

BUSINESS_WORDS = re.compile(r'麦当劳|瑞幸|滴滴|点餐|外卖|套餐|购物车|下单|订单|单子|叫车|打车|司机|师傅|付款|支付|取消订单|机票|航班|订票|出票|飞猪')


def business_turn(text, services):
    if BUSINESS_WORDS.search(text):return True
    # History may resolve a short continuation, but must not capture new tasks.
    continuation=re.fullmatch(r'(?:继续|继续吧|就这个|就这份|换一个|换一份|多少钱|要多久|不要冰的|热的|第?[一二三123](?:个|份)?)[。！？!?\s]*',text.strip())
    return bool(continuation and set(services)&{'mcd','didi','luckin'})


def business_reply(text, services, facts, events, profile=None, *, domain=None):
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
            if name in {'luckin_search_stores','luckin_search_products'}:
                key,label = ('stores','自取门店') if name=='luckin_search_stores' else ('products','饮品')
                if key in data:
                    choices = '、'.join(f"{row.get('index', i)}号{row['name']}"
                        for i,row in enumerate(data[key][:5],1) if row.get('name'))
                    if choices:
                        return f'查到这些瑞幸{label}。{choices}。您想选哪一个？'
                    return f'这次没有查到符合条件的瑞幸{label}。您想换个条件再查吗？'
            if domain=='luckin' and name in {'amap_search_places','amap_current_location'} and data.get('places'):
                places = '、'.join(f"{i}号{row['name']}" for i,row in enumerate(data['places'][:5],1) if row.get('name'))
                if places:
                    return f'查到这些地标：{places}。请选一个，我按这个位置查瑞幸自取门店。'
            if name in {'luckin_product_detail','luckin_switch_product'} and data.get('attributes'):
                options = '；'.join(f"{item['attribute']}可选{'、'.join(item['options'])}"
                    for item in data['attributes'] if item.get('attribute') and item.get('options'))
                if options:
                    return f"{data.get('name') or '这杯饮品'}。{options}。您想改哪项，还是按当前搭配核价？"
            if name=='didi_estimate_ride' and data.get('vehicles'):
                options = '、'.join(f"{i}号{row.get('productName','')}约{row['priceText']}元"
                    for i,row in enumerate(data['vehicles'][:5],1) if row.get('priceText'))
                if options:
                    places=data.get('actual_places',{})
                    start,end=((places.get(key) or {}).get('name') for key in ('from','to'))
                    route=f'平台匹配的上车点是{start}，下车点是{end}。' if start and end else ''
                    return f'{route}本次车型预估为{options}。请选择车型，之后再核对实际接送点和价格。'
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
    if re.search(r'取消.*(?:订单|单子)|不.*付钱|订单|单子|付款|支付',text):
        return '还没有取得这笔订单的最新官方状态，暂不能确认是否已付款或取消；您可以直接说新的需求。'
    target=domain or next((domain for domain,pattern in [('didi',r'滴滴|打车|叫车|司机|师傅'),('luckin',r'瑞幸|咖啡'),('mcd',r'麦当劳|点餐|外卖|套餐|购物车')] if re.search(pattern,text)),None)
    if target:services={target:services.get(target,{})}
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
