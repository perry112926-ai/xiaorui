import {useEffect,useRef,useState} from 'react';
import {locate} from '../location';
export function useLocation(){
 const [locationStatus,setLocationStatus]=useState(''),[locationBusy,setLocationBusy]=useState(false);
 const locationFresh=useRef(0),locating=useRef<Promise<boolean>|null>(null);
 useEffect(()=>{if(!locationStatus||locationBusy)return;const timer=setTimeout(()=>setLocationStatus(''),5000);return()=>clearTimeout(timer);},[locationStatus,locationBusy]);
 async function requestLocation(){
  if(locating.current)return locating.current;
  const job=(async()=>{setLocationBusy(true);setLocationStatus('正在定位，请留意浏览器或系统权限提示…');try{const accuracy=await locate();locationFresh.current=Date.now();setLocationStatus(`已定位 · 误差约${Math.ceil(accuracy)}米 · 2分钟有效`);return true;}catch(e){setLocationStatus(e instanceof Error?e.message:'定位失败，请说出地标。');return false;}})();
  locating.current=job;try{return await job;}finally{locating.current=null;setLocationBusy(false);}
 }
 return {locationStatus,locationBusy,locationFresh,requestLocation};
}
