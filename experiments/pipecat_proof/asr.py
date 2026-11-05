"""Synthetic PCM -> official streaming ASR. No production conversation access."""
import asyncio
from array import array
import json
import time
from uuid import uuid4
from websockets.asyncio.client import connect
from app.voice_protocol import encode_request, decode_response


def trim_trailing_silence(pcm, rate=16000):
    samples=array('h');samples.frombytes(pcm)
    step=rate//50
    last=0
    for start in range(0,len(samples),step):
        block=samples[start:start+step]
        if block and max(abs(v) for v in block)>250:
            last=start+len(block)
    if not last:raise ValueError('Synthetic audio is silent')
    return pcm[:last*2]


async def recognize(pcm, env):
    pcm=trim_trailing_silence(pcm)
    metrics={'synthetic_audio':True,'physical_microphone':False,'partials':0}
    ended=None;last=''
    async with connect('wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async',
        additional_headers={'X-Api-Key':env['DOUBAO_SPEECH_API_KEY'],
            'X-Api-Resource-Id':env.get('DOUBAO_ASR_RESOURCE_ID') or 'volc.seedasr.sauc.duration',
            'X-Api-Request-Id':str(uuid4())},proxy=None,open_timeout=10,close_timeout=2) as ws:
        await ws.send(encode_request(json.dumps({'user':{'uid':'xiaorui-isolated-proof'},
            'audio':{'format':'pcm','codec':'raw','rate':16000,'bits':16,'channel':1},
            'request':{'model_name':'bigmodel','enable_itn':True,'enable_punc':True,
                'enable_nonstream':False,'show_utterances':True,'result_type':'full'}}).encode()))
        async def upload():
            nonlocal ended
            for at in range(0,len(pcm),6400):
                chunk=pcm[at:at+6400]
                await asyncio.sleep(len(chunk)/32000)
                await ws.send(encode_request(chunk,audio=True))
            ended=time.monotonic()
            await ws.send(encode_request(b'',audio=True,final=True))
        sender=asyncio.create_task(upload())
        try:
            async with asyncio.timeout(40):
                async for frame in ws:
                    body,final=decode_response(frame)
                    result=body.get('payload_msg',body).get('result',{})
                    text=(''.join(r.get('text','') for r in result if isinstance(r,dict))
                        if isinstance(result,list) else result.get('text',''))
                    last=text or last
                    if final:
                        if not ended:raise RuntimeError('ASR finalized before synthetic input ended')
                        metrics['speech_end_to_transcript_ms']=round((time.monotonic()-ended)*1000)
                        break
                    if text:metrics['partials']+=1
                else:raise RuntimeError('ASR closed without a final transcript')
        finally:
            sender.cancel();await asyncio.gather(sender,return_exceptions=True)
    if not last:raise RuntimeError('ASR returned an empty transcript')
    return last,metrics
