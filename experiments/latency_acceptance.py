"""Real model + official read-only queries in isolated storage. No transactions.

Run: python -m experiments.latency_acceptance --output /tmp/latency.json
Reports full useful-result time, not receipt/progress text. Each scenario is repeated.
"""
import argparse
import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path
from app.agent import AgentService
from app.plans import PlanStore
from app.contact_events import contact_reply_mode
from experiments.services_acceptance import ReadOnlyMcd, ReadOnlyOfficial


async def run(repeats):
    logging.disable(logging.CRITICAL)
    report={'model':None,'business_writes':False,'hardware_voice_tested':False,'turns':[]}
    with tempfile.TemporaryDirectory(prefix='xiaorui-latency-') as temp:
        root=Path(temp)
        agent=AgentService(ReadOnlyMcd(),PlanStore(root/'plans.db'),data_dir=root/'agent')
        report['model']=agent._config()['model']
        agent.actions._enabled=lambda _:False
        for name in ('luckin','didi'):
            agent.scenarios[name].provider=ReadOnlyOfficial(name)
        async def turn(owner,text,scenario):
            started=time.monotonic()
            try:
                result=await asyncio.wait_for(agent.chat(owner,text),55)
                timings=[t for t in result['trace'] if t.get('type')=='timing']
                row={'scenario':scenario,'seconds':round(time.monotonic()-started,3),
                     'answer':result['text'],'timings':timings,'ok':bool(result['text']),
                     'model_requests':sum(t.get('stage')=='model_request' for t in timings),
                     'grounded':any(t.get('type')=='host.grounded_reply' for t in result['trace'])}
                if scenario=='cart_quote':
                    row['ok']=any(e.get('type')=='action_plan' for e in result['events'])
            except Exception as e:
                row={'scenario':scenario,'ok':False,'seconds':round(time.monotonic()-started,3),'error_type':type(e).__name__}
            report['turns'].append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        mode=contact_reply_mode.set('text')
        try:
            for i in range(repeats):
                await turn('chat','我一个人在家有点闷，想找你聊会儿。','chat')
                await turn('weather','请查北京现在的天气。','weather')
            # Real public menu, synthetic selections; only price calculation allowed.
            session=agent._session('cart')
            scenario=agent.scenarios['mcd']
            async def step(name,args):
                result=await scenario.dispatch(session,'cart',name,args,[])
                if 'error' in result:raise RuntimeError('official_menu_unavailable')
                return result
            try:
                stores=await step('mcd_search_pickup',{'city':'北京','keyword':'王府井'})
                selected=next(s['index'] for s in stores['stores'] if s.get('open') is not False)
                products=await step('mcd_menu',{'store_index':selected,'keyword':'麦香鱼'})
                index=next(p['index'] for p in products['products'] if p['name']=='麦香鱼')
                detail=await step('mcd_product_detail',{'product_index':index})
                assert not detail.get('rounds')
                ways=await step('mcd_prepare_order',{'product_index':index})
                way=next(x['index'] for x in ways.get('take_ways',[]) if '外带' in str(x) or '打包' in str(x))
                for i in range(repeats):
                    session.services['mcd']['cart']=[]
                    await turn('cart',f'请把当前菜单第{index}个麦香鱼加入购物车，数量两份，选择第{way}种外带方式，核价整个购物车给我确认卡片，不要下单。','cart_quote')
            except Exception as e:
                report['menu_setup_error']=type(e).__name__
            # Production HTTP receipt -> worker -> real model/API -> completed result.
            import httpx
            from unittest.mock import patch
            from uuid import uuid4
            from app import main as host
            from app.contact import ContactService
            contact=ContactService(agent,root/'contact.db')
            report['http']=[]
            try:
                with patch.object(host,'agent',agent), patch.object(host,'contact',contact):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=host.app),base_url='http://localhost') as client:
                        (await client.get('/api/health')).raise_for_status()
                        for text,mode_name in [('我一个人在家有点闷，想找你聊会儿。','text'),('请查北京现在的天气。','speech')]:
                            started=time.monotonic()
                            accepted=await client.post('/api/contact/messages',json={'text':text,'client_id':str(uuid4()),'reply_mode':mode_name})
                            accepted.raise_for_status()
                            mid=accepted.json()['message_id']
                            async with asyncio.timeout(55):
                                while True:
                                    state=(await client.get('/api/contact/state')).json()
                                    done=[e for e in state['events'] if e['type'] in {'completed','failed'} and mid in e.get('message_ids',[e.get('message_id')])]
                                    if done:break
                                    await asyncio.sleep(.05)
                            event=done[-1]
                            response=event.get('response',{})
                            row={'reply_mode':mode_name,'ok':event['type']=='completed' and bool(response.get('text')),
                                 'seconds':round(time.monotonic()-started,3),'answer':response.get('text'),
                                 'speech_text':response.get('speech_text')}
                            report['http'].append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
            finally:
                await contact.close()
            report['all_completed']=all(x['ok'] for x in report['turns']+report['http']) and 'menu_setup_error' not in report
            report['within_8_seconds']=report['all_completed'] and all(x['seconds']<=8 for x in report['turns']+report['http'])
            assert all(p['status'] not in {'succeeded','submitting','unknown'} for p in agent.actions.list('cart'))
        finally:
            contact_reply_mode.reset(mode)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    result=asyncio.run(run(args.repeats))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('completed',result['all_completed'],'within_8_seconds',result['within_8_seconds'])
    raise SystemExit(0 if result['within_8_seconds'] else 1)
