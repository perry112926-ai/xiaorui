const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
function harness(){
 const state=[],cleanups=[],intervals=[],sockets=[],players=[],requests=[];let index=0,now=10000,stopped=0,worklet;
 const hooks={useRef:v=>({current:v}),useState:v=>{const i=index++;state[i]=v;return[v,x=>{state[i]=typeof x==='function'?x(state[i]):x}];},useEffect:f=>cleanups.push(f())};
 class Socket{static OPEN=1;constructor(){this.readyState=1;this.bufferedAmount=0;this.sent=[];sockets.push(this);}send(v){this.sent.push(v);}close(){this.readyState=3;}receive(data){this.onmessage?.({data:JSON.stringify(data)});}}
 class Worklet{constructor(){this.port={postMessage:message=>{if(message?.type==='flush')this.port.onmessage?.({data:{type:'flushed',id:message.id}});}};worklet=this;}connect(){}disconnect(){}}
 class Context{constructor(){this.audioWorklet={addModule:async()=>{}};this.destination={};}async resume(){}async close(){}createMediaStreamSource(){return{connect(){}};}createGain(){return{gain:{value:0},connect(){}};}}
 class Audio{constructor(url){this.url=url;players.push(this);}play(){this.onplaying?.();return Promise.resolve();}pause(){this.paused=true;}removeAttribute(name){if(name==='src')this.detached=true;}load(){}dispatchEvent(e){if(e.type==='ended')this.onended?.();}}
 const module={exports:{}},feedbackModule={exports:{}};const context={module,exports:module.exports,require:n=>n==='react'?hooks:n==='./callFeedback'?feedbackModule.exports:require(n),
  fetch:async (url,options)=>{requests.push({url,options});return{ok:true,json:async()=>url.endsWith('/prepare')?{url:'/api/voice/tts/stream/test-ticket'}:{asr_configured:true,tts_configured:true},blob:async()=>{if(url.startsWith('/assets/voice-feedback/'))return new Blob(['synthetic-feedback']);throw Error('Must not wait for a full audio blob');}};},
  navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[{stop(){stopped++;}}]})}},
  WebSocket:Socket,AudioWorkletNode:Worklet,AudioContext:Context,Audio,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},
  location:{protocol:'http:',host:'localhost:8000'},Blob,AbortController,DOMException,Event,ArrayBuffer,Date:{now:()=>now},
  setInterval:f=>{intervals.push(f);return 1;},clearInterval(){},setTimeout:()=>1,clearTimeout(){},console};
 const code=ts.transpileModule(fs.readFileSync(require.resolve('../src/useVoice.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 const feedbackCode=ts.transpileModule(fs.readFileSync(require.resolve('../src/callFeedback.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 vm.runInNewContext(feedbackCode,{...context,module:feedbackModule,exports:feedbackModule.exports});
 vm.runInNewContext(code,context);
 const received=[],errors=[];let interruptions=0;const voice=module.exports.useVoice(t=>received.push(t),e=>errors.push(e),()=>interruptions++);
 return{voice,feedbackKind:feedbackModule.exports.feedbackKind,sockets,players,requests,received,errors,state,silenceDelay:module.exports.silenceDelay,get stopped(){return stopped;},get interruptions(){return interruptions;},
  loud(){for(let i=0;i<6;i++)worklet.port.onmessage({data:{level:.06}});},audio(){worklet.port.onmessage({data:new ArrayBuffer(6400)});},
  silence(ms=2000){now+=ms;worklet.port.onmessage({data:{level:0}});intervals.forEach(f=>f());},flush:async()=>{for(let i=0;i<8;i++)await Promise.resolve();},cleanup:()=>cleanups.forEach(f=>f?.())};
}
test('one call accepts multiple turns, with no microphone restart and exact final deduplication',async()=>{
 const h=harness();await h.voice.startCall();h.loud();h.audio();assert.equal(h.sockets.length,1);
 h.sockets[0].receive({type:'ready'});h.sockets[0].receive({type:'partial',text:'想吃午饭'});h.silence();
 assert.ok(h.sockets[0].sent.some(v=>typeof v==='string'&&v.includes('finish')));
 h.sockets[0].receive({type:'final',text:'想吃午饭'});assert.deepEqual(h.received,['想吃午饭']);assert.equal(h.stopped,0);
 h.loud();h.audio();h.sockets[1].receive({type:'ready'});h.silence();h.sockets[1].receive({type:'final',text:'三十元以内'});
 assert.deepEqual(h.received,['想吃午饭','三十元以内']);h.voice.endCall();assert.equal(h.stopped,1);assert.deepEqual(h.errors,[]);h.cleanup();
});
test('speech playback keeps the microphone active; user speech interrupts audio',async()=>{
 const h=harness();await h.voice.startCall();const playback=h.voice.speak('您好。');await h.flush();assert.equal(h.players.length,1);assert.equal(h.stopped,0);
 h.loud();await playback;assert.equal(h.players[0].paused,true);assert.equal(h.interruptions,1);assert.equal(h.stopped,0);h.cleanup();assert.equal(h.stopped,1);
});
test('hangup during pending ASR closes socket and does not send unfinished transcript',async()=>{
 const h=harness();await h.voice.startCall();h.loud();h.audio();h.sockets[0].receive({type:'ready'});h.sockets[0].receive({type:'partial',text:'尚未说完'});
 h.voice.endCall();h.sockets[0].receive({type:'final',text:'不能再提交'});assert.deepEqual(h.received,[]);assert.equal(h.sockets[0].readyState,3);assert.equal(h.stopped,1);h.cleanup();
});

test('single voice message waits for stop, submits once, then releases microphone',async()=>{
 const h=harness();await h.voice.startRecording();assert.equal(h.sockets.length,1);h.sockets[0].receive({type:'ready'});h.audio();h.silence();
 assert.equal(h.sockets[0].sent.some(v=>typeof v==='string'&&v.includes('finish')),false);
 h.voice.stopRecording();assert.equal(h.stopped,1);assert.deepEqual(h.received,[]);assert.equal(h.sockets[0].sent.some(v=>typeof v==='string'&&v.includes('finish')),true);
 h.sockets[0].receive({type:'final',text:'一条语音消息'});h.sockets[0].receive({type:'final',text:'不能重复'});assert.deepEqual(h.received,['一条语音消息']);assert.equal(h.stopped,1);assert.equal(h.sockets.length,1);h.cleanup();
});
test('switching away cancels a voice message without sending partial text',async()=>{
 const h=harness();await h.voice.startRecording();h.sockets[0].receive({type:'ready'});h.sockets[0].receive({type:'partial',text:'不要发送'});h.voice.cancelRecording();
 assert.deepEqual(h.received,[]);assert.equal(h.stopped,1);h.cleanup();
});

test('partial hello gets a local reply before ASR final, without duplicate reply or model work',async()=>{
 const h=harness();await h.voice.startCall();await h.flush();h.loud();h.audio();h.sockets[0].receive({type:'ready'});
 h.sockets[0].receive({type:'partial',text:'喂。'});h.silence(300);await h.flush();
 assert.equal(h.players.length,1);assert.equal(h.players[0].url,'blob:test');assert.deepEqual(h.received,[]);
 assert.equal(h.requests.filter(r=>r.url==='/api/voice/tts/prepare').length,0);
 h.silence(1000);h.sockets[0].receive({type:'final',text:'喂。'});await h.flush();
 assert.equal(h.players.length,1);assert.deepEqual(h.received,[]);
 h.loud();assert.equal(h.players[0].paused,true);h.cleanup();
});

test('caller receives feedback during a short pause even before cloud ASR is ready',async()=>{
 const h=harness();await h.voice.startCall();await h.flush();h.loud();h.audio();
 h.silence(300);await h.flush();
 assert.equal(h.players.length,1);assert.deepEqual(h.received,[]);
 assert.equal(h.requests.filter(r=>r.url==='/api/voice/tts/prepare').length,0);
 h.loud();assert.equal(h.players[0].paused,true);h.cleanup();
});

test('cached task acknowledgements are immediate and interruptible without cloud synthesis',async()=>{
 const h=harness();const first=h.voice.feedback('帮我查一下天气');await h.flush();
 assert.equal(h.players.length,1);assert.equal(h.requests[0].url,'/assets/voice-feedback/checking.wav');
 h.voice.stopSpeech();await first;
 const second=h.voice.feedback('帮我找附近的店');await h.flush();
 assert.equal(h.players.length,2);assert.equal(h.requests.length,1);
 assert.equal(h.feedbackKind('确认叫车'),'review');
 assert.equal(h.feedbackKind('等一下'),'wait');
 h.voice.stopSpeech();await second;h.cleanup();
});

test('hanging up during feedback loading suppresses late audio',async()=>{
 const h=harness();const pending=h.voice.feedback('喂');h.voice.endCall();await h.flush();await pending;
 assert.equal(h.players.length,0);assert.deepEqual(h.errors,[]);h.cleanup();
});

test('completed speech submits sooner while hesitation and confirmation keep a longer pause',async()=>{
 const h=harness();await h.voice.startCall();h.loud();h.audio();h.sockets[0].receive({type:'ready'});
 h.sockets[0].receive({type:'partial',text:'陪我聊聊吧。'});h.silence(950);
 assert.ok(h.sockets[0].sent.some(x=>typeof x==='string'&&x.includes('finish')));
 assert.equal(h.silenceDelay('然后，'),4000);assert.equal(h.silenceDelay('确认叫车。'),1800);assert.equal(h.silenceDelay(''),1800);
 h.cleanup();
});

test('a whole reply uses one progressive audio stream and interruption detaches its network source',async()=>{
 const h=harness();const playback=h.voice.speak('好呀，我陪您。想聊些什么呢？');await h.flush();
 assert.equal(h.players.length,1);assert.equal(h.players[0].url,'/api/voice/tts/stream/test-ticket');
 assert.equal(h.requests.filter(x=>x.url.endsWith('/prepare')).length,1);
 h.voice.stopSpeech();await playback;assert.equal(h.players[0].detached,true);assert.deepEqual(h.errors,[]);h.cleanup();
});

// Selected capture fixes must coexist with progressive playback.
test('ASR final before the user finishes cannot submit a partial message',async()=>{
 for(const mode of ['startRecording','startCall']){const h=harness();await h.voice[mode]();if(mode==='startCall'){h.loud();h.audio();}
 h.sockets[0].receive({type:'ready'});h.sockets[0].receive({type:'final',text:'还没说完'});
 assert.deepEqual(h.received,[]);assert.equal(h.stopped,1);assert.match(h.errors[0],/提前结束/);h.cleanup();}
});
test('stop before ASR readiness releases microphone and later submits only after ready',async()=>{
 const h=harness();await h.voice.startRecording();h.audio();h.voice.stopRecording();assert.equal(h.stopped,1);assert.deepEqual(h.received,[]);
 h.sockets[0].receive({type:'ready'});assert.equal(h.sockets[0].sent.filter(v=>typeof v==='string'&&v.includes('finish')).length,1);
 h.sockets[0].receive({type:'final',text:'连接前已经说完'});assert.deepEqual(h.received,['连接前已经说完']);h.cleanup();
});
test('cancel during final recognition drops late text after microphone release',async()=>{
 const h=harness();await h.voice.startRecording();h.sockets[0].receive({type:'ready'});h.voice.stopRecording();assert.equal(h.stopped,1);
 h.voice.cancelRecording();h.sockets[0].receive({type:'final',text:'不要再发送'});assert.deepEqual(h.received,[]);assert.equal(h.stopped,1);h.cleanup();
});
test('manual call finish is idempotent and does not close the following turn',async()=>{
 const h=harness();await h.voice.startCall();h.loud();h.audio();h.sockets[0].receive({type:'ready'});h.voice.finish();h.voice.finish();
 assert.equal(h.sockets[0].sent.filter(v=>typeof v==='string'&&v.includes('finish')).length,1);
 h.sockets[0].receive({type:'final',text:'第一轮'});h.silence();h.loud();h.audio();h.sockets[1].receive({type:'ready'});
 assert.equal(h.sockets[1].sent.some(v=>typeof v==='string'&&v.includes('finish')),false);h.cleanup();
});
test('streaming speech exposes timing spans without recording speech text',async()=>{
 const h=harness();const playback=h.voice.speak('请不要记录这句话。');await h.flush();h.players[0].dispatchEvent(new Event('ended'));await playback;
 assert.deepEqual(Array.from(h.voice.speechMetrics.current,m=>m.stage),['tts_request_start','stream_ready','playback_started','playback_ended']);
 assert.doesNotMatch(JSON.stringify(h.voice.speechMetrics.current),/请不要记录/);h.cleanup();
});

test('elderly caller explicitly hesitates for 2.5 seconds: do not prematurely submit the unfinished sentence',async()=>{
 const h=harness();await h.voice.startCall();h.loud();h.audio();h.sockets[0].receive({type:'ready'});
 h.sockets[0].receive({type:'partial',text:'我想想，那个'});h.silence(2500);
 assert.equal(h.sockets[0].sent.some(v=>typeof v==='string'&&v.includes('finish')),false);
 h.silence(1600);assert.equal(h.sockets[0].sent.filter(v=>typeof v==='string'&&v.includes('finish')).length,1);h.cleanup();
});

test('confirmation echoed during the assistants confirmation speech is not submitted; fresh confirmation still works',async()=>{
 const h=harness();await h.voice.startCall();
 const speaking=h.voice.speak('请核对套餐和总价，确定后说确认下单。');await h.flush();
 h.loud();h.audio();await speaking;
 h.sockets[0].receive({type:'ready'});h.sockets[0].receive({type:'partial',text:'确认下单'});h.silence(2000);
 h.sockets[0].receive({type:'final',text:'确认下单。'});
 assert.deepEqual(h.received,[]);assert.ok(h.errors.some(e=>e.includes('播报回声')));assert.equal(h.stopped,0);
 h.loud();h.audio();h.sockets[1].receive({type:'ready'});h.sockets[1].receive({type:'partial',text:'确认下单'});h.silence(2000);
 h.sockets[1].receive({type:'final',text:'确认下单。'});assert.deepEqual(h.received,['确认下单。']);h.cleanup();
});
