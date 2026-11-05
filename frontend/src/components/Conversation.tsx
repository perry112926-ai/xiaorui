import React from 'react';
import {Companion} from '../Companion';
import {MessageItem} from './MessageItem';
import type {MessageActions} from './MessageItem';
import type {useAppController} from '../chat/useAppController';
type Controller=ReturnType<typeof useAppController>;
type Props=MessageActions&Pick<Controller,'messages'|'setExtrasOpen'|'mood'|'companionLabel'|'error'|'setError'|'health'|'end'>;
export function Conversation(c:Props){
 const {messages,setExtrasOpen,settings,mood,companionLabel,busy,error,setError,health,end}=c;
 return <main className={messages.length?'conversation':'welcome'} onClick={()=>setExtrasOpen(false)}>
  {!messages.length?<div className="greeting"><h1>{settings.name}</h1><Companion mood={mood} label={companionLabel} name={settings.name}/></div>:messages.map(message=><MessageItem key={message.id} message={message} c={c}/>)}
  {busy&&<div className="busy" role="status"><span className="spinner"/>{busy}…</div>}
  {error&&<div className="error" role="alert">{error}<button onClick={()=>setError('')}>知道了</button></div>}
  {!health?.mcd_configured&&health&&<p className="error">请先在家人设置中配置麦当劳服务。</p>}
  <div ref={end}/>
 </main>;
}
