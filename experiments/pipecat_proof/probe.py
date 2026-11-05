"""Run isolated Pipecat + real Ark + Doubao experiments, never user profiles/tools.

Use the isolated requirements.txt environment; --live is mandatory.
Audio evidence is synthetic and stays in ignored .local-data/pipecat-proof/.
"""
import argparse
import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime
import importlib.metadata
import json
import math
from pathlib import Path
import statistics
import time
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from loguru import logger
from openai import AsyncOpenAI
from experiments.pipecat_proof.asr import recognize
from experiments.pipecat_proof.evaluation import evaluate, distribution
from pipecat.frames.frames import (ErrorFrame, InterruptionFrame, LLMContextFrame,
    LLMFullResponseEndFrame, LLMTextFrame, TTSAudioRawFrame, TTSTextFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.workers.runner import WorkerRunner
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.tts_service import TTSService

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ('你是小瑞，正在和用户电话聊天。直接用简短自然的中文回答当前这句话，一般只说一两句。'
          '称呼对方为您。承接上下文，不重复“我在，您说”或“收到”。不推断季节，不假装自己有现实经历，不虚构已完成的事情。'
          '本次是隔离闲聊，没有生活服务工具，不索取个人资料。')
CASES = [
    '我一个人在家有点闷，陪我聊一会儿吧。',
    '我今天去了公园，看见好多花。',
    '是黄色的，你猜是什么花？',
    '别猜了，我也不知道，我们换个话题。',
    '说个周末在家能做的轻松活动。',
    '不想看电视，还有别的办法吗？',
    '你刚才建议的活动，用一句话再说一下。',
    '我还没说完，我想想。',
    '想好了，我想听一个很短的小故事。',
    '今天先聊到这里吧。',
]


def speech_config(env):
    return {'key': env.get('DOUBAO_SPEECH_API_KEY', ''),
            'resource': env.get('DOUBAO_TTS_RESOURCE_ID') or 'seed-tts-2.0',
            'voice': env.get('DOUBAO_TTS_VOICE') or 'zh_female_vv_uranus_bigtts'}


async def pcm_stream(client, cfg, text, rate=24000):
    """Official HTTP streaming PCM; keep the connection pool warm across sentences."""
    async with client.stream('POST', 'https://openspeech.bytedance.com/api/v3/tts/unidirectional',
        headers={'X-Api-Key': cfg['key'], 'X-Api-Resource-Id': cfg['resource'],
                 'X-Api-Request-Id': str(uuid4())},
        json={'req_params': {'text': text, 'speaker': cfg['voice'],
              'audio_params': {'format': 'pcm', 'sample_rate': rate}}}) as response:
        response.raise_for_status()
        completed = False
        async for line in response.aiter_lines():
            if not line.strip() or line.startswith(('event:', ':')):
                continue
            data = json.loads(line[5:].strip() if line.startswith('data:') else line)
            if data.get('code', 0) not in (0, 20000000):
                raise RuntimeError('TTS provider rejected synthetic text')
            if data.get('data'):
                yield base64.b64decode(data['data'], validate=True)
            completed = completed or data.get('code') == 20000000
        if not completed:
            raise RuntimeError('TTS ended without completion marker')


@dataclass
class Turn:
    user: str
    start: float = field(default_factory=time.monotonic)
    first_text: float | None = None
    llm_end: float | None = None
    first_audio: float | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    audio_ready: asyncio.Event = field(default_factory=asyncio.Event)
    text: str = ''
    spoken: str = ''
    pcm: bytearray = field(default_factory=bytearray)
    errors: list = field(default_factory=list)
    audio_times: list = field(default_factory=list)


class Meter(FrameProcessor):
    def __init__(self, state):
        super().__init__(); self.state = state

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        t = self.state['turn']
        if isinstance(frame, LLMTextFrame) and frame.text:
            t.first_text = t.first_text or time.monotonic(); t.text += frame.text
        if isinstance(frame, LLMFullResponseEndFrame):
            t.llm_end = time.monotonic()
        await self.push_frame(frame, direction)


class DirectArk(OpenAILLMService):
    _requires_api_key = True

    def create_client(self, api_key=None, base_url=None, **kwargs):
        return AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0,
            http_client=httpx.AsyncClient(trust_env=False, timeout=30))


class DoubaoPCM(TTSService):
    def __init__(self, client, cfg):
        super().__init__(sample_rate=24000, push_start_frame=True, push_stop_frames=True)
        self.client, self.cfg = client, cfg

    async def run_tts(self, text, context_id):
        async for audio in pcm_stream(self.client, self.cfg, text):
            yield TTSAudioRawFrame(audio=audio, sample_rate=24000, num_channels=1, context_id=context_id)


class Sink(FrameProcessor):
    """Server PCM availability only. Does not pretend this is audible playback."""
    def __init__(self, state):
        super().__init__(); self.state = state

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        t = self.state['turn']
        if isinstance(frame, TTSAudioRawFrame) and frame.audio:
            now = time.monotonic(); t.first_audio = t.first_audio or now
            t.audio_times.append(now); t.pcm.extend(frame.audio); t.audio_ready.set()
        if isinstance(frame, TTSTextFrame):
            t.spoken += frame.text
        if isinstance(frame, ErrorFrame):
            t.errors.append(type(frame).__name__); t.done.set()
        if isinstance(frame, LLMFullResponseEndFrame):
            t.done.set()
        await self.push_frame(frame, direction)


def record(t):
    def ms(at): return round((at-t.start)*1000) if at else None
    return {'input': t.user, 'answer': t.text, 'first_text_ms': ms(t.first_text),
            'first_pcm_ms': ms(t.first_audio), 'llm_end_ms': ms(t.llm_end),
            'pcm_bytes': len(t.pcm), 'errors': t.errors,
            'audio_before_model_end': bool(t.first_audio and t.llm_end and t.first_audio < t.llm_end)}


async def run(args):
    logger.remove()  # No provider debug logs or credential-bearing exceptions.
    env = dotenv_values(ROOT/'.env')
    for key in ['ARK_API_KEY', 'ARK_MODEL', 'DOUBAO_SPEECH_API_KEY']:
        if not env.get(key): raise RuntimeError(f'Missing configured field: {key}')
    directory = ROOT/'.local-data/pipecat-proof'/uuid4().hex
    directory.mkdir(parents=True)
    report = {'checked_at': datetime.now().astimezone().isoformat(),
              'framework': 'pipecat-ai', 'version': importlib.metadata.version('pipecat-ai'),
              'model': args.model or env['ARK_MODEL'], 'synthetic_dialogue': True,
              'personal_profile_loaded': False, 'business_tools': False,
              'production_integrated': False, 'physical_microphone': False,
              'browser_playback_tested': False, 'asr_endpoint': 'explicit_finish_after_last_packet',
              'vad_boundary_in_end_to_end_measurement': False, 'turns': []}
    state = {'turn': Turn('setup')}
    history = [{'role':'system','content':PROMPT}]
    llm = DirectArk(api_key=env['ARK_API_KEY'], base_url=env['ARK_BASE_URL'],
        settings=OpenAILLMService.Settings(model=report['model'],max_tokens=240,extra={'extra_body': {'thinking': {'type': 'disabled'}}}))
    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
        tts = DoubaoPCM(client, speech_config(env))
        worker = PipelineWorker(Pipeline([llm, Meter(state), tts, Sink(state)]),
            params=PipelineParams(audio_out_sample_rate=24000, enable_metrics=True))
        @worker.event_handler('on_pipeline_error')
        async def pipeline_error(worker, frame):
            state['turn'].errors.append(type(frame).__name__)
            state['turn'].done.set()
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())
        try:
            for index, text in enumerate(CASES[:args.turns]):
                asr_metrics=None
                if index < args.audio_turns:
                    pcm=bytearray()
                    async for chunk in pcm_stream(client,speech_config(env),text,rate=16000):pcm.extend(chunk)
                    text,asr_metrics=await recognize(bytes(pcm),env)
                t = state['turn'] = Turn(text)
                history.append({'role':'user','content':text})
                await worker.queue_frame(LLMContextFrame(LLMContext(list(history))))
                await asyncio.wait_for(t.done.wait(), 45)
                result = record(t)
                if asr_metrics:
                    result['asr']=asr_metrics
                    result['speech_end_to_pcm_ms']=asr_metrics['speech_end_to_transcript_ms']+result['first_pcm_ms'] if result['first_pcm_ms'] is not None else None
                report['turns'].append(result)
                if not t.pcm or not t.text or t.errors:
                    raise RuntimeError('Real Pipecat model-to-audio pipeline failed')
                history.append({'role':'assistant','content':t.text})
                (directory/f'turn-{index+1}.pcm').write_bytes(t.pcm)
                print(json.dumps({'turn':index+1,**{k:v for k,v in result.items() if k not in {'input','answer'}}}),flush=True)
            delays = [t['first_pcm_ms'] for t in report['turns']]
            report['transcript_to_pcm'] = {'median_ms':round(statistics.median(delays)),
                'p95_ms':sorted(delays)[math.ceil(.95*len(delays))-1]}
            report['pipeline_passed'] = all(t['pcm_bytes'] and not t['errors'] for t in report['turns'])
            # A long reply must start synthesis without waiting for the whole model.
            t = state['turn'] = Turn('讲一个有六句话的小故事，每句话另起一行，故事开头直接进入情节。')
            await worker.queue_frame(LLMContextFrame(LLMContext([{'role':'system','content':PROMPT},{'role':'user','content':t.user}])))
            await asyncio.wait_for(t.done.wait(),45)
            report['streaming_probe'] = record(t)
            # Interrupt a real generation after first audio; no late PCM is allowed.
            t = state['turn'] = Turn('请讲一个很长的故事，至少十句话。')
            await worker.queue_frame(LLMContextFrame(LLMContext([{'role':'system','content':PROMPT},{'role':'user','content':t.user}])))
            await asyncio.wait_for(t.audio_ready.wait(),45)
            interrupted = time.monotonic()
            await worker.queue_frame(InterruptionFrame())
            await asyncio.sleep(.5)
            report['interruption'] = {'pcm_after_300ms':sum(at>interrupted+.3 for at in t.audio_times),
                                      'server_frame_only':True,'playback_stop_not_tested':True}
            delays = [t['first_pcm_ms'] for t in report['turns']]
            report['transcript_to_pcm'] = {'median_ms':round(statistics.median(delays)),
                'p95_ms':sorted(delays)[math.ceil(.95*len(delays))-1]}
            report['pipeline_passed'] = all(t['pcm_bytes'] and not t['errors'] for t in report['turns'])
            report['streaming_passed'] = report['streaming_probe']['audio_before_model_end']
            report['interruption_passed'] = report['interruption']['pcm_after_300ms']==0
        except Exception as exc:
            report['error_type'] = type(exc).__name__
            report.setdefault('pipeline_passed', False)
            report['failed_stage_turn'] = record(state['turn'])
        finally:
            await worker.cancel()
            await asyncio.gather(running, return_exceptions=True)
            await llm._client.close()
    # A receipt, text-only response or server frame is not audible phone acceptance.
    proof_root=ROOT/'.local-data/pipecat-proof'
    def evidence(name):
        path=proof_root/name
        return json.loads(path.read_text()) if path.exists() else {}
    report['gate']=evaluate(report,evidence('media.json'),evidence('turns.json'))
    report['integration_gate_passed']=report['gate']['integration_gate_passed']
    report['remaining_gates']=report['gate']['remaining_gates']
    (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report.get('pipeline_passed') else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--audio-turns',type=int,choices=range(0,11),default=2)
    parser.add_argument('--model');parser.add_argument('--turns',type=int,choices=range(1,11),default=10)
    args=parser.parse_args()
    if not args.live:parser.error('--live required; uses configured real model and speech APIs with synthetic dialogue')
    raise SystemExit(asyncio.run(run(args)))
