const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const React=require('react');
const code=ts.transpileModule(fs.readFileSync(require.resolve('../src/main.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
const companionModule={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(require.resolve('../src/Companion.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,{module:companionModule,exports:companionModule.exports,require:name=>name==='./CardHeading'?require('./load-card-heading.cjs'):name.endsWith('.css')?{}:name==='./money'?require('./load-money.cjs'):require(name)});
function harness(options={}){
 const slots=[];let index=0,callbacks,source;
 const spoken=[],feedback=[];const requests=[];let cancellations=0;
 const voice={phase:'listening',inCall:true,recording:false,transcript:'',speaking:false,loadingSpeech:false,speak:async text=>spoken.push(text),feedback:async text=>feedback.push(text),stopSpeech(){},cancel(){},cancelRecording(){cancellations++;voice.phase='idle';voice.recording=false;},startCall:async()=>{voice.inCall=true;voice.phase='listening';return true;},endCall(){voice.inCall=false;voice.phase='idle';}};
 const hooks={...React,useReducer(reducer,initial){const [state,setState]=hooks.useState(initial);return[state,action=>setState(old=>reducer(old,action))];},useState(initial){const i=index++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return[slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value;}];},useRef(value){const i=index++;if(!(i in slots))slots[i]={current:value};return slots[i];},useEffect(effect,deps){const i=index++;const old=slots[i];if(!old||!deps||deps.some((value,n)=>value!==old[n])){slots[i]=deps;effect();}}};
 class EventSource{constructor(){source=this;}close(){}}
 const module={exports:{}};
 const fetch=async (url,requestOptions)=>{requests.push({url,options:requestOptions});if(options.request){const result=await options.request(url,requestOptions);if(result)return result;}return{ok:true,headers:{get:()=> 'application/json'},json:async()=>url==='/api/health'?{mcd_configured:true,agent_configured:true}:url==='/api/contact/state'?{events:options.replay||[],cursor:0,pending:0}:url==='/api/chat/history'?{messages:[]}:url==='/api/actions'?{actions:[]}:url==='/api/contact/calls'?{id:'call-test-1',started_at:Date.now()/1000}:url.endsWith('/end')?{id:'call-test-1',started_at:Date.now()/1000-65,duration_seconds:65}: {accepted:true}};};
 require('./load-frontend.cjs')(code,{module,exports:module.exports,require:name=>name==='./CardHeading'?require('./load-card-heading.cjs'):name==='react'?hooks:name==='react-dom/client'?{createRoot:()=>({render(){}})}:name==='./useVoice'?{useVoice:(onFinal,onError,onSpeechStart)=>{callbacks={onFinal,onError,onSpeechStart};return voice;}}:name==='./Companion'?{Companion(){},CompanionAvatar(){},companionMood:companionModule.exports.companionMood}:name==='./SettingsDialog'?{SettingsDialog(){},useCompanionSettings:()=>({settings:{name:'小瑞',avatar:'portrait'},updateSettings(){}})}:name==='./CallBar'?{CallBar(){},callDuration:s=>String(s)}:name==='./ProfileCard'?{ProfileCard(){}}:name==='./location'?{locate:async()=>10}:name==='./payment'?{officialPaymentUrl:()=>undefined,openOfficialPayment:()=>false}:name==='./ActionCard'||name==='./ChoiceCards'?{}:name.endsWith('.css')?{}:name==='./money'?require('./load-money.cjs'):require(name),document:{getElementById:()=>({}),addEventListener(){},removeEventListener(){}},EventSource,fetch,crypto:require('node:crypto'),setInterval:()=>1,clearInterval(){},console});
 const render=()=>{index=0;return module.exports.App();};
 const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
 return{render,flush,spoken,feedback,voice,requests,get cancellations(){return cancellations;},get callbacks(){return callbacks;},emit:event=>source.onmessage({data:JSON.stringify(event)})};
}
function all(node,predicate){if(!node||typeof node!=='object')return[];if(typeof node.type==='function'&&['AppView','Conversation','Composer','MessageItem','StoreCards','MealCards','Mic','Keyboard','Photo','Phone'].includes(node.type.name))return[predicate(node)?node:null,...all(node.type(node.props),predicate)].filter(Boolean);return[predicate(node)?node:null,...React.Children.toArray(node.props?.children).flatMap(child=>all(child,predicate))].filter(Boolean);}
const reply=(id,text,events=[])=>({type:'completed',message_id:id,response:{text,speech_text:text,events}});

const poses=tree=>all(tree,node=>node.type?.name==='Companion').map(node=>node.props.mood);
test('avatar follows actual per-message operation and resets after completion, ignoring stale user keywords',async()=>{
 const h=harness();h.voice.inCall=false;h.voice.phase='idle';h.render();await h.flush();let tree=h.render();assert.ok(poses(tree).every(m=>m==='idle'));
 h.emit({type:'accepted',message_id:'one',client_id:'one',text:'昨天叫过车，今天只是聊天'});tree=h.render();assert.ok(poses(tree).every(m=>m==='working'));
 h.emit({type:'progress',message_id:'one',text:'正在查麦当劳菜单'});tree=h.render();assert.ok(poses(tree).every(m=>m==='dining'));
 h.emit(reply('one','查好了'));tree=h.render();assert.ok(poses(tree).every(m=>m==='idle'));
});
test('phone task and playback update the side character with no saved phone transcript',async()=>{
 const h=harness();h.voice.inCall=false;h.voice.phase='idle';h.render();await h.flush();let tree=h.render();
 const button=label=>all(tree,node=>node.type==='button'&&node.props['aria-label']===label)[0];
 button('更多功能').props.onClick();tree=h.render();button('拨打语音电话').props.onClick();await h.flush();tree=h.render();assert.ok(poses(tree).every(m=>m==='listening'));
 h.voice.speaking=true;tree=h.render();assert.ok(poses(tree).every(m=>m==='speaking'));h.voice.speaking=false;
 h.emit({type:'accepted',call_id:'call-test-1',message_id:'voice-one',text:'帮我打车' ,client_id:'voice-one'});
 h.emit({type:'progress',call_id:'call-test-1',message_id:'voice-one',text:'正在查滴滴车型'});tree=h.render();assert.ok(poses(tree).every(m=>m==='taxi'));
 assert.equal(all(tree,node=>node.type==='article').length,0);
 h.emit({...reply('voice-one','查好了'),call_id:'call-test-1'});tree=h.render();assert.ok(poses(tree).every(m=>m==='listening'));
});
