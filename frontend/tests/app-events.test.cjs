const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const React=require('react');
const code=ts.transpileModule(fs.readFileSync(require.resolve('../src/main.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
function harness(options={}){
 const slots=[];let index=0,callbacks,source;
 const paymentNavigations=[];
 const paymentModule={exports:{}};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(require.resolve('../src/payment.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module:paymentModule,exports:paymentModule.exports,URL,window:{open:(url,target,features)=>{if(target!=='_blank'||features!=='noopener,noreferrer')throw Error('unsafe payment window');paymentNavigations.push(url);}}});
 const spoken=[],feedback=[];const requests=[];let cancellations=0;
 const voice={phase:'listening',inCall:true,recording:false,transcript:'',speaking:false,loadingSpeech:false,speak:async text=>spoken.push(text),feedback:async text=>feedback.push(text),stopSpeech(){},cancel(){},cancelRecording(){cancellations++;voice.phase='idle';voice.recording=false;},startCall:async()=>{voice.inCall=true;voice.phase='listening';return true;},endCall(){voice.inCall=false;voice.phase='idle';}};
 const hooks={...React,useReducer(reducer,initial){const [state,setState]=hooks.useState(initial);return[state,action=>setState(old=>reducer(old,action))];},useState(initial){const i=index++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return[slots[i],value=>{slots[i]=typeof value==='function'?value(slots[i]):value;}];},useRef(value){const i=index++;if(!(i in slots))slots[i]={current:value};return slots[i];},useEffect(effect,deps){const i=index++;const old=slots[i];if(!old||!deps||deps.some((value,n)=>value!==old[n])){slots[i]=deps;effect();}}};
 class EventSource{constructor(){source=this;}close(){}}
 const module={exports:{}};
 const fetch=async (url,requestOptions)=>{requests.push({url,options:requestOptions});if(options.request){const result=await options.request(url,requestOptions);if(result)return result;}return{ok:true,headers:{get:()=> 'application/json'},json:async()=>url==='/api/health'?{mcd_configured:true,agent_configured:true}:url==='/api/contact/state'?{events:options.replay||[],cursor:0,pending:0}:url==='/api/chat/history'?{messages:[]}:url==='/api/actions'?{actions:[]}:url==='/api/contact/calls'?{id:'call-test-1',started_at:Date.now()/1000}:url.endsWith('/end')?{id:'call-test-1',started_at:Date.now()/1000-65,duration_seconds:65}: {accepted:true}};};
 require('./load-frontend.cjs')(code,{module,exports:module.exports,require:name=>name==='./CardHeading'?require('./load-card-heading.cjs'):name==='react'?hooks:name==='react-dom/client'?{createRoot:()=>({render(){}})}:name==='./useVoice'?{useVoice:(onFinal,onError,onSpeechStart)=>{callbacks={onFinal,onError,onSpeechStart};return voice;}}:name==='./Companion'?{Companion(){},CompanionAvatar(){},companionMood:()=> 'idle'}:name==='./SettingsDialog'?{SettingsDialog(){},useCompanionSettings:()=>({settings:{name:'小瑞',avatar:'portrait'},updateSettings(){}})}:name==='./CallBar'?{CallBar(){},callDuration:s=>String(s)}:name==='./ProfileCard'?{ProfileCard(){}}:name==='./location'?{locate:async()=>10}:name==='./payment'?paymentModule.exports:name==='./ActionCard'||name==='./ChoiceCards'?{}:name.endsWith('.css')?{}:name==='./money'?require('./load-money.cjs'):require(name),document:{getElementById:()=>({}),addEventListener(){},removeEventListener(){}},EventSource,fetch,crypto:require('node:crypto'),setInterval:()=>1,clearInterval(){},console});
 const render=()=>{index=0;return module.exports.App();};
 const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
 return{render,flush,spoken,feedback,voice,requests,paymentNavigations,get cancellations(){return cancellations;},get callbacks(){return callbacks;},emit:event=>source.onmessage({data:JSON.stringify(event)})};
}
function all(node,predicate){if(!node||typeof node!=='object')return[];if(typeof node.type==='function'&&['AppView','Conversation','Composer','MessageItem','FlightResults','StoreCards','MealCards','Mic','Keyboard','Photo','Phone'].includes(node.type.name))return[predicate(node)?node:null,...all(node.type(node.props),predicate)].filter(Boolean);return[predicate(node)?node:null,...React.Children.toArray(node.props?.children).flatMap(child=>all(child,predicate))].filter(Boolean);}
const reply=(id,text,events=[])=>({type:'completed',message_id:id,response:{text,speech_text:text,events}});
test('caller speech blocks late autoplay even when an old started event arrives afterwards; new final permits its own reply',async()=>{
 const h=harness();h.render();await h.flush();h.render();
 h.callbacks.onSpeechStart();
 h.emit({type:'accepted',message_id:'old',client_id:'old',text:'旧问题'});
 h.emit({type:'started',message_id:'old'});
 h.emit(reply('old','旧问题的迟到回答'));
 assert.deepEqual(h.spoken,[]);
 h.render();h.callbacks.onFinal('我刚刚说完的新问题');await h.flush();h.render();
 h.emit({type:'started',message_id:'new'});h.emit(reply('new','新问题的回答'));
 assert.deepEqual(h.spoken,['新问题的回答']);
});
test('nonvisual query receipts do not make empty bubbles and reply text appears once',async()=>{
 const h=harness();h.render();await h.flush();h.render();
 const receipt={type:'query_result',provider:'mcd',tool:'stores',success:true,source:'https://open.mcd.cn/mcp',data:{}};
 h.emit(reply('a','门店查好了',[receipt,{type:'stores',stores:[]},receipt,{type:'service_result',provider:'mcd',data:{}}]));
 let tree=h.render();
 const messages=()=>all(tree,node=>node.type==='article'&&node.props.className==='message assistant');
 assert.equal(messages().length,1);
 assert.equal(all(tree,node=>node.type==='p'&&node.props.className==='message-text'&&node.props.children==='门店查好了').length,1);
 h.emit(reply('b','还有一条查询结果',[receipt]));tree=h.render();assert.equal(messages().length,2);
 h.emit(reply('c','',[receipt]));tree=h.render();assert.equal(messages().length,2);
});

test('HTTP receipt and SSE replay show one quick answer and cannot resurrect a completed placeholder',async()=>{
 const h=harness();h.render();await h.flush();h.render();
 const accepted={type:'accepted',message_id:'receipt-1',client_id:'receipt-client',text:'帮我看看天气',ack_text:'好，我帮您看看。'};
 h.emit(accepted);h.emit(accepted);let tree=h.render();
 assert.equal(all(tree,n=>n.type==='p'&&n.props.children==='好，我帮您看看。').length,1);
 h.emit({...reply('receipt-1','真实查询结果'),response:{text:'真实查询结果',speech_text:'暂用安全播报',events:[],task_id:'task-1'}});h.emit(accepted);tree=h.render();
 assert.equal(all(tree,n=>n.type==='p'&&n.props.children==='真实查询结果').length,1);
 assert.equal(all(tree,n=>n.type?.name==='MessageProgress').length,0);
 const texts=all(tree,n=>n.type==='p').map(n=>n.props.children);
 assert.ok(texts.indexOf('好，我帮您看看。')<texts.indexOf('真实查询结果'));
 const count=all(tree,n=>n.type==='article').length;
 h.emit({type:'speech_ready',task_id:'task-1',speech_text:'后补的自然播报'});tree=h.render();
 assert.equal(all(tree,n=>n.type==='article').length,count);
});

const buttonByLabel=(tree,label)=>all(tree,node=>node.type==='button'&&node.props['aria-label']===label)[0];
test('switch input or open more functions cancels pending single-message recognition after mic release',async()=>{
 for(const label of ['切换到文字输入','更多功能']){
  const h=harness();h.render();await h.flush();h.voice.inCall=false;h.voice.phase='idle';let tree=h.render();
  buttonByLabel(tree,'切换到语音输入').props.onClick();h.voice.phase='finishing';h.voice.recording=false;tree=h.render();
  const record=buttonByLabel(tree,'正在识别语音');assert.ok(record);assert.equal(record.props.disabled,true);
  assert.equal(all(record,node=>node.type==='span'&&node.props.className==='record-caption')[0].props.children,'正在识别…');
  buttonByLabel(tree,label).props.onClick();assert.equal(h.cancellations,1);assert.equal(h.voice.phase,'idle');
 }
});
test('late reply cannot autoplay during single-message recognition with microphone already released',async()=>{
 const h=harness();h.render();await h.flush();h.voice.inCall=false;h.voice.phase='idle';let tree=h.render();
 buttonByLabel(tree,'切换到语音输入').props.onClick();h.voice.phase='finishing';h.voice.recording=false;h.render();
 h.emit({type:'started',message_id:'old'});h.emit(reply('old','不得在识别期间自动播放'));assert.deepEqual(h.spoken,[]);
 h.voice.phase='idle';h.render();h.callbacks.onFinal('新的语音最终结果');await h.flush();h.render();
 h.emit({type:'started',message_id:'new'});h.emit(reply('new','新的语音回复'));assert.deepEqual(h.spoken,['新的语音回复']);
});

test('identity opens settings and closing refreshes configuration health without submitting a query',async()=>{
 const h=harness();h.render();await h.flush();let tree=h.render();
 const identity=all(tree,node=>node.type==='button'&&node.props.className==='brand companion-settings-entry')[0];assert.match(identity.props['aria-label'],/外观与家人设置/);identity.props.onClick();tree=h.render();
 const dialog=all(tree,node=>node.type?.name==='SettingsDialog')[0];assert.equal(dialog.props.open,true);
 const before=h.requests.filter(r=>r.url==='/api/health').length;dialog.props.onClose();await h.flush();
 assert.equal(h.requests.filter(r=>r.url==='/api/health').length,before+1);assert.equal(h.requests.filter(r=>r.url==='/api/contact/messages').length,0);
});

test('original text composer exists, accepts typing, and sends actual text on Enter',async()=>{
 const h=harness();h.voice.inCall=false;h.voice.phase='idle';h.render();await h.flush();let tree=h.render();
 const textbox=()=>all(tree,node=>node.type==='textarea'&&node.props.id==='chat-input')[0];
 assert.ok(textbox(),'original textarea must remain in text mode');
 assert.equal(textbox().props.placeholder,'发消息给小瑞');
 textbox().props.onChange({target:{value:'陪我聊聊天'}});tree=h.render();assert.equal(textbox().props.value,'陪我聊聊天');
 let prevented=false;textbox().props.onKeyDown({key:'Enter',shiftKey:false,nativeEvent:{isComposing:false},preventDefault(){prevented=true;}});await h.flush();tree=h.render();
 assert.equal(prevented,true);const request=h.requests.find(r=>r.url==='/api/contact/messages');assert.equal(JSON.parse(request.options.body).text,'陪我聊聊天');assert.equal(textbox().props.value,'');
});
test('original composer preserves Shift+Enter and IME, with conditional text send button',async()=>{
 const h=harness();h.voice.inCall=false;h.voice.phase='idle';h.render();await h.flush();let tree=h.render();
 assert.equal(all(tree,node=>node.type==='button'&&node.props['aria-label']==='发送消息').length,0);
 const box=()=>all(tree,node=>node.type==='textarea'&&node.props.id==='chat-input')[0];box().props.onChange({target:{value:'还在输入'}});tree=h.render();
 const send=all(tree,node=>node.type==='button'&&node.props['aria-label']==='发送消息')[0];assert.ok(send);assert.equal(send.props.children,'发送');
 for(const [shiftKey,isComposing]of [[true,false],[false,true]])box().props.onKeyDown({key:'Enter',shiftKey,nativeEvent:{isComposing},preventDefault(){assert.fail('newline/IME must not submit');}});
 await h.flush();assert.equal(h.requests.filter(r=>r.url==='/api/contact/messages').length,0);
 buttonByLabel(tree,'切换到语音输入').props.onClick();tree=h.render();assert.equal(all(tree,node=>node.type==='textarea').length,0);assert.ok(buttonByLabel(tree,'开始语音输入'));
 buttonByLabel(tree,'切换到文字输入').props.onClick();tree=h.render();assert.equal(box().props.value,'还在输入');assert.ok(buttonByLabel(tree,'更多功能'));
});

async function connectPhone(h){h.voice.inCall=false;h.voice.phase='idle';h.render();await h.flush();let tree=h.render();buttonByLabel(tree,'更多功能').props.onClick();tree=h.render();buttonByLabel(tree,'拨打语音电话').props.onClick();await h.flush();return h.render();}
test('phone preserves composer, speaks an opening question and routes spoken turns outside chat bubbles',async()=>{
 const h=harness();let tree=await connectPhone(h);
 assert.equal(all(tree,n=>n.type==='textarea').length,1);
 assert.equal(all(tree,n=>n.type?.name==='CallBar').length,1);
 assert.equal(all(tree,n=>n.props?.className==='call-bar').length,0);
 assert.ok(h.feedback.includes('喂'));
 h.callbacks.onFinal('今天想吃午饭');await h.flush();tree=h.render();
 const request=h.requests.find(r=>r.url==='/api/contact/messages');assert.equal(JSON.parse(request.options.body).call_id,'call-test-1');
 h.emit({type:'accepted',call_id:'call-test-1',message_id:'voice-1',client_id:'voice-1',text:'今天想吃午饭'});
 h.emit({type:'delta',call_id:'call-test-1',message_id:'voice-1',text:'电话中不落气泡'});
 tree=h.render();assert.equal(all(tree,n=>n.type==='article').length,0);
});

test('phone does not preface each request with a canned acknowledgment and still speaks its real answer',async()=>{
 const h=harness();await connectPhone(h);h.feedback.length=0;h.spoken.length=0;
 h.callbacks.onFinal('帮我看看明天的天气');
 assert.deepEqual(h.feedback,[]);
 assert.deepEqual(h.spoken,[]);
 await h.flush();h.render();
 h.emit({type:'started',call_id:'call-test-1',message_id:'quick-weather'});
 h.emit({...reply('quick-weather','这是查询后的真实结果'),call_id:'call-test-1'});
 assert.deepEqual(h.spoken,['这是查询后的真实结果']);
});
test('phone cards appear without transcripts; hangup restores typing and leaves one duration record',async()=>{
 const h=harness();let tree=await connectPhone(h);const count=h.spoken.length;
 h.emit({type:'started',call_id:'call-test-1',message_id:'a'});
 h.emit({...reply('a','我给您发了餐品卡片',[{type:'meals',meals:[]}]),call_id:'call-test-1'});tree=h.render();
 assert.equal(h.spoken.length,count+1);
 assert.equal(all(tree,n=>n.type==='p'&&n.props.className==='message-text').length,0);
 assert.equal(all(tree,n=>n.props?.className==='meal-grid').length,1);
 all(tree,n=>n.type?.name==='CallBar')[0].props.onHangup();await h.flush();tree=h.render();assert.equal(all(tree,n=>n.type==='textarea').length,1);
 assert.equal(all(tree,n=>n.props?.className==='phone-record').length,1);
 const before=h.spoken.length;h.emit({...reply('late','挂断后的迟到回复'),call_id:'call-test-1'});tree=h.render();assert.equal(h.spoken.length,before);assert.equal(all(tree,n=>n.props?.className==='phone-record').length,1);
});
test('replayed call turns remain hidden and durable call summaries deduplicate',async()=>{
 const record={id:'old-call',started_at:1000,duration_seconds:65};
 const h=harness({replay:[{type:'accepted',call_id:'old-call',message_id:'old',text:'不显示的转录' ,client_id:'old'}, {...reply('old','不显示的回复'),call_id:'old-call'},{type:'call_ended',call:record}]});
 h.voice.inCall=false;h.voice.phase='idle';h.render();await h.flush();let tree=h.render();
 assert.equal(all(tree,n=>n.props?.className==='phone-record').length,1);assert.equal(all(tree,n=>n.type==='p'&&n.props.className==='message-text').length,0);
 h.emit({type:'call_ended',call:record});tree=h.render();assert.equal(all(tree,n=>n.props?.className==='phone-record').length,1);assert.deepEqual(h.spoken,[]);
});

test('each text message owns its progress and completion replaces only that progress',async()=>{
 const h=harness();h.voice.inCall=false;h.voice.phase='idle';h.render();await h.flush();
 for(const [id,text]of [['one','第一条消息'],['two','第二条消息']])h.emit({type:'accepted',message_id:id,client_id:id,text});
 h.emit({type:'progress',message_id:'one',text:'正在查麦当劳菜单'});
 h.emit({type:'progress',message_id:'two',text:'正在核对第二个需求'});
 let tree=h.render();const progress=()=>all(tree,n=>n.type?.name==='MessageProgress');assert.equal(progress().length,2);assert.deepEqual(progress().map(n=>n.props.text),['正在查麦当劳菜单','正在核对第二个需求']);
 h.emit({type:'delta',message_id:'one',text:'第一段回复'});tree=h.render();assert.equal(progress()[0].props.stream,'第一段回复');
 h.emit(reply('one','第一条正式回复'));tree=h.render();assert.equal(progress().length,1);assert.equal(progress()[0].props.text,'正在核对第二个需求');
 assert.equal(all(tree,n=>n.props?.className==='activity-strip').length,0);assert.equal(all(tree,n=>n.props?.className==='contact-progress').length,0);
 h.emit(reply('two','第二条正式回复'));tree=h.render();assert.equal(progress().length,0);
});
test('texting during a phone call remains an ordinary message and does not interrupt playback',async()=>{
 const h=harness();let tree=await connectPhone(h);let stops=0;h.voice.stopSpeech=()=>stops++;
 const input=all(tree,n=>n.type==='textarea')[0];assert.ok(input);input.props.onChange({target:{value:'我在电话中发一条文字'}});tree=h.render();
 all(tree,n=>n.type==='form'&&n.props.className==='composer wechat-composer')[0].props.onSubmit({preventDefault(){}});await h.flush();tree=h.render();
 const sent=h.requests.filter(r=>r.url==='/api/contact/messages').at(-1);assert.equal(JSON.parse(sent.options.body).text,'我在电话中发一条文字');assert.equal(JSON.parse(sent.options.body).call_id,undefined);assert.equal(stops,0);
 assert.equal(all(tree,n=>n.type==='article'&&n.props.className==='message user').length,1);
 const before=h.spoken.length;h.emit({type:'accepted',message_id:'sms',client_id:JSON.parse(sent.options.body).client_id,text:'我在电话中发一条文字'});h.emit({type:'progress',message_id:'sms',text:'正在处理文字消息'});
 h.emit(reply('sms','这是文字回复'));tree=h.render();assert.equal(h.spoken.length,before);assert.equal(all(tree,n=>n.type?.name==='CallBar').length,1);assert.equal(all(tree,n=>n.type==='textarea').length,1);
});
test('phone progress updates only the island subtitle, without a message placeholder',async()=>{
 const h=harness();let tree=await connectPhone(h);h.emit({type:'accepted',call_id:'call-test-1',message_id:'phone-one',text:'电话说的话' ,client_id:'phone-one'});
 h.emit({type:'progress',call_id:'call-test-1',message_id:'phone-one',text:'正在查滴滴车型'});tree=h.render();
 assert.equal(all(tree,n=>n.type?.name==='CallBar')[0].props.progress,'正在查滴滴车型');assert.equal(all(tree,n=>n.type?.name==='MessageProgress').length,0);

 assert.equal(all(tree,n=>n.props?.className==='activity-strip').length,0);assert.equal(all(tree,n=>n.props?.className==='contact-progress').length,0);
});
test('batched text reply replaces collected placeholders after the last user message',async()=>{
 const h=harness();h.voice.inCall=false;h.render();await h.flush();
 h.emit({type:'accepted',message_id:'one',client_id:'one',text:'第一段'});h.emit({type:'accepted',message_id:'two',client_id:'two',text:'补充条件'});
 h.emit({...reply('one','已结合两条消息回复'),message_ids:['one','two']});const tree=h.render();assert.equal(all(tree,n=>n.type?.name==='MessageProgress').length,0);

 const texts=all(tree,n=>n.type==='p'&&n.props.className==='message-text').map(n=>n.props.children);assert.deepEqual(texts,['第一段','补充条件','已结合两条消息回复']);
});

// Elderly-user scenarios: hesitation, double taps, mixed channels and accidental navigation.
test('elderly user double-taps send while the first receipt is pending: only one message is submitted',async()=>{
 let release;const wait=new Promise(resolve=>{release=resolve;});
 const h=harness({request:async(url)=>{if(url==='/api/contact/messages'){await wait;return{ok:true,headers:{get:()=> 'application/json'},json:async()=>({accepted:true})};}}});
 h.voice.inCall=false;h.voice.phase='idle';h.render();await h.flush();let tree=h.render();all(tree,n=>n.type==='textarea')[0].props.onChange({target:{value:'帮我看看午饭'}});tree=h.render();
 const submit=all(tree,n=>n.type==='form'&&n.props.className==='composer wechat-composer')[0].props.onSubmit;
 submit({preventDefault(){}});submit({preventDefault(){}});await h.flush();release();await h.flush();
 assert.equal(h.requests.filter(r=>r.url==='/api/contact/messages').length,1);
});
test('elderly user accidentally opens settings during a call: the phone must not hang up',async()=>{
 const h=harness();let tree=await connectPhone(h);
 all(tree,n=>n.props?.className==='brand companion-settings-entry')[0].props.onClick();await h.flush();tree=h.render();
 assert.equal(all(tree,n=>n.type?.name==='SettingsDialog')[0].props.open,true);
 assert.equal(all(tree,n=>n.type?.name==='CallBar').length,1);
 assert.equal(h.requests.filter(r=>r.url.endsWith('/end')).length,0);
});
test('elderly user taps end-call in the plus menu: it really ends the call once',async()=>{
 const h=harness();let tree=await connectPhone(h);buttonByLabel(tree,'更多功能').props.onClick();tree=h.render();
 const end=buttonByLabel(tree,'结束语音通话');assert.ok(end);end.props.onClick();await h.flush();tree=h.render();
 assert.equal(h.requests.filter(r=>r.url.endsWith('/end')).length,1);assert.equal(all(tree,n=>n.type?.name==='CallBar').length,0);
});
test('elderly user speaks while slowly typing an address: the unsent draft remains intact',async()=>{
 const h=harness();let tree=await connectPhone(h);all(tree,n=>n.type==='textarea')[0].props.onChange({target:{value:'三号楼二单元'}});tree=h.render();
 h.callbacks.onFinal('我还在找门牌，等我一下');await h.flush();tree=h.render();
 assert.equal(all(tree,n=>n.type==='textarea')[0].props.value,'三号楼二单元');
 const request=h.requests.find(r=>r.url==='/api/contact/messages');assert.equal(JSON.parse(request.options.body).call_id,'call-test-1');
});
test('elderly user hangs up twice: one duration record, no double end request',async()=>{
 const h=harness();let tree=await connectPhone(h);const end=all(tree,n=>n.type?.name==='CallBar')[0].props.onHangup;end();end();await h.flush();tree=h.render();
 assert.equal(h.requests.filter(r=>r.url.endsWith('/end')).length,1);assert.equal(all(tree,n=>n.props?.className==='phone-record').length,1);
});

test('elderly user loses network then retries: preserve text and reuse the same request id',async()=>{
 let attempt=0;const h=harness({request:async url=>{if(url==='/api/contact/messages'){attempt++;return{ok:attempt>1,headers:{get:()=> 'application/json'},json:async()=>attempt===1?{detail:'网络暂时不可用'}:{accepted:true}};}}});
 h.voice.inCall=false;h.voice.phase='idle';h.render();await h.flush();let tree=h.render();all(tree,n=>n.type==='textarea')[0].props.onChange({target:{value:'帮我找附近的店'}});tree=h.render();
 all(tree,n=>n.type==='form'&&n.props.className==='composer wechat-composer')[0].props.onSubmit({preventDefault(){}});await h.flush();tree=h.render();
 assert.equal(all(tree,n=>n.type?.name==='MessageProgress').length,0);
const retry=all(tree,n=>n.type==='button'&&n.props.children==='重试发送')[0];assert.ok(retry);retry.props.onClick();await h.flush();
 const sent=h.requests.filter(r=>r.url==='/api/contact/messages').map(r=>JSON.parse(r.options.body));assert.equal(sent.length,2);assert.equal(sent[0].client_id,sent[1].client_id);assert.equal(sent[1].text,'帮我找附近的店');
});
test('elderly user cannot grant microphone permission: end the call record and keep typing available',async()=>{
 const h=harness();h.voice.startCall=async()=>{h.voice.inCall=false;h.voice.phase='idle';h.callbacks.onError('麦克风未获允许，您仍可以打字。');return false;};
 const tree=await connectPhone(h);assert.equal(all(tree,n=>n.type?.name==='CallBar').length,0);assert.equal(all(tree,n=>n.type==='textarea').length,1);assert.equal(h.requests.filter(r=>r.url.endsWith('/end')).length,1);
 assert.ok(all(tree,n=>n.props?.role==='alert').some(n=>JSON.stringify(n.props.children).includes('麦克风未获允许')));
});

test('selecting a meal card sends its exact candidate once and waits for server options, never confirms an order',async()=>{
 const h=harness();h.render();await h.flush();h.voice.inCall=false;h.voice.phase='idle';
 const choices=[{kind:'product',label:'麦香鱼套餐',price_yuan:'33.00',prompt:'选择第7个商品：麦香鱼套餐。请继续给我核对，先不要执行交易。'}];
 h.emit(reply('food','看看这份套餐',[{type:'service_choices',choices}]));let tree=h.render();
 const card=all(tree,n=>n.props?.choices?.[0]?.label==='麦香鱼套餐')[0];assert.ok(card);assert.equal(card.props.disabled,false);
 card.props.onChoose(choices[0].prompt);card.props.onChoose(choices[0].prompt);await h.flush();
 const sends=h.requests.filter(r=>r.url==='/api/contact/messages');assert.equal(sends.length,1);
 assert.equal(JSON.parse(sends[0].options.body).text,choices[0].prompt);
 assert.equal(h.requests.filter(r=>/\/api\/actions\/.*\/confirm/.test(r.url)).length,0);
 const nextChoices=[{...choices[0],label:'新的餐品',prompt:'选择第1个商品'}];
 h.emit(reply('next','请看新的餐品',[{type:'service_choices',choices:nextChoices}]));tree=h.render();
 const cards=all(tree,n=>Array.isArray(n.props?.choices));
 assert.equal(cards.find(n=>n.props.choices[0].label==='麦香鱼套餐').props.disabled,true);
 assert.equal(cards.find(n=>n.props.choices[0].label==='新的餐品').props.disabled,false);
});


test('voice final confirmation opens the returned payment page once and ends the call; replay never navigates',async()=>{
 const plan={id:'paid-proposal',provider:'mcd',action:'create',status:'created',execution_enabled:true,confirmation_text:'确认下单',version:1,confirmation_token:'test',expires_at:Date.now()/1000+300,amount_cents:2500,summary:{product:'测试套餐'},order:{order_id:'fixture',payment_url:'https://example.invalid/fixture-payment'}};
 const h=harness();await connectPhone(h);
 const event={...reply('confirmed','订单已创建，接下来到官方页面付款。',[{type:'action_plan',plan}]),call_id:'call-test-1'};
 h.emit(event);await h.flush();h.render();
 assert.deepEqual(h.paymentNavigations,['https://example.invalid/fixture-payment']);
 h.emit(event);await h.flush();assert.equal(h.paymentNavigations.length,1);
 assert.equal(h.voice.inCall,false);
 const restored=harness({replay:[event]});restored.render();await restored.flush();restored.render();assert.deepEqual(restored.paymentNavigations,[]);
});
test('legacy store, meal, order and location cards each expose a purpose heading',async()=>{
 const h=harness();h.render();await h.flush();h.render();
 h.emit(reply('stores','',[{type:'stores',stores:[{code:'demo',name:'演示门店',address:'测试地址'}]}]));
 h.emit(reply('meals','',[{type:'meals',meals:[{product_code:'demo',name:'演示餐品',amount_cents:2500,choices:[],request:{}}]}]));
 h.emit(reply('plan','',[{type:'plan',plan:{id:'demo',status:'awaiting_confirmation',version:1,confirmation_token:'test',expires_at:Date.now()/1000+300,amount_cents:2500,summary:{product_name:'演示餐品',quantity:1,choices:[],store_name:'演示门店',store_address:'测试地址',take_way:'到店自取'}}}]));
 h.emit(reply('location','请授权定位后继续'));
 const titles=all(h.render(),n=>n.type?.name==='CardHeading').map(n=>n.props.title);
 for(const title of ['选择方便的取餐门店','挑选一份喜欢的餐品','提供本次位置'])assert.ok(titles.includes(title),title);
 assert.ok(titles.includes('核对您的点餐方案')||all(h.render(),n=>n.props?.plan?.id==='demo').length,'legacy proposals keep a heading or use the unified titled action card');
});

test('malformed SSE nested plan cannot mutate the conversation or open payment',async()=>{
 const h=harness();h.render();await h.flush();h.render();
 h.emit({type:'completed',message_id:'bad',response:{text:'不要显示',events:[{type:'action_plan',plan:{id:'bad',summary:null}}]}});
 const tree=h.render();assert.equal(all(tree,n=>n.type==='article').length,0);assert.deepEqual(h.paymentNavigations,[]);
 assert.ok(all(tree,n=>n.props?.role==='alert').some(n=>JSON.stringify(n.props.children).includes('消息显示异常')));
});

test('duplicate completed delivery never adds a second final reply',async()=>{
 const h=harness();h.render();await h.flush();h.render();
 const event=reply('same','唯一的最终回复');h.emit(event);h.emit(event);
 const tree=h.render();assert.equal(all(tree,n=>n.type==='p'&&n.props.className==='message-text'&&n.props.children==='唯一的最终回复').length,1);
});
test('one malformed historical record does not disable valid messages or the composer',async()=>{
 const h=harness({replay:[{type:'unknown'},reply('valid-history','保留的历史回复')]});h.render();await h.flush();const tree=h.render();
 assert.equal(all(tree,n=>n.type==='textarea').length,1);
 assert.ok(all(tree,n=>n.type==='p'&&n.props.className==='message-text'&&n.props.children==='保留的历史回复').length);
});

test('flight result becomes a booking card in chat, phone and replay without auto-navigation',async()=>{
 const flight={type:'flight_result',data:{flights:[{ticket_price_yuan:'400.00',booking_url:'https://router.feizhu.com/ws/example',journeys:[{type:'直达',segments:[{marketingTransportNo:'MF8561',depStationName:'大兴',arrStationName:'浦东',depDateTime:'2026-11-13 08:00',arrDateTime:'2026-11-13 10:10'}]}]}]}};
 for(const replay of [false,true]){
  const response=reply('flight-'+replay,'查询结果',[flight]);
  const h=harness(replay?{replay:[response]}:{});h.render();await h.flush();h.render();
  if(!replay)h.emit(response);
  const tree=h.render();
  const links=all(tree,n=>n.type==='a'&&n.props.href==='https://router.feizhu.com/ws/example');
  assert.equal(links.length,1);assert.equal(links[0].props.target,'_blank');
  assert.deepEqual(h.paymentNavigations,[]);
 }
 const h=harness();h.render();await h.flush();h.render();
 h.emit({...reply('flight-call','电话结果',[flight]),call_id:'call-test'});
 const tree=h.render();assert.equal(all(tree,n=>n.type==='a'&&n.props.href==='https://router.feizhu.com/ws/example').length,1);
 assert.deepEqual(h.paymentNavigations,[]);
});
