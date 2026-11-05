import React from 'react';
import {Companion} from '../Companion';
import {Mic,Keyboard,Photo,Phone} from './Icons';
import type {useAppController} from '../chat/useAppController';
export type AppController=ReturnType<typeof useAppController>;
export function Composer(c:AppController){
 const {health,input,setInput,ready,phone,activePhone,settings,voice,messageCaptureActive,inputMode,setInputMode,extrasOpen,setExtrasOpen,attachments,setAttachments,uploading,imageInput,composerWrap,locationStatus,requestLocation,mood,companionLabel,send,selectImages,cancelVoiceMessage,hangup,startPhone,switchInput}=c;
 return <div className="composer-wrap" ref={composerWrap}>{health?.read_only&&<p className="read-only-notice" role="status">只读预览 · 可查询，不能下单、叫车或支付</p>}<div className="companion-inline" aria-hidden="true">
<Companion mood={mood} label={companionLabel} name={settings.name}/>
</div>{attachments.length>0&&<div className="attachment-tray">{attachments.map(image=>
<div key={image.id}>
<img src={image.url} alt="待发送图片"/>
<button type="button" aria-label="移除这张图片" onClick={()=>setAttachments(old=>old.filter(i=>i.id!==image.id))}>×</button>
</div>)}<span>图片将随下一条消息发送</span>
</div>}{uploading&&<div className="upload-progress" role="status">正在准备图片…</div>}
{locationStatus&&<div className="note" role="status">{locationStatus}</div>}<form className="composer wechat-composer" onSubmit={e=>{e.preventDefault();void send();}}>
<button type="button" className="mode-switch" disabled={!ready||voice.inCall} onClick={switchInput} aria-label={inputMode==='text'?'切换到语音输入':'切换到文字输入'} title={inputMode==='text'?'语音输入':'文字输入'}>{inputMode==='text'?<Mic/>:<Keyboard/>}</button>
{inputMode==='text'||voice.inCall?<>
<label className="sr-only" htmlFor="chat-input">发消息给小瑞</label>
<textarea id="chat-input" value={input} onFocus={()=>setExtrasOpen(false)} onChange={e=>setInput(e.target.value)} placeholder={voice.inCall?'通话中也可以打字补充':'发消息给小瑞'} rows={1} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send();}}}/>
</>:<button type="button" className={'record-line '+(voice.recording?'is-listening':'')} disabled={!ready||voice.phase==='finishing'} onClick={()=>voice.recording?voice.stopRecording():void voice.startRecording()} aria-label={voice.phase==='finishing'?'正在识别语音':voice.recording?'停止录音并发送':'开始语音输入'}>
<span className="record-indicator">{voice.recording?<span className="stop-square"/>:<Mic/>}</span>
<span className="record-caption">{voice.phase==='finishing'?'正在识别…':voice.recording?(voice.phase==='connecting'?'正在连接…':voice.transcript||'正在听，点击停止并发送'):'点击说话'}</span>
</button>}
{messageCaptureActive&&<button type="button" className="cancel-recording" onClick={cancelVoiceMessage}>取消录音</button>}{(input.trim()||attachments.length>0)&&(inputMode==='text'||attachments.length>0)&&<button className="send" disabled={!ready||uploading} aria-label="发送消息">发送</button>}
<button type="button" className={'mode-switch plus-button '+(extrasOpen?'expanded':'')} disabled={!ready} aria-label={extrasOpen?'收起更多功能':'更多功能'} aria-expanded={extrasOpen} aria-controls="composer-extras" onClick={()=>{if(messageCaptureActive)cancelVoiceMessage();setExtrasOpen(old=>!old);}}>
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
<circle cx="12" cy="12" r="9"/>
<path d="M12 7v10M7 12h10"/>
</svg>
</button>
<input ref={imageInput} type="file" hidden style={{display:'none'}} tabIndex={-1} accept="image/jpeg,image/png,image/webp" multiple aria-label="选择图片" onChange={e=>void selectImages(e.target.files)}/>
</form>{extrasOpen&&<div id="composer-extras" className="composer-extras" aria-label="更多功能">
<button type="button" onClick={()=>{setExtrasOpen(false);void requestLocation();}}>
<span className="extra-icon">◎</span>
<span>定位</span>
</button>
<button type="button" disabled={uploading} onClick={()=>imageInput.current?.click()}>
<span className="extra-icon">
<Photo/>
</span>
<span>图片</span>
</button>
<button type="button" aria-label={phone?'结束语音通话':'拨打语音电话'} onClick={()=>{setExtrasOpen(false);setInputMode('text');if(activePhone.current)hangup();else void startPhone();}}>
<span className="extra-icon">
<Phone/>
</span>
<span>{voice.inCall?'结束通话':'语音通话'}</span>
</button>
</div>}</div>;
}
