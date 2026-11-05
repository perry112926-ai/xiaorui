import React from 'react';
import {ProfileCard} from '../ProfileCard';
import {CallBar} from '../CallBar';
import {CompanionAvatar} from '../Companion';
import {SettingsDialog} from '../SettingsDialog';
import type {useAppController} from '../chat/useAppController';
export type AppController=ReturnType<typeof useAppController>;
import {Conversation} from './Conversation';
import {Composer} from './Composer';
export function AppView(c:AppController){
 const {health,profileSaved,closeSettings,messages,now,profileOpen,setProfileOpen,phone,phoneProgress,phonePendingIds,settings,updateSettings,settingsOpen,voice,setExtrasOpen,openSettings,hangup}=c;
 return <div className={(messages.length?'app':'app empty')+(phone?' phone-active':'')}>
<header>
<button className="brand companion-settings-entry" type="button" onClick={openSettings} aria-label="助手外观与家人设置">
<CompanionAvatar variant={settings.avatar} name={settings.name}/>
<span>{settings.name}</span>
</button>
<button className="profile-entry" onClick={()=>{setExtrasOpen(false);setProfileOpen(true);}}>我的资料卡 <span aria-hidden="true">↗</span>
</button>
</header>{phone&&<CallBar name={settings.name} elapsed={(now-phone.started_at*1000)/1000} connecting={voice.phase==='connecting'} speaking={voice.speaking} loading={voice.loadingSpeech} processing={phonePendingIds.current.size>0||voice.phase==='finishing'} progress={voice.phase==='finishing'?'正在辨认刚才的话':phoneProgress} onFinish={voice.finish} onHangup={hangup}/>} {profileOpen&&<ProfileCard onClose={()=>setProfileOpen(false)} onSaved={profileSaved}/>}<Conversation {...c}/>
<Composer {...c}/>
<SettingsDialog inCall={!!phone} open={settingsOpen} onClose={closeSettings} settings={settings} onChange={updateSettings}/>
</div>
}
