"""Run bundled Silero VAD and Smart Turn on synthetic Chinese PCM evidence."""
import asyncio
import json
from pathlib import Path
import time
import numpy as np
import soxr
from loguru import logger
logger.remove()
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADState
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3


async def check(pcm):
    vad=SileroVADAnalyzer(sample_rate=16000)
    vad.set_sample_rate(16000)
    model=LocalSmartTurnAnalyzerV3()
    model.set_sample_rate(16000)
    # Real output evidence is 24 kHz mono PCM16.
    samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
    samples=soxr.resample(samples,24000,16000)
    states={};results=[]
    for name,fraction in [('fragment',.35),('complete',1)]:
        model.clear()
        audio=(samples[:int(len(samples)*fraction)]*32767).astype('<i2').tobytes()+bytes(16000*2//3)
        speaking=0
        for at in range(0,len(audio),640):
            chunk=audio[at:at+640]
            state=await vad.analyze_audio(chunk)
            voiced=state in {VADState.SPEAKING,VADState.STARTING}
            speaking+=voiced
            model.append_audio(chunk,is_speech=voiced)
        started=time.monotonic()
        state,metrics=await model.analyze_end_of_turn()
        results.append({'case':name,'decision':state.name,'inference_ms':round((time.monotonic()-started)*1000),
                        'vad_speech_frames':speaking})
    await model.cleanup()
    return {'synthetic_chinese_audio':True,'physical_microphone':False,'cases':results,
        'fragment_retained':results[0]['decision']=='INCOMPLETE',
        'complete_detected':results[1]['decision']=='COMPLETE'}


async def main():
    root=Path('.local-data/pipecat-proof')
    candidates=sorted(root.glob('*/turn-1.pcm'),key=lambda p:p.stat().st_mtime)
    if not candidates:raise RuntimeError('Run real model+TTS probe first')
    report=await check(candidates[-1].read_bytes())
    (root/'turns.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)

if __name__=='__main__':asyncio.run(main())
