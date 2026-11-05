import type {ChatEvent,ChatResponse,ImageMessage} from './types';
import type {PhoneCall} from '../CallBar';
import type {ActionPlan} from '../ActionCard';
type Run={message_id:string;message_ids?:string[];call_id?:string;cursor?:number};
export type ContactEvent=
 | ({type:'accepted';client_id:string;text:string;images?:ImageMessage[];ack_text?:string}&Run)
 | ({type:'started'}&Run)
 | ({type:'delta'|'progress';text:string;stage?:string}&Run)
 | ({type:'completed';response:ChatResponse;superseded?:boolean}&Run)
 | ({type:'failed';text:string;superseded?:boolean}&Run)
 | {type:'speech_ready';task_id:string;speech_text:string;speech_source?:string;cursor?:number}
 | {type:'call_ended';call:PhoneCall;cursor?:number};
const object=(v:unknown):v is Record<string,unknown>=>typeof v==='object'&&v!==null&&!Array.isArray(v);
const string=(v:unknown):v is string=>typeof v==='string';
const number=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
const strings=(v:unknown):v is string[]=>Array.isArray(v)&&v.every(string);
const optional=(v:unknown,check:(v:unknown)=>boolean)=>v===undefined||check(v);
function isCall(v:unknown):v is PhoneCall{return object(v)&&string(v.id)&&number(v.started_at)&&optional(v.duration_seconds,number);}
function isImage(v:unknown):v is ImageMessage{return object(v)&&string(v.id)&&string(v.url)&&/^\/api\/contact\/images\/[A-Za-z0-9_-]+$/.test(v.url);}
function isPlan(v:unknown):v is ActionPlan{
 return object(v)&&string(v.id)&&string(v.status)&&number(v.version)&&Number.isSafeInteger(v.amount_cents)&&Number(v.amount_cents)>=0&&object(v.summary)&&string(v.confirmation_token)&&number(v.expires_at)
  &&optional(v.provider,x=>x==='mcd'||x==='luckin'||x==='didi')&&optional(v.action,x=>x==='create'||x==='cancel'||x==='create_address');
}
function isChatEvent(v:unknown):v is ChatEvent{
 if(!object(v)||!string(v.type))return false;
 switch(v.type){
  case 'location_request':return true;
  case 'plan':return isPlan(v.plan);
  case 'action_plan':return isPlan(v.plan)&&object(v.plan)&&['mcd','luckin','didi'].includes(String(v.plan.provider))&&['create','cancel','create_address'].includes(String(v.plan.action))&&typeof v.plan.execution_enabled==='boolean'&&string(v.plan.confirmation_text);
  case 'stores':return Array.isArray(v.stores)&&v.stores.every(x=>object(x)&&string(x.code)&&string(x.name)&&string(x.address));
  case 'meals':return Array.isArray(v.meals)&&v.meals.every(x=>object(x)&&string(x.name)&&string(x.product_code)&&Number.isSafeInteger(x.amount_cents)&&strings(x.choices));
  case 'service_choices':return Array.isArray(v.choices)&&v.choices.every(x=>object(x)&&string(x.label)&&string(x.prompt)&&optional(x.detail,string)&&optional(x.contents,strings)&&optional(x.available,v=>typeof v==='boolean'));
  case 'flight_result':return object(v.data)&&(Array.isArray(v.data.flights)||string(v.data.error));
  case 'service_result':return string(v.provider)&&'data' in v;
  case 'query_result':return string(v.provider)&&string(v.tool)&&typeof v.success==='boolean'&&string(v.source)&&'data' in v;
  default:return false;
 }
}
export function isChatResponse(v:unknown):v is ChatResponse{
 return object(v)&&string(v.text)&&optional(v.speech_text,string)&&Array.isArray(v.events)&&v.events.every(isChatEvent)&&optional(v.task_id,string);
}
export function parseContactEvent(v:unknown):ContactEvent{
 if(!object(v)||!string(v.type)||!optional(v.cursor,number))throw Error('消息事件格式不正确。');
 if(v.type==='speech_ready'){
  if(string(v.task_id)&&string(v.speech_text))return v as ContactEvent;
 }else if(v.type==='call_ended'){
  if(isCall(v.call))return v as ContactEvent;
 }else if(string(v.message_id)&&optional(v.message_ids,strings)&&optional(v.call_id,string)){
  switch(v.type){
   case 'accepted':if(string(v.client_id)&&string(v.text)&&optional(v.images,x=>Array.isArray(x)&&x.every(isImage))&&optional(v.ack_text,string))return v as ContactEvent;break;
   case 'started':return v as ContactEvent;
   case 'delta':case 'progress':case 'failed':if(string(v.text))return v as ContactEvent;break;
   case 'completed':if(isChatResponse(v.response)&&optional(v.superseded,x=>typeof x==='boolean'))return v as ContactEvent;break;
  }
 }
 throw Error('消息事件格式不正确。');
}
export function unreachable(value:never):never{throw Error('未知消息事件：'+String(value));}
