"""Real HTTP/SSE + model acceptance against an isolated local test server.

python -m experiments.text_delivery_live_probe --live
Server must advertise X-Xiaorui-Acceptance: isolated on port 8013.
Uses synthetic dialogue, not the user's profile or browser cookie.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time
from uuid import uuid4
import httpx


async def main():
    observations=[];events=[];start=time.monotonic()
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8013',trust_env=False,timeout=20) as client:
        health=await client.get('/api/health');health.raise_for_status()
        if health.headers.get('x-xiaorui-acceptance')!='isolated':
            raise RuntimeError('This probe requires an isolated server')
        async def consume():
            async with client.stream('GET','/api/contact/events?after=0',timeout=None) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith('data: '):
                        events.append((time.monotonic(),json.loads(line[6:])))
        receiver=asyncio.create_task(consume())
        async def until(predicate,seconds=120):
            async with asyncio.timeout(seconds):
                while not predicate():
                    await asyncio.sleep(.02)
        async def send(text):
            sent=time.monotonic()
            response=await client.post('/api/contact/messages',json={'text':text,'client_id':str(uuid4()),'reply_mode':'text'})
            response.raise_for_status();receipt=response.json()
            item={'input':text,'receipt_ms':round((time.monotonic()-sent)*1000),
                  'immediate_ack':bool(receipt.get('event',{}).get('ack_text'))}
            observations.append(item)
            return receipt['message_id'],sent,item
        def completed(mid):
            return next(((t,e) for t,e in events if e['type'] in {'completed','failed'} and mid in e.get('message_ids',[e.get('message_id')])),None)
        try:
            mid,sent,first=await send('请列出6个轻松的周末活动，每项一句话。')
            await until(lambda:completed(mid))
            at,event=completed(mid)
            if event['type']!='completed':raise RuntimeError('model response failed')
            response=event['response'];task_id=response['task_id']
            delta=next((t for t,e in events if e['type']=='delta' and e['message_id']==mid),None)
            first.update(completed_ms=round((at-sent)*1000),first_delta_ms=round((delta-sent)*1000) if delta else None,
                         voice_deferred=response.get('speech_deferred',False))
            second,second_sent,item=await send('再用一句话告诉我，想放松时先做哪一项就好。')
            await until(lambda:completed(second))
            at2,event2=completed(second)
            if event2['type']!='completed':raise RuntimeError('follow-up failed')
            begun=next(t for t,e in events if e['type']=='started' and e['message_id']==second)
            item.update(started_ms=round((begun-second_sent)*1000),completed_ms=round((at2-second_sent)*1000))
            if first['voice_deferred']:
                await until(lambda:any(e['type']=='speech_ready' and e['task_id']==task_id for _,e in events),20)
            narration=next((t for t,e in events if e['type']=='speech_ready' and e['task_id']==task_id),None)
            greeting,when,greet=await send('在吗？')
            await until(lambda:completed(greeting),5)
            at3,event3=completed(greeting)
            greet.update(completed_ms=round((at3-when)*1000),host_reply=event3.get('response',{}).get('text')=='我在，您说。')
            result={'live_model':True,'http_sse':True,'isolated_profile':True,'business_writes':False,
                    'observations':observations,'text_before_narration':narration is not None and at<narration,
                    'next_turn_started_before_narration_finished':narration is not None and begun<narration,
                    'elapsed_seconds':round(time.monotonic()-start,2),'passed':bool(delta and first['immediate_ack'] and greet['host_reply'])}
        finally:
            receiver.cancel();await asyncio.gather(receiver,return_exceptions=True)
    directory=Path('.local-data/text-delivery-acceptance');directory.mkdir(parents=True,exist_ok=True)
    (directory/'latest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true')
    if not parser.parse_args().live:parser.error('--live required; calls the real model with synthetic text')
    raise SystemExit(asyncio.run(main()))
