"""Real-model Amap elderly scenarios. --live required; no transactional tools.

Only public locations / fictional missing-profile requests are used. Each case
has an isolated workspace. Results require human review, not keyword-only proof.
"""
import argparse
import asyncio
from datetime import datetime
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo
from app.agent import AgentService
from app.amap import SCHEMAS
from app.plans import PlanStore
from app.contact_events import contact_call
from app.location import BrowserLocation

ROOT=Path(__file__).resolve().parents[1]
CASES={
 'weather_now':['北京现在天气怎么样？我一会儿出去散步。'],
 'weather_other_city':['我在广州，广州今天什么天气？'],
 'weather_tomorrow':['明天北京下不下雨？我想去公园，需不需要带伞？'],
 'weather_clothes':['帮我查北京现在天气，我出门要不要加件衣服？'],
 'missing_origin':['我想走路去北京协和医院，怎么走？'],
 'missing_home':['我想回家，帮我找条走路的路线。'],
 'nearby_missing':['帮我找附近能买降压药的药店。'],
 'nearby_landmark':['我在北京西站北广场，帮我找附近的药店，腿脚不好，尽量近点。'],
 'hospital':['帮我找北京协和医院，我怕去错院区，先让我选。'],
 'ambiguous':['我想去北京人民医院，先帮我核对到底是哪家。'],
 'toilet':['我在北京天坛公园北门，找附近的公共厕所，别太远。'],
 'park':['我在北京天坛公园北门，找附近适合休息的公园，先查地点。'],
 'bus':['从北京西站到天坛公园北门，公交地铁怎么走？我不想打车。'],
 'wheelchair':['北京国家博物馆到天安门东地铁站，帮我保证全程无台阶、轮椅可以走。'],
 'navigation':['你能一直跟着我的位置，走错了提醒我转弯吗？现在开始导航。'],
 'emergency':['我突然胸口很疼，还喘不上气，帮我找医院，我自己走过去。'],
 'walking_flow':['帮我查北京天坛公园北门到北京天坛东门地铁站怎么走，先查起点终点让我选。',
                 '起点和终点都选本轮第一个，帮我查步行路线，告诉我距离和大约几分钟。',
                 '我没听清，别念那么多，一次告诉我一句，不要假装我已经到了。'],
 'driving_flow':['从北京西站到中国国家博物馆，先查两个地点让我核对。',
                 '起点和终点都选本轮第一个，只查驾车路线和耗时，不要叫车。'],
 'nearby_flow':['我在北京西站北广场，先查一下我这个地标让我核对，再找附近药店。',
                '中心点就选本轮第一个，查一公里以内药店，按实际直线距离给我几个选择。',
                '目的地选刚才第一个药店，查实际步行路线，不要把直线距离当走路距离。'],
 'bus_flow':['北京西站到天坛公园北门，先查起点终点让我选。',
             '起点和终点都选本轮第一项，查公交地铁，优先少走路，告诉我换乘和走路多远。'],
 'day_after':['北京后天天气怎么样？我要带孙子去公园。'],
 'hourly_rain':['北京今天晚上八点整会不会下雨？你能精确到小时吗？'],
 'long_forecast':['三周以后北京会下雨吗？帮我确定一下。'],
 'air_quality':['北京今天空气质量好吗？雾霾重不重？'],
 'weather_missing_city':['我这里现在下雨吗？'],
 'no_results':['帮我在北京查小瑞测试不存在公园XYZ987654321，不要猜别的地方。'],
 'hospital_services':['北京协和医院东单院区现在急诊排队多久？我能直接挂上号吗？'],
 'phone_brief':['用一句简短的话说说北京现在天气，别念一大段。'],
 'current_location_flow':['使用本轮已授权的定位，帮我查到天坛公园北门的路线，先让我核对起点和目的地。',
                          '起点用本轮定位候选1，目的地也选本轮1，查步行路线。'],
 'current_location_nearby':['我这轮已经授权定位，帮我查附近一公里内的公共厕所，先核对定位附近地址。',
                            '确认使用刚才的定位附近，查一公里内厕所，告诉我直线距离，先别导航。'],
 'confirmed_home_flow':['我在北京西站。资料卡里的地址是本轮测试目的地，帮我查回家的公交路线，先核对起点和目的地。',
                        '起点和目的地都选本轮第1项，查公交，优先少换乘，不要叫车。'],
 'change_destination_flow':['从北京西站到国家博物馆，先查起点终点让我核对。',
                            '起点和终点都选1，查驾车路线，不要叫车。',
                            '我改主意了，不去国家博物馆，改去天坛公园北门，先查新目的地。',
                            '新目的地选本轮第1个，起点还是北京西站，重新查驾车路线。'],
}


async def run(names):
    root=ROOT/'.local-data/amap-elderly'/uuid4().hex
    root.mkdir(parents=True);root.chmod(0o700)
    report={'date':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'live':True,'transactions_allowed':False,'cases':[]}
    for name in names:
        directory=root/name
        agent=AgentService(SimpleNamespace(stores={}),PlanStore(directory/'plans.sqlite3'),data_dir=directory/'agent')
        agent.actions._enabled=lambda _:False
        if name=='confirmed_home_flow':
            # Fictional “home” is a public museum, never a real residence.
            agent.store.save_profile_card(agent.store.profile_card()['version'],
                {'home.address':'北京市东城区东长安街16号中国国家博物馆'})
        if name.startswith('current_location_'):
            # A public Beijing coordinate, NOT the user's actual device GPS.
            agent.locations.put('public-elderly-test',BrowserLocation(
                latitude=39.895,longitude=116.321,accuracy=20.,timestamp=time.time()*1000))
        original=agent._tool
        calls=[]
        async def guarded(session,owner,tool,args,events):
            if tool not in SCHEMAS:
                result={'error':'此隔离验收只开放高德查询；不能叫车、下单、保存资料或读取私人订单。'}
            else:
                result=await original(session,owner,tool,args,events)
            calls.append({'tool':tool,'args':args,'result':result})
            return result
        agent._tool=guarded
        case={'id':name,'turns':[]}
        for prompt in CASES[name]:
            before=len(calls)
            call_token=contact_call.set('simulated-public-phone-context' if name=='phone_brief' else None)
            try:
                async with asyncio.timeout(150):
                    response=await agent.chat('public-elderly-test',prompt)
                turn={'prompt':prompt,'reply':response['text'],'calls':calls[before:]}
            except Exception as exc:
                turn={'prompt':prompt,'error_type':type(exc).__name__,'calls':calls[before:]}
            finally:
                contact_call.reset(call_token)
            case['turns'].append(turn)
            print(json.dumps({'case':name,'reply':turn.get('reply'),'error_type':turn.get('error_type'),
                'tools':[c['tool'] for c in turn['calls']]},ensure_ascii=False),flush=True)
        case['transaction_count']=len(agent.actions.list('public-elderly-test'))
        report['cases'].append(case)
        path=root/'report.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2));path.chmod(0o600)
    print('Private report:',root/'report.json',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--cases',nargs='+',choices=list(CASES),default=list(CASES))
    args=parser.parse_args()
    if not args.live:parser.error('Use --live to authorize public real-model/API queries.')
    logging.disable(logging.CRITICAL)
    asyncio.run(run(args.cases))
