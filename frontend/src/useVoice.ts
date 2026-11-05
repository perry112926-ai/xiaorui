import {useEffect,useRef,useState} from 'react';
import {feedbackClip,feedbackKind,isGreeting,isHolding,warmFeedback} from './callFeedback';
type VoiceMetric={stage:'tts_request_start'|'stream_ready'|'playback_started'|'playback_ended'|'feedback_load_start'|'feedback_ready'|'feedback_playback_started';sentence:number;elapsedMs:number;durationMs?:number;sinceUserSpeechMs?:number};
type Status={asr_configured:boolean;tts_configured:boolean};
// 20 ms level events for barge-in; official ASR receives 200 ms PCM16 packets.
const processor=`class PCM extends AudioWorkletProcessor {
 constructor(){super();this.phase=0;this.sum=0;this.count=0;this.buffer=[];this.power=0;this.n=0;this.port.onmessage=e=>{if(e.data?.type==='flush'){if(this.buffer.length){const b=new ArrayBuffer(this.buffer.length*2),d=new DataView(b);this.buffer.forEach((v,i)=>d.setInt16(i*2,v,true));this.port.postMessage(b,[b]);this.buffer=[];}this.port.postMessage({type:'flushed',id:e.data.id});}};}
 process(inputs){const a=inputs[0]?.[0];if(!a)return true;for(const x of a){this.power+=x*x;this.n++;if(this.n>=sampleRate*.02){this.port.postMessage({level:Math.sqrt(this.power/this.n)});this.power=0;this.n=0;}this.sum+=x;this.count++;this.phase+=16000;if(this.phase>=sampleRate){this.phase-=sampleRate;const v=Math.max(-1,Math.min(1,this.sum/this.count));this.buffer.push(Math.round(v*(v<0?32768:32767)));this.sum=0;this.count=0;if(this.buffer.length===3200){const b=new ArrayBuffer(6400),d=new DataView(b);this.buffer.forEach((v,i)=>d.setInt16(i*2,v,true));this.port.postMessage(b,[b]);this.buffer=[];}}}return true;}
}registerProcessor('xiaorui-pcm',PCM);`;
// Completed sentences can finish sooner; hesitation and confirmations retain room.
export function silenceDelay(text:string){
 const value=text.trim();
 if(/(?:然后|还有|那个|这个|就是|我想|我想想|让我想想|等一下|稍等|但是|或者|嗯|呃)[，,、。\s]*$/.test(value))return 4000;
 if(!value||/确认(?:叫车|下单|取消)/.test(value))return 1800;
 return /[。！？!?]$/.test(value)?900:1200;
}
type Turn={confirmationEchoRisk?:boolean;socket:WebSocket;ready:boolean;closing:boolean;pending:ArrayBuffer[];lastText:string;timeout?:ReturnType<typeof setTimeout>;limit?:ReturnType<typeof setTimeout>};
export function useVoice(onFinal:(text:string)=>void,onError:(text:string)=>void,onSpeechStart:()=>void=()=>{}){
 const [status,setStatus]=useState<Status>();const [phase,setPhase]=useState<'idle'|'connecting'|'listening'|'finishing'>('idle');const [transcript,setTranscript]=useState('');const [speaking,setSpeaking]=useState(false);const [loadingSpeech,setLoadingSpeech]=useState(false);const [inCall,setInCall]=useState(false);const [recording,setRecording]=useState(false);const captureMode=useRef<'call'|'message'>('call');const finishRequested=useRef(false);const flushRequest=useRef<{id:number;target:Turn}|undefined>(undefined),flushSequence=useRef(0);
 const handlers=useRef({onFinal,onError,onSpeechStart});handlers.current={onFinal,onError,onSpeechStart};
 const active=useRef(false),mounted=useRef(true),generation=useRef(0),media=useRef<MediaStream|undefined>(undefined),ctx=useRef<AudioContext|undefined>(undefined),node=useRef<AudioWorkletNode|undefined>(undefined),turn=useRef<Turn|undefined>(undefined);
 const pre=useRef<ArrayBuffer[]>([]),next=useRef<ArrayBuffer[]>([]),talking=useRef(false),lastLoud=useRef(0),loudFrames=useRef(0),ticker=useRef<ReturnType<typeof setInterval>|undefined>(undefined);
 const speechMetrics=useRef<VoiceMetric[]>([]);
 const confirmationAudioPlaying=useRef(false),nextConfirmationEchoRisk=useRef(false);
 const player=useRef<HTMLAudioElement|undefined>(undefined),audioUrl=useRef(''),speechAbort=useRef<AbortController|undefined>(undefined),speechGeneration=useRef(0);
 function stopSpeech(){confirmationAudioPlaying.current=false;speechGeneration.current++;speechAbort.current?.abort();speechAbort.current=undefined;const p=player.current;if(p){p.pause();p.removeAttribute('src');p.load();p.dispatchEvent(new Event('ended'));}player.current=undefined;if(audioUrl.current){URL.revokeObjectURL(audioUrl.current);audioUrl.current='';}if(mounted.current){setSpeaking(false);setLoadingSpeech(false);}}
 function dispose(t:Turn){clearTimeout(t.timeout);clearTimeout(t.limit);t.socket.onclose=null;t.socket.onerror=null;t.socket.onmessage=null;t.socket.close();}
 function releaseMicrophone(){const worklet=node.current;node.current=undefined;if(worklet){worklet.port.onmessage=null;worklet.disconnect();}media.current?.getTracks().forEach(track=>track.stop());media.current=undefined;void ctx.current?.close().catch(()=>{});ctx.current=undefined;}
 function endCall(){nextConfirmationEchoRisk.current=false;flushRequest.current=undefined;finishRequested.current=false;active.current=false;generation.current++;clearInterval(ticker.current);const t=turn.current;turn.current=undefined;if(t)dispose(t);releaseMicrophone();pre.current=[];next.current=[];talking.current=false;stopSpeech();if(mounted.current){setInCall(false);setRecording(false);setPhase('idle');setTranscript('');}}
 function fail(message:string){endCall();handlers.current.onError(message);}
 function complete(t:Turn,text:string){if(turn.current!==t)return;if(t.confirmationEchoRisk&&/^(?:确认下单|确认叫车|确认取消|确认新增地址)[。！!，,\s]*$/.test(text.trim())){if(captureMode.current==='message')endCall();else{dispose(t);turn.current=undefined;next.current=[];talking.current=false;setTranscript('');setPhase('listening');}handlers.current.onError('为避免播报回声误确认，请等播报结束后再确认，或点击方案卡片。');return;}if(captureMode.current==='message'){endCall();if(text.trim())handlers.current.onFinal(text.trim());else handlers.current.onError('没有听清楚，请再说一次。');return;}dispose(t);turn.current=undefined;setTranscript('');setPhase('listening');if(text.trim()){if(isGreeting(text)||isHolding(text)){void feedback(text);}else handlers.current.onFinal(text.trim());}const pending=next.current;next.current=[];if(active.current&&pending.length)openTurn(pending);}
 function finishTurn(){const t=turn.current;if(!t||t.closing||!t.ready)return;t.closing=true;finishRequested.current=false;setPhase('finishing');t.socket.send(JSON.stringify({type:'finish'}));t.timeout=setTimeout(()=>fail('语音识别等待超时，通话已结束，您可以继续打字。'),18000);}
 function openTurn(frames:ArrayBuffer[]){if(!active.current||turn.current)return;const socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/api/voice/asr`);const t:Turn={socket,ready:false,closing:false,pending:frames,lastText:'',confirmationEchoRisk:nextConfirmationEchoRisk.current};nextConfirmationEchoRisk.current=false;turn.current=t;t.timeout=setTimeout(()=>fail('语音连接超时，请重新接通。'),20000);
 socket.onopen=()=>{};
 socket.onmessage=e=>{if(turn.current!==t||!active.current)return;try{const msg=JSON.parse(e.data);if(msg.type==='ready'){clearTimeout(t.timeout);t.ready=true;setPhase('listening');for(const b of t.pending)socket.send(b);t.pending=[];t.limit=setTimeout(()=>{if(turn.current!==t)return;if(captureMode.current==='message'&&node.current)requestFlush(t);else finishTurn();},55000);if(finishRequested.current)finishTurn();}else if(msg.type==='partial'){t.lastText=msg.text||'';setTranscript(t.lastText);}else if(msg.type==='final'){if(!t.closing){fail('语音服务提前结束，未发送这段录音，请重新说或打字。');return;}complete(t,msg.text||t.lastText);}else if(msg.type==='error'){fail(msg.message||'语音服务暂时不可用。');}}catch{fail('语音服务返回异常，通话已结束。');}};
 socket.onerror=()=>{if(turn.current===t)fail('语音连接失败，请检查网络后重新接通。');};socket.onclose=()=>{if(turn.current===t)fail('语音连接已断开，您可以继续打字。');};
 }
 async function startCapture(mode:'call'|'message'){if(mode==='call')void warmFeedback().catch(()=>{});if(active.current){endCall();}captureMode.current=mode;finishRequested.current=false;active.current=true;stopSpeech();const id=++generation.current;setPhase('connecting');setInCall(mode==='call');setRecording(mode==='message');setTranscript('');
 try{const r=await fetch('/api/voice/status');if(!r.ok)throw Error('语音服务未连接。');const s:Status=await r.json();if(id!==generation.current)return;setStatus(s);if(!s.asr_configured||!s.tts_configured)throw Error('请先配置豆包语音服务。');if(!navigator.mediaDevices?.getUserMedia)throw Error('当前浏览器不支持通话，请在本机浏览器打开小瑞。');
 const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});if(id!==generation.current){stream.getTracks().forEach(t=>t.stop());return;}media.current=stream;const context=new AudioContext();ctx.current=context;await context.resume();const url=URL.createObjectURL(new Blob([processor],{type:'application/javascript'}));try{await context.audioWorklet.addModule(url);}finally{URL.revokeObjectURL(url);}if(id!==generation.current)return;
 const worklet=new AudioWorkletNode(context,'xiaorui-pcm');node.current=worklet;const source=context.createMediaStreamSource(stream),mute=context.createGain();mute.gain.value=0;source.connect(worklet);worklet.connect(mute);mute.connect(context.destination);
 worklet.port.onmessage=e=>{if(!active.current||id!==generation.current)return;if(e.data?.type==='flushed'){const request=flushRequest.current;if(!request||request.id!==e.data.id)return;flushRequest.current=undefined;if(turn.current!==request.target||request.target.closing)return;finishRequested.current=true;finishTurn();if(captureMode.current==='message'){releaseMicrophone();setRecording(false);}return;}if(!(e.data instanceof ArrayBuffer)){if(e.data.level>.018){lastLoud.current=Date.now();loudFrames.current++;if(loudFrames.current>=6&&!talking.current){talking.current=true;if(confirmationAudioPlaying.current){if(turn.current)turn.current.confirmationEchoRisk=true;else nextConfirmationEchoRisk.current=true;}stopSpeech();handlers.current.onSpeechStart();}}else loudFrames.current=0;return;}
 const b=e.data as ArrayBuffer;const t=turn.current;if(t&&!t.closing){if(t.ready){if(t.socket.bufferedAmount>256000){fail('网络暂时跟不上通话，请重新接通。');return;}t.socket.send(b);}else{t.pending.push(b);if(t.pending.length>40)fail('语音连接过慢，请重新接通。');}}else if(t?.closing){if(captureMode.current==='call'&&talking.current){next.current.push(b);if(next.current.length>40)fail('识别等待过久，请重新接通。');}}else{pre.current.push(b);if(pre.current.length>3)pre.current.shift();if(talking.current){const frames=pre.current;pre.current=[];openTurn(frames);}}};
 if(mode==='message'){openTurn([]);if(finishRequested.current&&turn.current)requestFlush(turn.current);}else ticker.current=setInterval(()=>{const quiet=Date.now()-lastLoud.current;if(quiet>silenceDelay(turn.current?.lastText||'')){talking.current=false;if(turn.current?.ready&&!turn.current.closing)finishTurn();}},100);setPhase(finishRequested.current?'finishing':'listening');return true;
 }catch(e){if(id!==generation.current)return;fail(e instanceof DOMException&&e.name==='NotAllowedError'?'麦克风未获允许，您仍可以打字。':e instanceof Error?e.message:'无法接通语音。');return false;}}
 function startCall(){if(active.current&&captureMode.current==='call'){endCall();return Promise.resolve();}return startCapture('call');}
 function startRecording(){return startCapture('message');}
 function requestFlush(target:Turn){const request={id:++flushSequence.current,target};flushRequest.current=request;node.current?.port.postMessage({type:'flush',id:request.id});}
 function stopRecording(){if(!active.current||captureMode.current!=='message'||turn.current?.closing)return;setPhase('finishing');if(node.current&&turn.current){requestFlush(turn.current);}else{finishRequested.current=true;finishTurn();}}
 function finishCurrent(){const t=turn.current;if(!t||t.closing)return;talking.current=false;loudFrames.current=0;next.current=[];if(node.current){requestFlush(t);}else{finishRequested.current=true;finishTurn();}}
 async function speak(text:string){
 stopSpeech();const id=speechGeneration.current;const controller=new AbortController();speechAbort.current=controller;
 setLoadingSpeech(true);const started=Date.now();speechMetrics.current=[];
 const metric=(stage:VoiceMetric['stage'])=>{if(id===speechGeneration.current&&!controller.signal.aborted)speechMetrics.current.push({stage,sentence:0,elapsedMs:Date.now()-started});};
 metric('tts_request_start');
 try{
  const r=await fetch('/api/voice/tts/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text}),signal:controller.signal});
  if(!r.ok)throw Error('语音播报暂时不可用，文字消息已保留。');
  const data=await r.json();
  if(controller.signal.aborted||id!==speechGeneration.current)return;
  if(typeof data.url!=='string'||!/^\/api\/voice\/tts\/stream\/[A-Za-z0-9_-]+$/.test(data.url))throw Error('语音播放地址无效，请重试。');
  metric('stream_ready');const p=new Audio(data.url);player.current=p;p.preload='auto';
  await new Promise<void>((resolve,reject)=>{
   p.onplaying=()=>{metric('playback_started');if(id===speechGeneration.current){confirmationAudioPlaying.current=/确认(?:下单|叫车|取消|新增地址)/.test(text);setLoadingSpeech(false);setSpeaking(true);}};
   p.onended=()=>{if(id===speechGeneration.current)confirmationAudioPlaying.current=false;metric('playback_ended');resolve();};p.onerror=()=>reject(Error('语音播放未完成，请点击消息重新播报。'));
   void p.play().catch(reject);
  });
  if(id===speechGeneration.current){p.removeAttribute('src');p.load();player.current=undefined;setSpeaking(false);setLoadingSpeech(false);}
 }catch(e){if(controller.signal.aborted||id!==speechGeneration.current)return;stopSpeech();handlers.current.onError(e instanceof DOMException&&e.name==='NotAllowedError'?'浏览器尚未允许播放，请点击消息下方“听小瑞说”。':e instanceof Error?e.message:'语音播放失败。');}
 }

 async function feedback(text:string){
  // Local clips are for explicit contact/hold phrases, never generic turn fillers.
  if(!isGreeting(text)&&!isHolding(text))return;
  stopSpeech();const id=speechGeneration.current;const controller=new AbortController();speechAbort.current=controller;
  const started=Date.now();speechMetrics.current=[{stage:'feedback_load_start',sentence:0,elapsedMs:0}];
  setLoadingSpeech(true);
  try{
   const clip=await feedbackClip(feedbackKind(text));
   if(controller.signal.aborted||id!==speechGeneration.current)return;
   speechMetrics.current.push({stage:'feedback_ready',sentence:0,elapsedMs:Date.now()-started});
   audioUrl.current=URL.createObjectURL(clip);const p=new Audio(audioUrl.current);player.current=p;
   await new Promise<void>((resolve,reject)=>{
    p.onplaying=()=>{if(id===speechGeneration.current){speechMetrics.current.push({stage:'feedback_playback_started',sentence:0,elapsedMs:Date.now()-started});setLoadingSpeech(false);setSpeaking(true);}};
    p.onended=()=>resolve();p.onerror=()=>reject(Error('通话短回应播放失败，请刷新页面后重试。'));
    void p.play().catch(reject);
   });
   if(id===speechGeneration.current){player.current=undefined;URL.revokeObjectURL(audioUrl.current);audioUrl.current='';setSpeaking(false);setLoadingSpeech(false);}
  }catch(e){if(controller.signal.aborted||id!==speechGeneration.current)return;stopSpeech();handlers.current.onError(e instanceof Error?e.message:'通话短回应播放失败。');}
 }

 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;endCall();};},[]);
 return{status,phase,transcript,speaking,loadingSpeech,inCall,recording,startRecording,stopRecording,cancelRecording:endCall,start:startCall,startCall,endCall,finish:finishCurrent,cancel:endCall,speak,feedback,stopSpeech,speechMetrics};
}
