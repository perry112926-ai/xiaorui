"""Isolated real-provider/HTTP acceptance; never submits orders or payments.

Read-only prices from a closed store validate decoding/formatting only. Such a
price is never promoted to a valid order proposal or claimed as an open store.
"""
import argparse
import asyncio
from decimal import Decimal
import json
import logging
from pathlib import Path
import tempfile
import time
from uuid import uuid4
import httpx
from app.runtime import build_services
from app.main import create_app
from app.mcd import _amount
from app.money import format_cents
from experiments.services_acceptance import ReadOnlyMcd


async def run(output,serve=False):
    logging.disable(logging.CRITICAL)
    from loguru import logger
    logger.remove()
    with tempfile.TemporaryDirectory(prefix='xiaorui-review-') as temp:
        dependencies=build_services(Path(temp))
        merchant=ReadOnlyMcd()
        dependencies.service=merchant
        agent=dependencies.agent
        agent.service=agent.skills.service=agent.scenarios['mcd'].provider=merchant
        agent.actions._enabled=lambda _:False
        application=create_app(services=dependencies)
        report={'business_writes':False,'real_queries':True,'physical_microphone':False,'steps':[]}
        if serve:
            import uvicorn
            server=uvicorn.Server(uvicorn.Config(application,host='127.0.0.1',port=8014,log_level='warning'))
            print('Isolated UI http://127.0.0.1:8014',flush=True)
            await server.serve();return
        async def message(client,text):
            start=time.monotonic()
            accepted=await client.post('/api/contact/messages',json={'text':text,'client_id':str(uuid4())})
            accepted.raise_for_status();mid=accepted.json()['message_id']
            async with asyncio.timeout(60):
                while True:
                    state=(await client.get('/api/contact/state')).json()
                    done=[e for e in state['events'] if e['type'] in {'completed','failed'} and mid in e.get('message_ids',[e.get('message_id')])]
                    if done:break
                    await asyncio.sleep(.05)
            event=done[-1]
            assert event['type']=='completed'
            response=event['response']
            report['steps'].append({'name':text,'ok':True,'seconds':round(time.monotonic()-start,3),'text':response['text'],
                                    'speech_source':response.get('speech_source'),'event_types':[e['type'] for e in response['events']]})
            print(json.dumps(report['steps'][-1],ensure_ascii=False),flush=True)
            return response
        try:
            async with application.router.lifespan_context(application):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application),base_url='http://localhost',timeout=65) as client:
                    (await client.get('/api/health')).raise_for_status()
                    await message(client,'我一个人在家有点闷，想找你聊会儿。')
                    weather=await message(client,'请查北京现在的天气。')
                    assert '高德报告时间' in weather['text']
                    business=await message(client,'请查询北京市北京西站附近的麦当劳门店，到店自取，只查询不要下单。')
                    assert business.get('speech_source')=='grounded'
                    stores_response=await client.post('/api/mcd/stores',json={'city':'北京','keyword':'北京西站'})
                    stores_response.raise_for_status();stores=stores_response.json()['stores']
                    report['stores_count']=len(stores);report['open_stores_count']=sum(s.get('open') is True for s in stores)
                    if not stores:raise RuntimeError('No public stores returned')
                    store=next((s for s in stores if s.get('open') is True),stores[0])
                    menu_response=await client.post('/api/mcd/menu',json={'store_code':store['code']})
                    menu_response.raise_for_status();products=menu_response.json()['products']
                    product=next((p for p in products if p['name']=='麦香鱼'),products[0])
                    details=await merchant.detail(store['code'],product['code'])
                    item={'productCode':product['code'],'quantity':1}
                    rounds=[]
                    for group in details.get('rounds',[]):
                        if group.get('minQuantity')!=1 or group.get('maxQuantity')!=1:raise RuntimeError('Unsupported quote-only test combo')
                        choice=next(c for c in group.get('choices',[]) if c.get('code') is not None)
                        rounds.append({'round':str(group['id']),'comboItemList':[{'code':str(choice['code']),'quantity':1}]})
                    if rounds:item['roundList']=rounds
                    async with merchant._connection() as read:
                        priced=await read('calculate-price',{'storeCode':store['code'],'orderType':1,'beType':1,'items':[item]})
                    cents=_amount(priced);formatted=format_cents(cents)
                    assert Decimal(formatted)==Decimal(cents)/100
                    report['steps'].append({'name':'official-price-decode-and-display','ok':True,'product':product['name'],
                        'amount_cents':cents,'display_yuan':formatted,'store_open':store.get('open'),
                        'valid_order_proposal':False,'note':'Read-only price conversion only; no preparation, submission or payment.'})
                    report['http_and_model_passed']=True
                    report['quote_display_verified']=True
                    assert not agent.actions.list(next(iter(agent.sessions)))
        except Exception as exc:
            report['error_type']=type(exc).__name__
            report['http_and_model_passed']=all(s.get('ok') for s in report['steps']) and len(report['steps'])>=3
            report.setdefault('quote_display_verified',False)
        finally:
            await dependencies.contact.close()
        report['passed']=report.get('http_and_model_passed',False) and report.get('quote_display_verified',False)
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
        return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('/tmp/xiaorui-review-acceptance.json'))
    parser.add_argument('--serve',action='store_true')
    args=parser.parse_args();result=asyncio.run(run(args.output,args.serve))
    if not args.serve:raise SystemExit(0 if result['passed'] else 1)
