import {useEffect,useRef} from 'react';
import {api} from './api';
import {parseContactEvent,isChatResponse} from './contactEvents';
import type {ContactEvent} from './contactEvents';
import type {Health,ChatResponse} from './types';
import type {ActionPlan} from '../ActionCard';
import type {PhoneCall} from '../CallBar';
export type ContactHandlers={receive:(event:ContactEvent,replay?:boolean)=>void;setHealth:(h:Health)=>void;setPending:(n:number)=>void;onReady:()=>void;onError:(message:string)=>void;onReconnect:()=>void;onConnected:()=>void;showCall:(call:PhoneCall)=>void;restore:(message:({role:'user'|'assistant'}&ChatResponse))=>void;updateAction:(plan:ActionPlan)=>void};
export function useContact(handlers:ContactHandlers){
 const latest=useRef(handlers);latest.current=handlers;
 useEffect(()=>{
  let alive=true,source:EventSource|undefined;
  const h=()=>latest.current;
  void (async()=>{
   try{
    const health=await api<Health>('/api/health');
    const state=await api<{events:unknown[];cursor:number;pending:number;active_call?:PhoneCall}>('/api/contact/state');
    if(!alive)return;
    if(!Array.isArray(state.events)||!Number.isSafeInteger(state.cursor)||!Number.isSafeInteger(state.pending))throw Error('消息记录格式不正确。');
    h().setHealth(health);
    if(state.active_call)void api<PhoneCall>(`/api/contact/calls/${state.active_call.id}/end`,{}).then(call=>{if(alive)h().showCall(call);}).catch(()=>{if(alive)h().onError('上次通话记录暂未同步，请稍后刷新。');});
    if(state.events.length){for(const event of state.events){try{h().receive(parseContactEvent(event),true);}catch{h().onError('部分历史消息格式不正确，已跳过；其余记录仍可使用。');}}}
    else{
     const history=await api<{messages:unknown[]}>('/api/chat/history');
     if(!alive)return;
     for(const message of history.messages){
      if(typeof message!=='object'||message===null||!('role' in message)||!('text' in message)||typeof message.text!=='string')throw Error('对话记录格式不正确。');
      if(message.role==='user')h().restore({role:'user',text:message.text,events:[]});
      else if(message.role==='assistant'&&isChatResponse(message))h().restore({...message,role:'assistant'});
     }
    }
    if(!alive)return;h().setPending(state.pending);h().onReady();
    source=new EventSource(`/api/contact/events?after=${state.cursor}`);
    source.onmessage=e=>{if(!alive)return;try{h().receive(parseContactEvent(JSON.parse(e.data)));}catch{h().onError('消息显示异常，请刷新恢复记录。');}};
    source.onerror=()=>{if(alive)h().onReconnect();};source.onopen=()=>{if(alive)h().onConnected();};
    const actions=await api<{actions:ActionPlan[]}>('/api/actions');if(alive)actions.actions.forEach(plan=>h().updateAction(plan));
   }catch{if(alive)h().onError('未能连接小瑞，请检查服务后刷新页面。');}
  })();
  return()=>{alive=false;source?.close();};
 },[]);
}
