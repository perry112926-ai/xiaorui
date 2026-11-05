import {useRef,useState} from 'react';
import type {useVoice} from '../useVoice';
import type {ImageMessage} from './types';
import {api} from './api';
export function useComposer(options:{voice:()=>ReturnType<typeof useVoice>;cancelCapture:()=>void;setError:(s:string)=>void}){
 const [input,setInput]=useState(''),[inputMode,setInputMode]=useState<'text'|'voice'>('text'),[extrasOpen,setExtrasOpen]=useState(false);
 const [attachments,setAttachments]=useState<ImageMessage[]>([]),[uploading,setUploading]=useState(false);
 const imageInput=useRef<HTMLInputElement>(null),composerWrap=useRef<HTMLDivElement>(null),inflightSends=useRef(new Set<string>());
 function switchInput(){const voice=options.voice();if(!voice.inCall&&voice.phase!=='idle')options.cancelCapture();setInputMode(old=>old==='text'?'voice':'text');setExtrasOpen(false);}
 async function selectImages(files:FileList|null){
  if(!files?.length)return;setExtrasOpen(false);setUploading(true);options.setError('');
  try{
   if(files.length+attachments.length>4)throw Error('每条消息最多发送四张图片。');
   for(const file of Array.from(files)){
    if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8_000_000)throw Error('请选择 8 MB 以内的 JPG、PNG 或 WebP 图片。');
    const data_url=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(Error('图片读取失败，请重新选择。'));reader.readAsDataURL(file);});
    const image=await api<ImageMessage>('/api/contact/images',{data_url});setAttachments(old=>[...old,image]);
   }
  }catch(e){options.setError(e instanceof Error?e.message:'图片暂时无法发送。');}
  finally{setUploading(false);if(imageInput.current)imageInput.current.value='';}
 }
 return {input,setInput,inputMode,setInputMode,extrasOpen,setExtrasOpen,attachments,setAttachments,uploading,imageInput,composerWrap,inflightSends,switchInput,selectImages};
}
