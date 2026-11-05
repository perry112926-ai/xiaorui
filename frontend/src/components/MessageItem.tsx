import React from 'react';
import {ActionCard} from '../ActionCard';
import {ChoiceCards} from '../ChoiceCards';
import {CompanionAvatar} from '../Companion';
import {callDuration} from '../CallBar';
import {CardHeading} from '../CardHeading';
import {Phone} from './Icons';
import {MessageProgress} from './MessageProgress';
import {StoreCards,MealCards} from './LegacyCandidates';
import type {Message} from '../chat/types';
import type {useAppController} from '../chat/useAppController';
type Controller=ReturnType<typeof useAppController>;
export type MessageActions=Pick<Controller,'settings'|'voice'|'stopPlayback'|'playReply'|'transmit'|'busy'|'blocked'|'stores'|'meals'|'chooseStore'|'selectMeal'|'activeAction'|'chatPending'|'updateAction'|'displayResponse'|'locationBusy'|'ready'|'requestLocation'|'send'|'activePhone'|'activeChoices'>;
export function MessageItem({message:m,c}:{message:Message;c:MessageActions}){
 const {settings,voice,stopPlayback,playReply,transmit,busy,blocked,stores,meals,chooseStore,selectMeal,activeAction,chatPending,updateAction,displayResponse,locationBusy,ready,requestLocation,send,activePhone,activeChoices}=c;
 return <article className={'message '+m.role}>
  {m.call?<div className="phone-record"><Phone/><span>语音通话</span><time>{callDuration(m.call.duration_seconds||0)}</time></div>:<>
   <div className="avatar" aria-hidden="true">{m.role==='assistant'?<CompanionAvatar variant={settings.avatar} name={settings.name}/>:'您'}</div>
   <div className="message-body">
    {m.pending&&<MessageProgress text={m.progress||'正在回复'} stream={m.stream}/>}
    {!!m.images?.length&&<div className="message-images">{m.images.map(image=><a href={image.url} target="_blank" rel="noreferrer" key={image.id}><img src={image.url} alt="发送的图片"/></a>)}</div>}
    {m.text&&<p className="message-text">{m.text}</p>}
    {m.delivery&&<small className="delivery">{m.delivery}{m.delivery==='发送结果待核实'&&m.client_id&&<button type="button" onClick={()=>void transmit(m.text,m.client_id!,m.images)}>重试发送</button>}</small>}
    {m.speech_text&&<button className="speech-button" type="button" onClick={()=>voice.speaking||voice.loadingSpeech?stopPlayback():playReply(m.speech_text!)}>{voice.loadingSpeech?'停止生成语音':voice.speaking?'停止播报':'▶ 听小瑞说'}</button>}
    {m.stores&&<StoreCards stores={m.stores} disabled={!!busy||blocked||m.stores!==stores} onChoose={chooseStore}/>}
    {m.meals&&<MealCards meals={m.meals} disabled={!!busy||blocked||m.meals!==meals} onChoose={selectMeal}/>}
    {m.actionPlan&&<ActionCard plan={m.actionPlan} active={m.actionPlan.id===activeAction&&chatPending===0} onChange={updateAction} onPrepared={p=>displayResponse({text:'请核对这份取消方案，尚未取消真实订单。',events:[{type:'action_plan',plan:p}]})} speak={playReply}/>}
    {m.role==='assistant'&&m.locationRequest&&<section className="choice-panel location-panel">
     <CardHeading icon="pin" title="提供本次位置" description="授权后核对附近地址，也可以直接告诉我地标。"/>
     <div className="card-actions"><button type="button" className="primary" disabled={locationBusy||!ready} onClick={async()=>{if(await requestLocation())await send('我已授权本次定位，请继续当前任务并核对实际地址；先不要提交交易。',activePhone.current?.id);}}>{locationBusy?'正在定位…':'授权定位并继续'}</button></div>
    </section>}
    {m.choices&&<ChoiceCards choices={m.choices} disabled={!!busy||blocked||m.choices!==activeChoices} onChoose={prompt=>void send(prompt,activePhone.current?.id)}/>}
   </div>
  </>}
 </article>;
}
