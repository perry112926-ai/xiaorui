import {useReducer,useRef} from 'react';
import type {Dispatch,SetStateAction} from 'react';
import type {PhoneCall} from '../CallBar';
import type {Message} from './types';
import type {ContactEvent} from './contactEvents';

type Action=
 | {type:'call';call:PhoneCall;id:number}
 | {type:'update';update:SetStateAction<Message[]>}
 | {type:'append';message:Message}
 | {type:'replace';messages:Message[];ids:string[]}
 | {type:'progress';ids:string[];patch:Partial<Message>}
 | {type:'accept';event:Extract<ContactEvent,{type:'accepted'}>;userId:number;ackId:number;progressId:number};
export function chatReducer(state:Message[],action:Action):Message[]{
 switch(action.type){
  case 'call':return state.some(m=>m.call?.id===action.call.id)?state.map(m=>m.call?.id===action.call.id?{...m,call:action.call}:m):[...state,{id:action.id,role:'assistant',text:'',call:action.call}];
  case 'update':return typeof action.update==='function'?action.update(state):action.update;
  case 'append':return [...state,action.message];
  case 'progress':return state.map(m=>m.pending&&action.ids.includes(m.message_id||'')?{...m,...action.patch}:m);
  case 'replace':{
   const at=state.reduce((last,m,i)=>m.pending&&action.ids.includes(m.message_id||'')?i:last,-1);
   if(at<0)return [...state,...action.messages];
   const keep=(m:Message)=>!m.pending||!action.ids.includes(m.message_id||'');
   return [...state.slice(0,at).filter(keep),...action.messages,...state.slice(at).filter(keep)];
  }
  case 'accept':{
   const e=action.event;
   let next=state.some(m=>m.client_id===e.client_id)?state.map(m=>m.client_id===e.client_id?{...m,message_id:e.message_id,delivery:'已送达',images:e.images}:m):[...state,{id:action.userId,role:'user' as const,text:e.text,images:e.images,client_id:e.client_id,message_id:e.message_id,delivery:'已送达'}];
   if(e.ack_text){const at=next.findIndex(m=>m.client_id===e.client_id);const ack:Message={id:action.ackId,role:'assistant',text:e.ack_text,ackFor:e.message_id};next=at<0?[...next,ack]:[...next.slice(0,at+1),ack,...next.slice(at+1)];}
   const existing=next.find(m=>m.pending&&m.replyTo===e.client_id);
   if(existing)return next.map(m=>m===existing?{...m,message_id:e.message_id,progress:'消息已收到，正在准备回复'}:m);
   const at=next.reduce((last,m,i)=>m.client_id===e.client_id||m.ackFor===e.message_id?i:last,-1);
   const progress:Message={id:action.progressId,role:'assistant',text:'',pending:true,replyTo:e.client_id,message_id:e.message_id,progress:'消息已收到，正在准备回复'};
   return at<0?[...next,progress]:[...next.slice(0,at+1),progress,...next.slice(at+1)];
  }
 }
}
export function useChat(){
 const [messages,dispatch]=useReducer(chatReducer,[]);
 const terminalIds=useRef(new Set<string>());
 const counter=useRef(0),pendingIds=useRef(new Set<string>()),acceptedIds=useRef(new Set<string>());
 const setMessages:Dispatch<SetStateAction<Message[]>>=update=>dispatch({type:'update',update});
 function add(message:Omit<Message,'id'>){dispatch({type:'append',message:{...message,id:++counter.current}});}
 function replacePending(incoming:Omit<Message,'id'>[],ids:string[]=[]){dispatch({type:'replace',messages:incoming.map(m=>({...m,id:++counter.current})),ids});}
 function updateProgress(ids:string[],patch:Partial<Message>){dispatch({type:'progress',ids,patch});}
 function accept(e:Extract<ContactEvent,{type:'accepted'}>){
  if(acceptedIds.current.has(e.message_id))return false;
  acceptedIds.current.add(e.message_id);pendingIds.current.add(e.message_id);
  if(!e.call_id)dispatch({type:'accept',event:e,userId:++counter.current,ackId:++counter.current,progressId:++counter.current});
  return true;
 }
 function showCall(call:PhoneCall){dispatch({type:'call',call,id:++counter.current});}
 function settle(event:Extract<ContactEvent,{type:'completed'|'failed'}>){
  const ids=event.message_ids??[event.message_id];
  if(ids.every(id=>terminalIds.current.has(id)))return false;
  for(const id of ids)terminalIds.current.add(id);return true;
 }
 return {settle,showCall,messages,setMessages,add,replacePending,updateProgress,accept,pendingIds};
}
