import React, {useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';
import {ChoiceCards,ChoiceCard} from './ChoiceCards';
import {useVoice} from './useVoice';
import {ActionCard,ActionPlan} from './ActionCard';
import {ProfileCard} from './ProfileCard';
import {locate} from './location';
import {CallBar,PhoneCall,callDuration} from './CallBar';
import {Companion,CompanionAvatar,companionMood} from './Companion';
import {SettingsDialog,useCompanionSettings} from './SettingsDialog';


type Store={code:string;name:string;address:string;open?:boolean};
type Selection={store_code:string;product_code:string;quantity:number;rounds:{round_id:string;code:string;quantity:number}[]};
type Meal={product_code:string;name:string;image?:string;amount_cents:number;choices:string[];request:Selection};
type Plan={id:string;version:number;status:string;amount_cents:number;summary:{store_name:string;store_address:string;product_name:string;quantity:number;choices:string[];take_way:string};expires_at:number;confirmation_token:string;order?:{order_id?:string;payment_url?:string};error?:string};
type ImageMessage={id:string;url:string};
type Message={pending?:boolean;progress?:string;stream?:string;replyTo?:string;call?:PhoneCall;locationRequest?:boolean;images?:ImageMessage[];client_id?:string;message_id?:string;delivery?:string;id:number;role:'user'|'assistant';text:string;speech_text?:string;kind?:'stores'|'meals'|'plan';stores?:Store[];meals?:Meal[];plan?:Plan;actionPlan?:ActionPlan;choices?:ChoiceCard[]};
type Health={read_only?:boolean;order_execution_enabled:boolean;mcd_configured:boolean;agent_configured?:boolean};
type ChatEvent={type:'location_request'}|{type:'stores';stores:Store[]}|{type:'meals';meals:Meal[]}|{type:'plan';plan:Plan}|{type:'action_plan';plan:ActionPlan}|{type:'service_choices';choices:ChoiceCard[]}|{type:'service_result';provider:string;data:unknown}|{type:'query_result';provider:string;tool:string;success:boolean;source:string;data:unknown};

type ChatResponse={text:string;speech_text?:string;events:ChatEvent[];conversation_reset?:boolean};
const yuan=(n:number)=>`¥${(n/100).toFixed(2)}`;
const labels:Record<string,string>={awaiting_confirmation:'请您确认',needs_review:'价格有变化，请再次确认',rechecking:'正在重新核价',submitting:'正在创建订单',created:'订单已创建，待支付',unknown:'订单结果待核查',failed:'未能创建订单',cancelled:'方案已取消',superseded:'方案已替换',expired:'报价已过期'};
async function api<T>(url:string,body?:unknown):Promise<T>{const r=await fetch(url,{method:body===undefined?'GET':'POST',headers:body===undefined?undefined:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});if(!r.headers.get('content-type')?.includes('application/json'))throw Error('本地服务暂时不可用，请稍后重试。');const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'这一步暂时没有完成，请稍后重试。');return d}
function Mic(){return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><rect x="8" y="2" width="8" height="13" rx="4"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>}
function Keyboard(){return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="2" y="5" width="20" height="14" rx="3"/><path d="M5 9h2m2 0h2m2 0h2m2 0h2M5 12h2m2 0h2m2 0h2m2 0h2M7 15h10"/></svg>}
function Photo(){return <svg viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><rect x="3" y="4" width="22" height="20" rx="3"/><circle cx="10" cy="10" r="2"/><path d="m4 21 7-7 4 4 4-6 6 8"/></svg>}
function Phone(){return <svg viewBox="0 0 28 28" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M7 4 3.5 7.5c-1 6 11 18 17 17L24 21l-5-5-3 2c-3-1-5-3-6-6l2-3-5-5Z"/></svg>}
export function MessageProgress({text,stream}:{text:string;stream?:string}){
 return <div className="message-progress"><span role="status" className="message-progress-label"><span className="reply-dot" aria-hidden="true"/>{text||'正在回复'}</span>{stream&&<p className="message-text">{stream}</p>}</div>;
}
export function App(){
 const [health,setHealth]=useState<Health>();const [messages,setMessages]=useState<Message[]>([]);const [input,setInput]=useState('');const [stores,setStores]=useState<Store[]>([]);const [busy,setBusy]=useState('正在恢复对话');const [error,setError]=useState('');const [meals,setMeals]=useState<Meal[]>([]);const [plan,setPlan]=useState<Plan>();const [modal,setModal]=useState(false);const [now,setNow]=useState(Date.now());const counter=useRef(0);const lock=useRef(false);const end=useRef<HTMLDivElement>(null);const dialog=useRef<HTMLDivElement>(null);
 const [ready,setReady]=useState(false);const [chatPending,setChatPending]=useState(0);const [contactStatus,setContactStatus]=useState('');const [phoneProgress,setPhoneProgress]=useState('');const phonePendingIds=useRef(new Set<string>());const pendingIds=useRef(new Set<string>());const interrupted=useRef(false);
 const [inputMode,setInputMode]=useState<'text'|'voice'>('text');const [extrasOpen,setExtrasOpen]=useState(false);const [attachments,setAttachments]=useState<ImageMessage[]>([]);const [uploading,setUploading]=useState(false);const imageInput=useRef<HTMLInputElement>(null);const inflightSends=useRef(new Set<string>());
 const [profileOpen,setProfileOpen]=useState(false);
 const [locationStatus,setLocationStatus]=useState('');const [locationBusy,setLocationBusy]=useState(false);const locationFresh=useRef(0);const locating=useRef<Promise<boolean>|null>(null);
 useEffect(()=>{
  if(!locationStatus||locationBusy)return;
  const timer=setTimeout(()=>setLocationStatus(''),5000);
  return()=>clearTimeout(timer);
 },[locationStatus,locationBusy]);
 async function requestLocation(){
  if(locating.current)return locating.current;
  const job=(async()=>{setLocationBusy(true);setLocationStatus('正在定位，请留意浏览器或系统权限提示…');try{const accuracy=await locate();locationFresh.current=Date.now();setLocationStatus(`已定位 · 误差约${Math.ceil(accuracy)}米 · 2分钟有效`);return true;}catch(e){setLocationStatus(e instanceof Error?e.message:'定位失败，请说出地标。');return false;}})();
  locating.current=job;try{return await job;}finally{locating.current=null;setLocationBusy(false);}
 }
 const [activeAction,setActiveAction]=useState('');
 const [activeChoices,setActiveChoices]=useState<ChoiceCard[]>();
 const [phone,setPhone]=useState<PhoneCall>();const activePhone=useRef<PhoneCall|undefined>(undefined);const startingPhone=useRef(false);const greetedPhone=useRef('');
 const {settings,updateSettings}=useCompanionSettings();const [settingsOpen,setSettingsOpen]=useState(false);
 const [voiceNotice,setVoiceNotice]=useState('');const autoplayAllowed=useRef(true);const composerWrap=useRef<HTMLDivElement>(null);
 const voice=useVoice(text=>{void send(text,activePhone.current?.id)},text=>{setError(text==='请先配置豆包语音服务。'?'语音还没接通，请家人帮忙完成设置。您可以继续打字。':text);},()=>{autoplayAllowed.current=false;interrupted.current=true;});
 const messageCaptureActive=!voice.inCall&&voice.phase!=='idle';
 useEffect(()=>{document.title=`${settings.name} · 您的生活小帮手`;},[settings.name]);
 const add=(m:Omit<Message,'id'>)=>setMessages(old=>[...old,{...m,id:++counter.current}]);
 function replacePending(incoming:Omit<Message,'id'>[],ids:string[]=[]){
  const replies=incoming.map(message=>({...message,id:++counter.current}));
  setMessages(old=>{const at=old.reduce((last,m,index)=>m.pending&&ids.includes(m.message_id||'')?index:last,-1);if(at<0)return [...old,...replies];const before=old.slice(0,at).filter(m=>!m.pending||!ids.includes(m.message_id||''));const after=old.slice(at).filter(m=>!m.pending||!ids.includes(m.message_id||''));return [...before,...replies,...after];});
 }
 function updateProgress(ids:string[],patch:Partial<Message>){setMessages(old=>old.map(m=>m.pending&&ids.includes(m.message_id||'')?{...m,...patch}:m));}
 function receive(e:any,replay=false){
  if(e.type==='call_ended'){showCall(e.call);return;}
  if(e.type==='accepted'){
   pendingIds.current.add(e.message_id);
   if(e.call_id){if(e.call_id===activePhone.current?.id)phonePendingIds.current.add(e.message_id);setChatPending(pendingIds.current.size);return;}
   setMessages(old=>old.some(m=>m.client_id===e.client_id)?old.map(m=>m.client_id===e.client_id?{...m,message_id:e.message_id,delivery:'已送达',images:e.images}:m):[...old,{id:++counter.current,role:'user',text:e.text,images:e.images,client_id:e.client_id,message_id:e.message_id,delivery:'已送达'}]);
   setMessages(old=>{const existing=old.find(m=>m.pending&&m.replyTo===e.client_id);if(existing)return old.map(m=>m===existing?{...m,message_id:e.message_id,progress:'消息已收到，正在准备回复'}:m);const at=old.findIndex(m=>m.client_id===e.client_id);const progress:Message={id:++counter.current,role:'assistant',text:'',pending:true,replyTo:e.client_id,message_id:e.message_id,progress:'消息已收到，正在准备回复'};return at<0?[...old,progress]:[...old.slice(0,at+1),progress,...old.slice(at+1)];});
  }else if(e.type==='started'){interrupted.current=false;if(e.call_id){if(e.call_id===activePhone.current?.id)setPhoneProgress('正在听，也在帮您处理');}else updateProgress(e.message_ids||[e.message_id],{progress:'正在理解您的消息'});}
  else if(e.type==='delta'&&!interrupted.current&&!e.call_id){setMessages(old=>old.map(m=>m.pending&&m.message_id===e.message_id?{...m,stream:((m.stream||'')+e.text).slice(-12000),progress:'正在回复'}:m));}
  else if(e.type==='progress'){if(e.call_id){if(e.call_id===activePhone.current?.id)setPhoneProgress(e.text);}else updateProgress([e.message_id],{progress:e.text});}
  else if(e.type==='completed'||e.type==='failed'){
   for(const id of e.message_ids||[e.message_id])pendingIds.current.delete(id);
   for(const id of e.message_ids||[e.message_id])phonePendingIds.current.delete(id);
   setContactStatus('');if(e.call_id===activePhone.current?.id)setPhoneProgress('');
   if(e.type==='failed'){const message=e.text==='请先配置豆包文本模型，再开始对话。'?'小瑞还没接通对话服务，请家人帮忙完成设置。':e.text;if(!e.call_id)replacePending([{role:'assistant',text:message,speech_text:message}],e.message_ids||[e.message_id]);else if(!replay)setError(message);if(!replay&&(e.call_id?e.call_id===activePhone.current?.id&&voice.inCall:!activePhone.current&&(voice.inCall||inputMode==='voice'))&&!voice.recording&&!messageCaptureActive&&!interrupted.current&&autoplayAllowed.current)void voice.speak(message);}
   else if(!e.superseded){const d=e.response as ChatResponse;if(d.conversation_reset){setMessages([]);setStores([]);setMeals([]);setPlan(undefined);setModal(false);}displayResponse(d,!!e.call_id,e.message_ids||[e.message_id]);if(!replay&&(e.call_id?e.call_id===activePhone.current?.id&&voice.inCall:!activePhone.current&&(voice.inCall||inputMode==='voice'))&&!voice.recording&&!messageCaptureActive&&!interrupted.current&&autoplayAllowed.current&&d.speech_text)void voice.speak(d.speech_text);}
   if(e.superseded&&!e.call_id)replacePending([],e.message_ids||[e.message_id]);
   if(!replay)void api<{actions:ActionPlan[]}>('/api/actions').then(d=>d.actions.forEach(updateAction)).catch(()=>{});
  }
  setChatPending(pendingIds.current.size);
 }
 const receiver=useRef(receive);receiver.current=receive;
 useEffect(()=>{
  let alive=true;let source:EventSource|undefined;
  api<Health>('/api/health').then(async h=>{
   const state=await api<{events:any[];cursor:number;pending:number;active_call?:PhoneCall}>('/api/contact/state');
   if(!alive)return;setHealth(h);if(state.active_call){void api<PhoneCall>(`/api/contact/calls/${state.active_call.id}/end`,{}).then(showCall).catch(()=>setError('上次通话记录暂未同步，请稍后刷新。'));}
   if(state.events.length){state.events.forEach(e=>receiver.current(e,true));}else{const history=await api<{messages:({role:'user'|'assistant'}&ChatResponse)[]}>('/api/chat/history');if(!alive)return;for(const message of history.messages){if(message.role==='user')add({role:'user',text:message.text});else displayResponse(message);}}
   if(!alive)return;setChatPending(state.pending);setReady(true);setBusy('');
   source=new EventSource(`/api/contact/events?after=${state.cursor}`);
   source.onmessage=e=>{try{receiver.current(JSON.parse(e.data));}catch{setError('消息显示异常，请刷新恢复记录。');}};
   source.onerror=()=>{setMessages(old=>old.map(m=>m.pending?{...m,progress:'消息连接正在恢复，已收到的消息仍会继续处理'}:m));if(activePhone.current)setPhoneProgress('消息连接正在恢复');};
   source.onopen=()=>{setContactStatus('');setPhoneProgress('');};
   const actions=await api<{actions:ActionPlan[]}>('/api/actions');if(alive)actions.actions.forEach(updateAction);
  }).catch(()=>{if(alive){setError('未能连接小瑞，请检查服务后刷新页面。');setBusy('');}});
  const t=setInterval(()=>setNow(Date.now()),1000);return()=>{alive=false;source?.close();clearInterval(t);};
 },[]);
 useEffect(()=>{const element=composerWrap.current;if(!element)return;const measure=()=>document.documentElement.style.setProperty('--composer-height',`${element.getBoundingClientRect().height}px`);measure();const observer=new ResizeObserver(measure);observer.observe(element);return()=>{observer.disconnect();document.documentElement.style.removeProperty('--composer-height');};},[]);
 useEffect(()=>{end.current?.scrollIntoView({behavior:'smooth',block:'end'})},[messages,busy]);
 useEffect(()=>{if(!modal)return;const previous=document.activeElement as HTMLElement|null;const el=dialog.current;el?.querySelector<HTMLButtonElement>('button')?.focus();function key(e:KeyboardEvent){if(e.key==='Escape')setModal(false);if(e.key==='Tab'&&el){const b=Array.from(el.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'));if(!b.length)return;const first=b[0],last=b[b.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}}document.addEventListener('keydown',key);return()=>{document.removeEventListener('keydown',key);previous?.focus()}},[modal]);
 useEffect(()=>{if(!extrasOpen)return;const close=(e:KeyboardEvent)=>{if(e.key==='Escape')setExtrasOpen(false);};document.addEventListener('keydown',close);return()=>document.removeEventListener('keydown',close);},[extrasOpen]);
 const blocked=Boolean(plan&&['unknown','submitting','rechecking'].includes(plan.status));
 async function task(title:string,fn:()=>Promise<void>){if(lock.current)return;lock.current=true;setBusy(title);setError('');try{await fn()}catch(e){setError(e instanceof Error?e.message:'暂时没有完成，请重试。')}finally{setBusy('');lock.current=false}}
 function update(p:Plan){setPlan(p);setMessages(old=>old.map(m=>m.plan?.id===p.id?{...m,plan:p}:m))}
 function updateAction(p:ActionPlan){setMessages(old=>old.map(m=>m.actionPlan?.id===p.id?{...m,actionPlan:p}:m))}
 async function release(){if(plan&&['awaiting_confirmation','needs_review','expired'].includes(plan.status)){const d=await api<{plan:Plan}>(`/api/plans/${plan.id}/cancel`,{});update(d.plan)}}
 function displayResponse(d:ChatResponse,phoneTurn=false,replyIds:string[]=[]){
   const incoming:Omit<Message,'id'>[]=[];
   const response:Omit<Message,'id'>={role:'assistant',text:d.text,speech_text:d.speech_text,locationRequest:/定位|上车.*位置/.test(d.text)};
   const events=(d.events??[]).filter(event=>['stores','meals','plan','action_plan','service_choices','location_request'].includes(event.type));
   if(!phoneTurn&&!events.length&&(d.text||d.speech_text))incoming.push(response);

   events.forEach((event,i)=>{
    const message:Omit<Message,'id'>={role:'assistant',text:!phoneTurn&&i===0?d.text:'',speech_text:!phoneTurn&&i===0?d.speech_text:undefined,locationRequest:event.type==='location_request'||(i===0&&/定位|上车.*位置/.test(d.text))};
    if(event.type==='stores'){setStores(event.stores);setMeals([]);message.kind='stores';message.stores=event.stores}
    if(event.type==='meals'){setMeals(event.meals);message.kind='meals';message.meals=event.meals}
    if(event.type==='plan'){update(event.plan);message.kind='plan';message.plan=event.plan}
    if(event.type==='action_plan'){updateAction(event.plan);setActiveAction(event.plan.id);message.actionPlan=event.plan}
    if(event.type==='service_choices'){message.choices=event.choices;setActiveChoices(event.choices)}
    incoming.push(message);
   });
   replacePending(incoming,replyIds);
 }
 async function send(spoken?:string,phoneId?:string){
  const outgoingImages=spoken===undefined?attachments:[];const text=(spoken??input).trim()||(outgoingImages.length?'请看看这张图片。':'');if(!text||!ready||uploading)return;
  const submissionKey=JSON.stringify([phoneId||'chat',text,outgoingImages.map(image=>image.id)]);if(inflightSends.current.has(submissionKey))return;inflightSends.current.add(submissionKey);
  try{
  if(outgoingImages.length)setAttachments([]);setExtrasOpen(false);
  if(phoneId||!activePhone.current){if(!phoneId)voice.stopSpeech();autoplayAllowed.current=true;interrupted.current=true;if(phoneId)void voice.feedback(text,true);}setVoiceNotice('');if(spoken===undefined)setInput('');setActiveChoices(undefined);setActiveAction('');setPlan(undefined);setModal(false);
  const client_id=crypto.randomUUID();if(!phoneId){add({role:'user',text,client_id,images:outgoingImages,delivery:'正在发送'});add({role:'assistant',text:'',pending:true,replyTo:client_id,progress:'正在发送消息…'});}
  if(/打车|叫车|我在哪|我的位置|当前位置|定位/.test(text)&&!/^确认/.test(text)&&Date.now()-locationFresh.current>110000)await requestLocation();
  await transmit(text,client_id,outgoingImages,phoneId);
  }finally{inflightSends.current.delete(submissionKey);}
 }
 async function transmit(text:string,client_id:string,images:ImageMessage[]=[],phoneId?:string){
  try{await api('/api/contact/messages',{text,client_id,image_ids:images.map(i=>i.id),...(phoneId?{call_id:phoneId}:{})});}
  catch(e){setMessages(old=>old.filter(m=>!m.pending||m.replyTo!==client_id).map(m=>m.client_id===client_id&&m.delivery!=='已送达'?{...m,delivery:'发送结果待核实'}:m));setError(e instanceof Error?e.message:'连接已断开，可以点击消息旁重试；不会重复提交同一条消息。');if(phoneId&&phoneId===activePhone.current?.id)void voice.speak('刚才那句话没有确认发送成功，请您稍后再说一次。');}
 }
 async function selectImages(files:FileList|null){
  if(!files?.length)return;setExtrasOpen(false);setUploading(true);setError('');
  try{if(files.length+attachments.length>4)throw Error('每条消息最多发送四张图片。');
   for(const file of Array.from(files)){
    if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8_000_000)throw Error('请选择 8 MB 以内的 JPG、PNG 或 WebP 图片。');
    const data_url=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(Error('图片读取失败，请重新选择。'));reader.readAsDataURL(file);});
    const image=await api<ImageMessage>('/api/contact/images',{data_url});setAttachments(old=>[...old,image]);
   }
  }catch(e){setError(e instanceof Error?e.message:'图片暂时无法发送。');}finally{setUploading(false);if(imageInput.current)imageInput.current.value='';}
 }
 function playReply(text:string){autoplayAllowed.current=false;setVoiceNotice('');void voice.speak(text);}
 function stopPlayback(){autoplayAllowed.current=false;voice.stopSpeech();setVoiceNotice('已停止播报，文字消息仍然保留。');}
 function cancelVoiceMessage(){autoplayAllowed.current=false;interrupted.current=true;voice.cancelRecording();setVoiceNotice('已取消这段录音，没有发送。');}
 function showCall(call:PhoneCall){setMessages(old=>{const existing=old.find(m=>m.call?.id===call.id);return existing?old.map(m=>m.call?.id===call.id?{...m,call}:m):[...old,{id:++counter.current,role:'assistant',text:'',call}];});}
 async function finishPhone(){const call=activePhone.current;if(!call)return;activePhone.current=undefined;setPhone(undefined);phonePendingIds.current.clear();setPhoneProgress('');try{const ended=await api<PhoneCall>(`/api/contact/calls/${call.id}/end`,{});showCall(ended);}catch{setError('通话已停止，时长记录暂未同步，请刷新后核对。');}}
 function hangup(){autoplayAllowed.current=false;interrupted.current=true;voice.endCall();setVoiceNotice('已挂断。');void finishPhone();}
 async function startPhone(){if(startingPhone.current||activePhone.current)return;startingPhone.current=true;setExtrasOpen(false);setError('');try{const call=await api<PhoneCall>('/api/contact/calls',{});activePhone.current=call;setPhone(call);autoplayAllowed.current=true;setVoiceNotice('');const connected=await voice.startCall();if(!connected&&activePhone.current?.id===call.id)await finishPhone();}catch(e){setError(e instanceof Error?e.message:'暂时无法接通电话。');void finishPhone();}finally{startingPhone.current=false;}}
 useEffect(()=>{if(phone&&!voice.inCall&&!startingPhone.current)void finishPhone();},[voice.inCall,phone]);
 useEffect(()=>{if(phone&&voice.inCall&&voice.phase==='listening'&&greetedPhone.current!==phone.id){greetedPhone.current=phone.id;void voice.feedback('喂');}},[phone,voice.inCall,voice.phase]);
 function switchInput(){if(messageCaptureActive)cancelVoiceMessage();setInputMode(old=>old==='text'?'voice':'text');setExtrasOpen(false);}
 async function chooseStore(s:Store){await send(`选择门店：${s.name}。`,activePhone.current?.id)}
 async function selectMeal(m:Meal,index:number){await send(`选第${index+1}份套餐，${m.name}。`,activePhone.current?.id)}
 async function cancel(p:Plan){await task('正在取消方案',async()=>{const d=await api<{plan:Plan}>(`/api/plans/${p.id}/cancel`,{});update(d.plan);add({role:'assistant',text:'这份方案已取消，没有创建订单。您可以重新选择。'})})}
 async function confirm(){if(!plan)return;setModal(false);await task('正在核实价格并创建订单，请勿重复操作',async()=>{try{const d=await api<{plan:Plan}>(`/api/plans/${plan.id}/confirm`,{version:plan.version,confirmation_token:plan.confirmation_token,confirmation_text:'确认下单'});update(d.plan)}catch(e){try{const d=await api<{plan:Plan}>(`/api/plans/${plan.id}`);update(d.plan)}catch{}throw e}})}

 function planCard(p:Plan){const current=p.id===plan?.id;const review=['awaiting_confirmation','needs_review'].includes(p.status);const expired=p.expires_at*1000<=now;const payment=p.order?.payment_url;return <div className="order-card"><div className="card-overline">{labels[expired&&review?'expired':p.status]||p.status}</div><h3>{p.summary.product_name} <small>×{p.summary.quantity}</small></h3><ul>{p.summary.choices.map((s,i)=><li key={i}>{s}</li>)}</ul><div className="pickup"><strong>{p.summary.store_name}</strong><span>{p.summary.store_address}</span><span>{p.summary.take_way}</span></div><div className="total"><span>本次总价</span><strong>{yuan(p.amount_cents)}</strong></div>{p.error&&<p className="note">{p.error}</p>}{review&&!health?.order_execution_enabled&&<p className="note">当前仅查看真实报价，下单尚未开启。</p>}{p.status==='unknown'&&<p className="note">请到麦当劳官方渠道核查，暂时不要重复下单。</p>}{p.status==='created'&&<><p>订单号：{p.order?.order_id}，尚未代表支付成功。</p>{payment?.startsWith('https://')&&<a className="primary link-button" href={payment} target="_blank" rel="noreferrer">前往官方支付页面 ↗</a>}</>}{review&&current&&<div className="card-actions"><button className="primary" disabled={!!busy||expired||!health?.order_execution_enabled} onClick={()=>setModal(true)}>确认这个方案</button><button disabled={!!busy} onClick={()=>cancel(p)}>取消方案</button></div>}<small className="disclaimer">到店自取 · 官方核价 · 下单前再次核实</small></div>}
 const taskProgress=phonePendingIds.current.size?phoneProgress:(messages.filter(message=>message.pending).at(-1)?.progress||'');
 const mood=companionMood({phase:voice.phase,recording:voice.recording,speaking:voice.speaking,loadingSpeech:voice.loadingSpeech,pending:Math.max(chatPending,messages.filter(message=>message.pending).length,busy?1:0),context:taskProgress||busy});
 const companionLabel={idle:'安静陪伴',listening:'正在倾听',working:'正在思考',speaking:'正在说话',taxi:'正在处理出行查询',dining:'正在处理餐饮查询'}[mood];
 function openSettings(){if(messageCaptureActive)cancelVoiceMessage();if(!voice.inCall)stopPlayback();setSettingsOpen(true);}
 return <div className={(messages.length?'app':'app empty')+(phone?' phone-active':'')}><header><button className="brand companion-settings-entry" type="button" onClick={openSettings} aria-label="助手外观与家人设置"><CompanionAvatar variant={settings.avatar} name={settings.name}/><span>{settings.name}</span></button><button className="profile-entry" onClick={()=>{setExtrasOpen(false);setProfileOpen(true);}}>我的资料卡 <span aria-hidden="true">↗</span></button></header>{phone&&<CallBar name={settings.name} elapsed={(now-phone.started_at*1000)/1000} connecting={voice.phase==='connecting'} speaking={voice.speaking} loading={voice.loadingSpeech} processing={phonePendingIds.current.size>0||voice.phase==='finishing'} progress={voice.phase==='finishing'?'正在辨认刚才的话':phoneProgress} onFinish={voice.finish} onHangup={hangup}/>} {profileOpen&&<ProfileCard onClose={()=>setProfileOpen(false)} onSaved={()=>{setActiveAction('');void api<{actions:ActionPlan[]}>('/api/actions').then(d=>d.actions.forEach(updateAction)).catch(()=>{});}}/>}<main className={messages.length?'conversation':'welcome'} onClick={()=>setExtrasOpen(false)}>{!messages.length?<div className="greeting"><h1>{settings.name}</h1><Companion mood={mood} label={companionLabel} name={settings.name}/></div>:messages.map(m=><article className={'message '+m.role} key={m.id}>{m.call?<div className="phone-record"><Phone/><span>语音通话</span><time>{callDuration(m.call.duration_seconds||0)}</time></div>:<><div className="avatar" aria-hidden="true">{m.role==='assistant'?<CompanionAvatar variant={settings.avatar} name={settings.name}/>:'您'}</div><div className="message-body">{m.pending&&<MessageProgress text={m.progress||'正在回复'} stream={m.stream}/>} {!!m.images?.length&&<div className="message-images">{m.images.map(image=><a href={image.url} target="_blank" rel="noreferrer" key={image.id}><img src={image.url} alt="发送的图片"/></a>)}</div>}{m.text&&<p className="message-text">{m.text}</p>}{m.delivery&&<small className="delivery">{m.delivery}{m.delivery==='发送结果待核实'&&m.client_id&&<button type="button" onClick={()=>void transmit(m.text,m.client_id!,m.images)}>重试发送</button>}</small>}{m.speech_text&&<button className="speech-button" type="button" onClick={()=>voice.speaking||voice.loadingSpeech?stopPlayback():playReply(m.speech_text!)}>{voice.loadingSpeech?'停止生成语音':voice.speaking?'停止播报':'▶ 听小瑞说'}</button>}{m.stores&&<div className="store-list">{m.stores.map(s=><button className="store-card" key={s.code} onClick={()=>chooseStore(s)} disabled={!!busy||blocked||s.open===false||m.stores!==stores}><strong>{s.name}</strong><span>{s.address}{s.open===false?' · 暂未营业':''}</span><small>在这家取餐 →</small></button>)}</div>}{m.meals&&<div className="meal-grid">{m.meals.map((meal,i)=><div className="meal-card" key={meal.product_code}><div className="meal-image">{meal.image?<img src={meal.image} alt={meal.name} loading="lazy"/>:<span>暂无餐品图片</span>}<span className="letter">{String.fromCharCode(65+i)}</span></div><div className="meal-content"><h3>{meal.name}</h3><p>{meal.choices.join(' · ')}</p><strong className="meal-price">{yuan(meal.amount_cents)}</strong><small>到店自取 · 本次官方核价</small><button disabled={!!busy||blocked||m.meals!==meals} onClick={()=>selectMeal(meal,i)}>选 {String.fromCharCode(65+i)} 这份</button></div></div>)}</div>}{m.plan&&planCard(m.plan)}{m.actionPlan&&<ActionCard plan={m.actionPlan} active={m.actionPlan.id===activeAction&&chatPending===0} onChange={updateAction} onPrepared={p=>displayResponse({text:'请核对这份取消方案，尚未取消真实订单。',events:[{type:'action_plan',plan:p}]})} speak={playReply}/>} {m.role==='assistant'&&m.locationRequest&&<div className="card-actions"><button type="button" className="primary" disabled={locationBusy||!ready} onClick={async()=>{if(await requestLocation())await send('我已授权本次定位，请继续当前任务并核对实际地址；先不要提交交易。',activePhone.current?.id);}}>{locationBusy?'正在定位…':'授权定位并继续'}</button></div>}{m.choices&&<ChoiceCards choices={m.choices} disabled={!!busy||blocked||m.choices!==activeChoices} onChoose={prompt=>void send(prompt,activePhone.current?.id)}/>}</div></>}</article>)}{busy&&<div className="busy" role="status"><span className="spinner"/>{busy}…</div>}{error&&<div className="error" role="alert">{error}<button onClick={()=>setError('')}>知道了</button></div>}{!health?.mcd_configured&&health&&<p className="error">请先在本地 .env 配置麦当劳 Token。</p>}<div ref={end}/></main><div className="composer-wrap" ref={composerWrap}>{health?.read_only&&<p className="read-only-notice" role="status">只读预览 · 可查询，不能下单、叫车或支付</p>}<div className="companion-inline" aria-hidden="true"><Companion mood={mood} label={companionLabel} name={settings.name}/></div>{attachments.length>0&&<div className="attachment-tray">{attachments.map(image=><div key={image.id}><img src={image.url} alt="待发送图片"/><button type="button" aria-label="移除这张图片" onClick={()=>setAttachments(old=>old.filter(i=>i.id!==image.id))}>×</button></div>)}<span>图片将随下一条消息发送</span></div>}{uploading&&<div className="upload-progress" role="status">正在准备图片…</div>}
{locationStatus&&<div className="note" role="status">{locationStatus}</div>}<form className="composer wechat-composer" onSubmit={e=>{e.preventDefault();void send();}}>
<button type="button" className="mode-switch" disabled={!ready||voice.inCall} onClick={switchInput} aria-label={inputMode==='text'?'切换到语音输入':'切换到文字输入'} title={inputMode==='text'?'语音输入':'文字输入'}>{inputMode==='text'?<Mic/>:<Keyboard/>}</button>
{inputMode==='text'||voice.inCall?<><label className="sr-only" htmlFor="chat-input">发消息给小瑞</label><textarea id="chat-input" value={input} onFocus={()=>setExtrasOpen(false)} onChange={e=>setInput(e.target.value)} placeholder={voice.inCall?'通话中也可以打字补充':'发消息给小瑞'} rows={1} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/></>:<button type="button" className={'record-line '+(voice.recording?'is-listening':'')} disabled={!ready||voice.phase==='finishing'} onClick={()=>voice.recording?voice.stopRecording():void voice.startRecording()} aria-label={voice.phase==='finishing'?'正在识别语音':voice.recording?'停止录音并发送':'开始语音输入'}><span className="record-indicator">{voice.recording?<span className="stop-square"/>:<Mic/>}</span><span className="record-caption">{voice.phase==='finishing'?'正在识别…':voice.recording?(voice.phase==='connecting'?'正在连接…':voice.transcript||'正在听，点击停止并发送'):'点击说话'}</span></button>}
{messageCaptureActive&&<button type="button" className="cancel-recording" onClick={cancelVoiceMessage}>取消录音</button>}{(input.trim()||attachments.length>0)&&(inputMode==='text'||attachments.length>0)&&<button className="send" disabled={!ready||uploading} aria-label="发送消息">发送</button>}
<button type="button" className={'mode-switch plus-button '+(extrasOpen?'expanded':'')} disabled={!ready} aria-label={extrasOpen?'收起更多功能':'更多功能'} aria-expanded={extrasOpen} aria-controls="composer-extras" onClick={()=>{if(messageCaptureActive)cancelVoiceMessage();setExtrasOpen(old=>!old);}}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M7 12h10"/></svg></button>
<input ref={imageInput} type="file" hidden style={{display:'none'}} tabIndex={-1} accept="image/jpeg,image/png,image/webp" multiple aria-label="选择图片" onChange={e=>void selectImages(e.target.files)}/>
</form>{extrasOpen&&<div id="composer-extras" className="composer-extras" aria-label="更多功能"><button type="button" onClick={()=>{setExtrasOpen(false);void requestLocation();}}><span className="extra-icon">◎</span><span>定位</span></button><button type="button" disabled={uploading} onClick={()=>imageInput.current?.click()}><span className="extra-icon"><Photo/></span><span>图片</span></button><button type="button" aria-label={phone?'结束语音通话':'拨打语音电话'} onClick={()=>{setExtrasOpen(false);setInputMode('text');if(activePhone.current)hangup();else void startPhone();}}><span className="extra-icon"><Phone/></span><span>{voice.inCall?'结束通话':'语音通话'}</span></button></div>}</div><SettingsDialog inCall={!!phone} open={settingsOpen} onClose={()=>{setSettingsOpen(false);void api<Health>('/api/health').then(setHealth).catch(()=>{});}} settings={settings} onChange={updateSettings}/>{modal&&plan&&<div className="modal-backdrop"><div ref={dialog} className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><h2 id="confirm-title">最后确认一次</h2><p>{plan.summary.product_name}，共 {yuan(plan.amount_cents)}，在 {plan.summary.store_name} {plan.summary.take_way}。</p><p>确认后将创建真实待支付订单，支付仍在官方页面完成。</p><button onClick={()=>setModal(false)}>先不下单，返回看看</button><button className="primary" onClick={confirm} disabled={!!busy||!health?.order_execution_enabled}>确认下单 · {yuan(plan.amount_cents)}</button></div></div>}</div>

}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
