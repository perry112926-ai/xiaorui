import {useEffect,useRef,useState} from 'react';
import type {ActionPlan} from '../ActionCard';
import type {ChoiceCard} from '../ChoiceCards';
import type {PhoneCall} from '../CallBar';
import {officialPaymentUrl,openOfficialPayment} from '../payment';
import {useVoice} from '../useVoice';
import {companionMood} from '../Companion';
import {useCompanionSettings} from '../SettingsDialog';
import {api} from './api';
import {useChat} from './useChat';
import {useContact} from './useContact';
import {usePhone} from './usePhone';
import {useComposer} from './useComposer';
import {useLocation} from './useLocation';
import {parseContactEvent,unreachable} from './contactEvents';
import type {ContactEvent} from './contactEvents';
import {legacyAction} from './types';
import type {Message,Health,ChatResponse,ChatEvent,ImageMessage,Store,Meal} from './types';
export function useAppController(){

 const [health,setHealth]=useState<Health>();
 const chat=useChat();const {messages,setMessages,add,replacePending,updateProgress,pendingIds}=chat;
 const [stores,setStores]=useState<Store[]>([]),[meals,setMeals]=useState<Meal[]>([]);
 const [busy,setBusy]=useState('正在恢复对话'),[error,setError]=useState(''),[ready,setReady]=useState(false),[chatPending,setChatPending]=useState(0);
 const [now,setNow]=useState(Date.now());const end=useRef<HTMLDivElement>(null);
 const interrupted=useRef(false),autoplayAllowed=useRef(true);
 const {input,setInput,inputMode,setInputMode,extrasOpen,setExtrasOpen,attachments,setAttachments,uploading,imageInput,composerWrap,inflightSends,switchInput,selectImages}=useComposer({voice:()=>voice,cancelCapture:cancelVoiceMessage,setError});
 const [profileOpen,setProfileOpen]=useState(false);
 const {locationStatus,locationBusy,locationFresh,requestLocation}=useLocation();
 const [activeAction,setActiveAction]=useState('');
 const paymentOpened=useRef(new Set<string>());
 const [activeChoices,setActiveChoices]=useState<ChoiceCard[]>();
 const {settings,updateSettings}=useCompanionSettings();const [settingsOpen,setSettingsOpen]=useState(false);
 const [voiceNotice,setVoiceNotice]=useState('');
 const voice=useVoice(text=>{void send(text,activePhone.current?.id)},text=>{setError(text==='请先配置豆包语音服务。'?'语音还没接通，请家人帮忙完成设置。您可以继续打字。':text);},()=>{autoplayAllowed.current=false;interrupted.current=true;});
 const {phone,activePhone,phoneProgress,setPhoneProgress,phonePendingIds,hangup,startPhone}=usePhone(voice,{setError,setNotice:setVoiceNotice,showCall,autoplay:autoplayAllowed,interrupted,closeExtras:()=>setExtrasOpen(false)});
 const messageCaptureActive=!voice.inCall&&voice.phase!=='idle';
 useEffect(()=>{document.title=`${settings.name} · 您的生活小帮手`;},[settings.name]);
 function receive(e:ContactEvent,replay=false){
  switch(e.type){
   case 'speech_ready':setMessages(old=>old.map(m=>m.task_id===e.task_id?{...m,speech_text:e.speech_text}:m));return;
   case 'call_ended':showCall(e.call);return;
   case 'accepted':
    if(!chat.accept(e))return;
    if(e.call_id&&e.call_id===activePhone.current?.id)phonePendingIds.current.add(e.message_id);
    break;
   case 'started':
    interrupted.current=false;
    if(e.call_id){if(e.call_id===activePhone.current?.id)setPhoneProgress('正在听，也在帮您处理');}
    else updateProgress(e.message_ids||[e.message_id],{progress:'正在理解您的消息'});
    break;
   case 'delta':
    if(!interrupted.current&&!e.call_id)setMessages(old=>old.map(m=>m.pending&&m.message_id===e.message_id?{...m,stream:((m.stream||'')+e.text).slice(-12000),progress:'正在回复'}:m));
    break;
   case 'progress':
    if(e.call_id){if(e.call_id===activePhone.current?.id)setPhoneProgress(e.text);}else updateProgress([e.message_id],{progress:e.text});
    break;
   case 'completed':case 'failed':{
    if(!chat.settle(e))return;
    for(const id of e.message_ids||[e.message_id]){pendingIds.current.delete(id);phonePendingIds.current.delete(id);}
    if(e.call_id===activePhone.current?.id)setPhoneProgress('');
   if(e.type==='failed'){const message=e.text==='请先配置豆包文本模型，再开始对话。'?'小瑞还没接通对话服务，请家人帮忙完成设置。':e.text;if(!e.call_id)replacePending([{role:'assistant',text:message,speech_text:message}],e.message_ids||[e.message_id]);else if(!replay)setError(message);if(!replay&&(e.call_id?e.call_id===activePhone.current?.id&&voice.inCall:!activePhone.current&&(voice.inCall||inputMode==='voice'))&&!voice.recording&&!messageCaptureActive&&!interrupted.current&&autoplayAllowed.current)void voice.speak(message);}
   else if(!e.superseded){const d=e.response;if(d.conversation_reset){setMessages([]);setStores([]);setMeals([]);setActiveAction('');setActiveChoices(undefined);}displayResponse(d,!!e.call_id,e.message_ids||[e.message_id]);if(!replay&&(e.call_id?e.call_id===activePhone.current?.id&&voice.inCall:!activePhone.current&&(voice.inCall||inputMode==='voice'))&&!voice.recording&&!messageCaptureActive&&!interrupted.current&&autoplayAllowed.current&&d.speech_text)void voice.speak(d.speech_text);}
   if(e.superseded&&!e.call_id)replacePending([],e.message_ids||[e.message_id]);
   if(!replay&&e.type==='completed'&&!e.superseded){const paymentEvent=e.response.events.find((event):event is Extract<ChatEvent,{type:'action_plan'}>=>event.type==='action_plan'&&!!officialPaymentUrl(event.plan));const paidPlan=paymentEvent?.plan;if(paidPlan&&!paymentOpened.current.has(paidPlan.id)){paymentOpened.current.add(paidPlan.id);void (async()=>{if(activePhone.current)await hangup();openOfficialPayment(paidPlan);})();}}
   if(!replay)void api<{actions:ActionPlan[]}>('/api/actions').then(d=>d.actions.forEach(updateAction)).catch(()=>{});
   break;
   }
   default:unreachable(e);
  }
  setChatPending(pendingIds.current.size);
 }
 const receiver=useRef(receive);receiver.current=receive;
 useContact({receive:(event,replay)=>receiver.current(event,replay),setHealth,setPending:setChatPending,
  onReady:()=>{setReady(true);setBusy('');},onError:message=>{setError(message);setBusy('');},
  onReconnect:()=>{setMessages(old=>old.map(m=>m.pending?{...m,progress:'消息连接正在恢复，已收到的消息仍会继续处理'}:m));if(activePhone.current)setPhoneProgress('消息连接正在恢复');},
  onConnected:()=>setPhoneProgress(''),showCall,restore:message=>{if(message.role==='user')add({role:'user',text:message.text});else displayResponse(message);},updateAction});
 useEffect(()=>{const t=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(t);},[]);
 useEffect(()=>{const element=composerWrap.current;if(!element)return;const measure=()=>document.documentElement.style.setProperty('--composer-height',`${element.getBoundingClientRect().height}px`);measure();const observer=new ResizeObserver(measure);observer.observe(element);return()=>{observer.disconnect();document.documentElement.style.removeProperty('--composer-height');};},[]);
 useEffect(()=>{end.current?.scrollIntoView({behavior:'smooth',block:'end'})},[messages,busy]);
 useEffect(()=>{if(!extrasOpen)return;const close=(e:KeyboardEvent)=>{if(e.key==='Escape')setExtrasOpen(false);};document.addEventListener('keydown',close);return()=>document.removeEventListener('keydown',close);},[extrasOpen]);
 const blocked=messages.some(m=>m.actionPlan?.id===activeAction&&['unknown','submitting','rechecking'].includes(m.actionPlan.status));
 function updateAction(p:ActionPlan){setMessages(old=>old.map(m=>m.actionPlan?.id===p.id?{...m,actionPlan:p}:m));}
 function displayResponse(d:ChatResponse,phoneTurn=false,replyIds:string[]=[]){
   const incoming:Omit<Message,'id'>[]=[];
   const response:Omit<Message,'id'>={task_id:d.task_id,role:'assistant',text:d.text,speech_text:d.speech_text,locationRequest:/定位|上车.*位置/.test(d.text)};
   const events=(d.events??[]).filter(event=>['stores','meals','plan','action_plan','service_choices','location_request','flight_result'].includes(event.type));
   if(!phoneTurn&&!events.length&&(d.text||d.speech_text))incoming.push(response);

   events.forEach((event,i)=>{
    const message:Omit<Message,'id'>={task_id:i===0?d.task_id:undefined,role:'assistant',text:!phoneTurn&&i===0?d.text:'',speech_text:!phoneTurn&&i===0?d.speech_text:undefined,locationRequest:event.type==='location_request'||(i===0&&/定位|上车.*位置/.test(d.text))};
    if(event.type==='stores'){setStores(event.stores);setMeals([]);message.stores=event.stores}
    if(event.type==='meals'){setMeals(event.meals);message.meals=event.meals}
    if(event.type==='plan'){const p=legacyAction(event.plan);updateAction(p);setActiveAction(p.id);message.actionPlan=p;}
    if(event.type==='action_plan'){updateAction(event.plan);setActiveAction(event.plan.id);message.actionPlan=event.plan}
    if(event.type==='service_choices'){message.choices=event.choices;setActiveChoices(event.choices)}
    if(event.type==='flight_result')message.flightResult=event.data;
    incoming.push(message);
   });
   replacePending(incoming,replyIds);
 }
 async function send(spoken?:string,phoneId?:string){
  const outgoingImages=spoken===undefined?attachments:[];const text=(spoken??input).trim()||(outgoingImages.length?'请看看这张图片。':'');if(!text||!ready||uploading)return;
  const submissionKey=JSON.stringify([phoneId||'chat',text,outgoingImages.map(image=>image.id)]);if(inflightSends.current.has(submissionKey))return;inflightSends.current.add(submissionKey);
  try{
  if(outgoingImages.length)setAttachments([]);setExtrasOpen(false);
  if(phoneId||!activePhone.current){if(!phoneId)voice.stopSpeech();autoplayAllowed.current=true;interrupted.current=true;}setVoiceNotice('');if(spoken===undefined)setInput('');setActiveChoices(undefined);setActiveAction('');
  const client_id=crypto.randomUUID();if(!phoneId){add({role:'user',text,client_id,images:outgoingImages,delivery:'正在发送'});add({role:'assistant',text:'',pending:true,replyTo:client_id,progress:'正在发送消息…'});}
  if(/打车|叫车|我在哪|我的位置|当前位置|定位/.test(text)&&!/^确认/.test(text)&&Date.now()-locationFresh.current>110000)await requestLocation();
  await transmit(text,client_id,outgoingImages,phoneId);
  }finally{inflightSends.current.delete(submissionKey);}
 }
 async function transmit(text:string,client_id:string,images:ImageMessage[]=[],phoneId?:string){
  try{const receipt=await api<{event?:unknown}>('/api/contact/messages',{text,client_id,image_ids:images.map(i=>i.id),reply_mode:phoneId||inputMode==='voice'?'speech':'text',...(phoneId?{call_id:phoneId}:{})});if(receipt.event)receiver.current(parseContactEvent(receipt.event));}
  catch(e){setMessages(old=>old.filter(m=>!m.pending||m.replyTo!==client_id).map(m=>m.client_id===client_id&&m.delivery!=='已送达'?{...m,delivery:'发送结果待核实'}:m));setError(e instanceof Error?e.message:'连接已断开，可以点击消息旁重试；不会重复提交同一条消息。');if(phoneId&&phoneId===activePhone.current?.id)void voice.speak('刚才那句话没有确认发送成功，请您稍后再说一次。');}
 }
 function playReply(text:string){autoplayAllowed.current=false;setVoiceNotice('');void voice.speak(text);}
 function stopPlayback(){autoplayAllowed.current=false;voice.stopSpeech();setVoiceNotice('已停止播报，文字消息仍然保留。');}
 function cancelVoiceMessage(){autoplayAllowed.current=false;interrupted.current=true;voice.cancelRecording();setVoiceNotice('已取消这段录音，没有发送。');}
 function showCall(call:PhoneCall){chat.showCall(call);}
 async function chooseStore(s:Store){await send(`选择门店：${s.name}。`,activePhone.current?.id)}
 async function selectMeal(m:Meal,index:number){await send(`选第${index+1}份套餐，${m.name}。`,activePhone.current?.id)}
 const taskProgress=phonePendingIds.current.size?phoneProgress:(messages.filter(message=>message.pending).at(-1)?.progress||'');
 const mood=companionMood({phase:voice.phase,recording:voice.recording,speaking:voice.speaking,loadingSpeech:voice.loadingSpeech,pending:Math.max(chatPending,messages.filter(message=>message.pending).length,busy?1:0),context:taskProgress||busy});
 const companionLabel={idle:'安静陪伴',listening:'正在倾听',working:'正在思考',speaking:'正在说话',taxi:'正在处理出行查询',dining:'正在处理餐饮查询'}[mood];
 function openSettings(){if(messageCaptureActive)cancelVoiceMessage();if(!voice.inCall)stopPlayback();setSettingsOpen(true);}
 function profileSaved(){setActiveAction('');void api<{actions:ActionPlan[]}>('/api/actions').then(d=>d.actions.forEach(updateAction)).catch(()=>{});}
 function closeSettings(){setSettingsOpen(false);void api<Health>('/api/health').then(setHealth).catch(()=>{});}
 return {health,setHealth,profileSaved,closeSettings,messages,input,setInput,stores,meals,busy,error,setError,ready,chatPending,now,end,blocked,
  profileOpen,setProfileOpen,activeAction,setActiveAction,activeChoices,phone,activePhone,phoneProgress,phonePendingIds,
  settings,updateSettings,settingsOpen,setSettingsOpen,voice,voiceNotice,autoplayAllowed,messageCaptureActive,
  inputMode,setInputMode,extrasOpen,setExtrasOpen,attachments,setAttachments,uploading,imageInput,composerWrap,
  locationStatus,locationBusy,requestLocation,mood,companionLabel,openSettings,send,transmit,selectImages,
  playReply,stopPlayback,cancelVoiceMessage,hangup,startPhone,switchInput,chooseStore,selectMeal,displayResponse,updateAction};
}
