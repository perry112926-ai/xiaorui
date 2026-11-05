import {useEffect,useRef,useState} from 'react';
import type {MutableRefObject} from 'react';
import type {useVoice} from '../useVoice';
import type {PhoneCall} from '../CallBar';
import {api} from './api';
export function usePhone(voice:ReturnType<typeof useVoice>,options:{setError:(s:string)=>void;setNotice:(s:string)=>void;showCall:(call:PhoneCall)=>void;autoplay:MutableRefObject<boolean>;interrupted:MutableRefObject<boolean>;closeExtras:()=>void}){
 const [phone,setPhone]=useState<PhoneCall>(),activePhone=useRef<PhoneCall|undefined>(undefined),startingPhone=useRef(false),greetedPhone=useRef('');
 const [phoneProgress,setPhoneProgress]=useState('');
 const phonePendingIds=useRef(new Set<string>());
 async function finishPhone(){
  const call=activePhone.current;if(!call)return;
  activePhone.current=undefined;setPhone(undefined);phonePendingIds.current.clear();setPhoneProgress('');
  try{options.showCall(await api<PhoneCall>(`/api/contact/calls/${call.id}/end`,{}));}
  catch{options.setError('通话已停止，时长记录暂未同步，请刷新后核对。');}
 }
 function hangup(){options.autoplay.current=false;options.interrupted.current=true;voice.endCall();options.setNotice('已挂断。');return finishPhone();}
 async function startPhone(){
  if(startingPhone.current||activePhone.current)return;
  startingPhone.current=true;options.closeExtras();options.setError('');
  try{
   const call=await api<PhoneCall>('/api/contact/calls',{});activePhone.current=call;setPhone(call);options.autoplay.current=true;options.setNotice('');
   const connected=await voice.startCall();if(!connected&&activePhone.current?.id===call.id)await finishPhone();
  }catch(e){options.setError(e instanceof Error?e.message:'暂时无法接通电话。');await finishPhone();}
  finally{startingPhone.current=false;}
 }
 useEffect(()=>{if(phone&&!voice.inCall&&!startingPhone.current)void finishPhone();},[voice.inCall,phone]);
 useEffect(()=>{if(phone&&voice.inCall&&voice.phase==='listening'&&greetedPhone.current!==phone.id){greetedPhone.current=phone.id;void voice.feedback('喂');}},[phone,voice.inCall,voice.phase]);
 return {phone,activePhone,phoneProgress,setPhoneProgress,phonePendingIds,hangup,startPhone,finishPhone};
}
