"""Real synthetic call -> ASR -> contact -> recommendation cards -> confirmation.

--live uses an isolated production app on 127.0.0.1:8012. No physical microphone,
no merchant mutations, no order or payment. --serve leaves it for browser QA.
"""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import subprocess
import tempfile
import wave
from uuid import uuid4
import httpx
import uvicorn
from websockets.asyncio.client import connect
from app.agent import AgentService
from app.contact import ContactService
from app.plans import PlanStore
from experiments.services_acceptance import ReadOnlyMcd, ReadOnlyOfficial

ROOT=Path(__file__).resolve().parents[1]


async def run(serve=False,delivery=False,model=None,text_mode=False):
    logging.disable(logging.CRITICAL)
    from app import main as host
    directory=ROOT/'.local-data/mcd-call-journey'/uuid4().hex
    directory.mkdir(parents=True,mode=0o700)
    from experiments.mcd_delivery_acceptance import ReadOnlyMcd as DeliveryReadOnlyMcd
    agent=AgentService(DeliveryReadOnlyMcd() if delivery else ReadOnlyMcd(),PlanStore(directory/'plans.db'),data_dir=directory/'agent')
    if model:
        original_config=agent._config
        agent._config=lambda:{**original_config(),'model':model}
    agent.actions._enabled=lambda _:False
    for name in ('luckin','didi'):agent.scenarios[name].provider=ReadOnlyOfficial(name)
    host.agent=agent
    host.contact=ContactService(agent,directory/'contact.db')
    server=uvicorn.Server(uvicorn.Config(host.app,host='127.0.0.1',port=8012,log_level='critical',lifespan='off'))
    task=asyncio.create_task(server.serve())
    while not server.started:
        if task.done():await task
        await asyncio.sleep(.05)
    if serve:
        print('Isolated browser QA: http://127.0.0.1:8012',flush=True)
        await task;return 0
    report={'passed':False,'real_model_and_official_menu':True,'real_tts_asr':not text_mode,'business_writes':False,
            'physical_microphone':False,'text_mode':text_mode,'test_model':agent._config()['model'],'turns':[]}
    try:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8012',trust_env=False,timeout=210) as client:
            (await client.get('/api/health')).raise_for_status()
            call=(await client.post('/api/contact/calls',json={})).json()
            call_id=call['id']
            async def utter(text):
                if text_mode:
                    transcript=text
                else:
                    audio=await client.post('/api/voice/tts',json={'text':text});audio.raise_for_status()
                    with tempfile.TemporaryDirectory() as tmp:
                        mp3=Path(tmp)/'speech.mp3';wav=Path(tmp)/'speech.wav';mp3.write_bytes(audio.content)
                        subprocess.run(['/usr/bin/afconvert','-f','WAVE','-d','LEI16@16000','-c','1',str(mp3),str(wav)],check=True,capture_output=True)
                        with wave.open(str(wav),'rb') as stream:pcm=stream.readframes(stream.getnframes())
                    async with connect('ws://127.0.0.1:8012/api/voice/asr',origin='http://127.0.0.1:8012',proxy=None) as socket:
                        ready=json.loads(await asyncio.wait_for(socket.recv(),30));assert ready['type']=='ready'
                        async def upload():
                            for i in range(0,len(pcm),6400):
                                await socket.send(pcm[i:i+6400]);await asyncio.sleep(.2)
                            await socket.send(json.dumps({'type':'finish'}))
                        uploader=asyncio.create_task(upload())
                        try:
                            async with asyncio.timeout(90):
                                while True:
                                    message=json.loads(await socket.recv())
                                    if message['type']=='final':transcript=message['text'];break
                                    if message['type']=='error':raise RuntimeError('ASR failed')
                        finally:
                            if not uploader.done():uploader.cancel()
                            await asyncio.gather(uploader,return_exceptions=True)
                receipt=await client.post('/api/contact/messages',json={'text':transcript,'client_id':str(uuid4()),**({} if text_mode else {'call_id':call_id})});receipt.raise_for_status()
                mid=receipt.json()['message_id']
                async with asyncio.timeout(210):
                    while True:
                        state=(await client.get('/api/contact/state')).json()
                        done=[e for e in state['events'] if e['type'] in {'completed','failed'} and mid in e.get('message_ids',[e.get('message_id')])]
                        if done:break
                        await asyncio.sleep(.3)
                assert done[-1]['type']=='completed'
                if not text_mode:assert done[-1]['call_id']==call_id
                answer=done[-1]['response'];report['turns'].append({'input':text,'asr':transcript,'response':answer})
                audio_bytes=0
                if not text_mode:
                    response_audio=await client.post('/api/voice/tts',json={'text':answer['speech_text']});response_audio.raise_for_status();audio_bytes=len(response_audio.content)
                print(json.dumps({'turn':len(report['turns']),'transcript':transcript,'events':[e['type'] for e in answer['events']],'response_audio_bytes':audio_bytes},ensure_ascii=False),flush=True)
                return answer
            answer=await utter('我要麦当劳外卖，明确送到北京市海淀区中关村大街十一号e世界财富中心楼下，使用账号里这个地址，一人吃，预算六十元，不需要餐具。请直接推荐几个有图单人套餐，不创建订单。' if delivery else '用北京王府井公开地点测试麦当劳点餐，到店外带，一人吃，预算五十元。请推荐几个带图片的单人套餐，只准备方案，不创建订单。')
            cards=[c for e in answer['events'] if e['type']=='service_choices' for c in e['choices'] if c.get('recommendation_id')]
            assert 1<=len(cards)<=3 and all(c.get('image') and c.get('price_yuan') and c.get('contents') for c in cards)
            answer=await utter(cards[0]['prompt'] if text_mode else '我选第一份套餐。')
            plans=[e['plan'] for e in answer['events'] if e['type']=='action_plan']
            assert len(plans)==1 and plans[0]['status']=='awaiting_confirmation' and not plans[0].get('order')
            assert plans[0]['amount_cents']<=(6000 if delivery else 5000) and plans[0]['summary']['image']
            await client.post('/api/actions/'+plans[0]['id']+'/cancel-plan',json={})
            (await client.post('/api/contact/calls/'+call_id+'/end',json={})).raise_for_status()
            report.update(passed=True,delivery=delivery,recommendation_count=len(cards),selected_summary=plans[0]['summary'],amount_cents=plans[0]['amount_cents'],call_cards_and_confirmation=not text_mode,text_cards_and_confirmation=text_mode,
                payment_boundary='A real order and official payment page require user approval of this concrete proposal; not executed.')
    except Exception as exc:report['failure_type']=type(exc).__name__
    finally:
        path=directory/'report.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)
        await host.contact.close();server.should_exit=True;await task
    print(json.dumps({k:v for k,v in report.items() if k not in {'turns','selected_summary'}},ensure_ascii=False));print(str(path))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--serve',action='store_true');parser.add_argument('--delivery',action='store_true');parser.add_argument('--text',action='store_true');parser.add_argument('--model',help='Isolated test model override; never edits .env')
    args=parser.parse_args()
    if not (args.live or args.serve):parser.error('--live or --serve required')
    raise SystemExit(asyncio.run(run(args.serve,args.delivery,args.model,args.text)))
