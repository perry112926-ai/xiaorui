import {formatCents} from './money';
import React,{useEffect,useRef,useState} from 'react';
import {CardHeading} from './CardHeading';
import {openOfficialPayment} from './payment';

export type ActionPlan={id:string;provider:'didi'|'mcd'|'luckin';action:'create'|'cancel'|'create_address';status:string;
 summary:Record<string,unknown>;amount_cents:number;version:number;confirmation_token:string;
 confirmation_text:string;execution_enabled:boolean;expires_at:number;error?:string;
 order?:{order_id?:string;payment_url?:string;last_status?:Record<string,any>;[key:string]:unknown}};
const providers={didi:'滴滴出行',mcd:'麦当劳',luckin:'瑞幸咖啡'};
const states:Record<string,string>={awaiting_confirmation:'请您核对',needs_review:'方案有变化，请再核对',
 address_created:'配送地址已创建',created:'请求已提交',cancelled:'已取消',superseded:'已换新方案',expired:'方案已过期',unknown:'结果待核查',
 rechecking:'正在重新核价',submitting:'正在提交',failed:'尚未完成',cancellation_requested:'取消请求已提交'};
const names:Record<string,string>={phone_tail:'收餐电话尾号',city:'城市',contact:'联系人',phone:'联系电话',privacy:'信息用途',store:'门店',address:'地址',address_detail:'门牌',product:'商品',attributes:'规格',
 quantity:'数量',fulfillment:'取餐方式',choices:'套餐内容',payment:'支付说明',fee_note:'费用说明',
 action:'操作',cancel_fee_yuan:'取消费用',tableware:'餐具',remark:'给商家的备注',fee_breakdown:'费用明细',defaults:'搭配说明'};
function details(value:unknown):string{
 if(value===null||value===undefined)return '';
 if(Array.isArray(value))return value.map(v=>typeof v==='string'?v:(v?.attribute?`${v.attribute}：${(v.selected??[]).join('、')}`:'')).filter(Boolean).join(' · ');
 return typeof value==='object'?'':String(value);
}
async function request(id:string,suffix:string,body:unknown={}){
 const response=await fetch(`/api/actions/${id}/${suffix}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const result=await response.json();if(!response.ok)throw Error(result.detail||'暂时没有完成，请稍后再试。');return result;
}
function statusText(p:ActionPlan){
 const data=p.order?.last_status;if(!data)return '';
 return String(data.orderStatusName||data.statusText||data.statusName||
  (typeof data.orderStatus==='string'&&!/^\d+$/.test(data.orderStatus)?data.orderStatus:'')||
  (p.provider==='didi'?({'0':'正在匹配司机','1':'司机已接单','2':'司机已到达','4':'行程中','5':'行程已完成'} as Record<string,string>)[String(data.statusCode)]:'')||'');
}
function progressKey(p:ActionPlan){
 const s=p.order?.last_status;
 return [statusText(p),s?.driver?.carPlate,s?.expectDeliveryTime,s?.riderNickName].filter(Boolean).join('|');
}
export function ActionCard({plan,active,speak,onChange,onPrepared}:{plan:ActionPlan;active:boolean;speak:(s:string)=>void;onChange:(p:ActionPlan)=>void;onPrepared?:(p:ActionPlan)=>void}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const previous=useRef(progressKey(plan));
 const renewable=plan.provider==='mcd'&&plan.action==='create';
 const review=['awaiting_confirmation','needs_review'].includes(plan.status)||(renewable&&plan.status==='expired');
 const expired=plan.expires_at*1000<=Date.now();
 async function act(suffix:string,body:unknown={},announce=true){
  if(busy)return;setBusy(true);setError('');try{const result=await request(plan.id,suffix,body);if(suffix==='prepare-cancel')onPrepared?.(result.plan);else onChange(result.plan);
   if(announce&&result.speech_text)speak(result.speech_text);
   if(suffix==='confirm')openOfficialPayment(result.plan);
  }catch(e){const text=e instanceof Error?e.message:'暂时无法查询。';setError(text);if(announce)speak(text);}finally{setBusy(false)}
 }
 useEffect(()=>{
  const text=statusText(plan),driver=plan.order?.last_status?.driver;
  const key=progressKey(plan),eta=plan.order?.last_status?.expectDeliveryTime;
  if(active&&key&&key!==previous.current){speak(`${providers[plan.provider]}：${text?`${text}。`:''}${driver?.carPlate?`车牌是${driver.carPlate}。`:''}${eta?`平台预计送达时间：${eta}，实际以配送情况为准。`:''}`);previous.current=key;}
 },[plan.order?.last_status,active]);
 useEffect(()=>{
  if(!active||!['created','cancellation_requested'].includes(plan.status)||!plan.order?.order_id)return;
  const text=statusText(plan);if(/已完成|已取消|已退款/.test(text))return;
  const timer=setInterval(()=>{void act('refresh',{},false)},30000);return()=>clearInterval(timer);
 },[plan.id,plan.status,plan.order?.order_id,active,busy,statusText(plan)]);
 const orderStatus=statusText(plan),driver=plan.order?.last_status?.driver;
 const payment=plan.order?.payment_url;
 const mealImages=Array.isArray(plan.summary.images)?plan.summary.images.filter((v:any)=>typeof v?.image==='string'&&v.image.startsWith('https://')):[];
 return <section className="order-card action-card" aria-label={`${providers[plan.provider]}操作方案`}>
  <CardHeading icon={plan.action==='create_address'?'pin':plan.provider==='didi'?'route':'meal'} eyebrow={providers[plan.provider]}
   title={plan.action==='create_address'?'新增配送地址':plan.action==='cancel'?'取消订单方案':review?(plan.provider==='didi'?'核对您的出行方案':plan.provider==='luckin'?'核对您的饮品方案':'核对您的点餐方案'):(plan.provider==='didi'?'出行方案与进度':plan.provider==='luckin'?'饮品订单与进度':'点餐订单与进度')}
   description={review?'请逐项核对下面的信息，再决定是否确认。':'以下为这份方案的记录，请以平台最新状态为准。'}
   status={states[expired&&review?'expired':plan.status]||'请核对当前结果'}/>

  {mealImages.length>1?<div className="confirmed-meal-grid">{mealImages.map((item:any,i:number)=><figure key={i}><img src={item.image} alt={item.name} loading={active?'eager':'lazy'} referrerPolicy="no-referrer"/><figcaption>{item.name} × {item.quantity}</figcaption></figure>)}</div>:typeof plan.summary.image==='string'&&plan.summary.image.startsWith('https://')&&<img className="confirmed-meal-photo" src={plan.summary.image} alt={String(plan.summary.product||'所选套餐')} loading={active?'eager':'lazy'} referrerPolicy="no-referrer"/>}
  <dl className="action-details">{Object.entries(plan.summary).map(([key,value])=>{
   const label=names[key]||(/^[\u4e00-\u9fff]/.test(key)?key:'');const text=details(value);
   return label&&text?<div key={key}><dt>{label}</dt><dd>{text}</dd></div>:null;
  })}</dl>
  {plan.action!=='create_address'&&<div className="total"><span>{plan.action==='cancel'?'取消费用':plan.provider==='didi'?'本次预估费用':'本次总价'}</span><strong>¥{formatCents(plan.amount_cents)}</strong></div>}
  {plan.provider==='didi'&&plan.action==='create'&&review&&<p className="note">确认后会真实叫车，关联账号可能免密扣款。请核对实际接送点，最终车费以平台为准。</p>}
  {plan.error&&<p className="note">{plan.error}</p>}
  {review&&!plan.execution_enabled&&<p className="note">家人尚未开启这项真实订单执行。</p>}
  {review&&active&&<div className="card-actions"><button className="primary" disabled={busy||(expired&&!renewable)||!plan.execution_enabled} onClick={()=>void act('confirm',{version:plan.version,confirmation_token:plan.confirmation_token,confirmation_text:plan.confirmation_text})}>{expired&&renewable?'重新核价 · 不下单':`${plan.confirmation_text}${renewable?' · 去付款':''}`}</button><button disabled={busy} onClick={()=>void act('cancel-plan')}>取消这个方案</button></div>}
  {review&&active&&<p className="note">也可以直接说：“{plan.confirmation_text}”。</p>}
  {plan.status==='address_created'&&<p role="status">地址已保存至麦当劳。请继续查询配送地址，选择新地址查店点餐；尚未下单。</p>}
  {plan.status==='unknown'&&<p className="note">请先到官方渠道核查，这笔请求不会自动重复提交。</p>}
  {orderStatus&&<p className="order-progress" role="status">{orderStatus}</p>}
  {plan.order?.last_status?.expectDeliveryTime&&<p>平台预计送达：{String(plan.order.last_status.expectDeliveryTime)}</p>}
  {plan.order?.last_status?.riderNickName&&<p>配送员：{String(plan.order.last_status.riderNickName)}</p>}
  {driver?.carPlate&&<p>车牌：<strong>{driver.carPlate}</strong>{driver.carModel?` · ${driver.carModel}`:''}</p>}
  {plan.order?.order_id&&<button disabled={busy} onClick={()=>void act('refresh')}>{busy?'正在查询…':'查询最新进度'}</button>}
  {['didi','mcd'].includes(plan.provider)&&plan.action==='create'&&plan.order?.order_id&&<><button disabled={busy} onClick={()=>void act('prepare-cancel')}>查看取消条件</button><p className="note">这里只查询取消条件，不会直接取消。若无法取得取消条件或费用，请到对应官方 App／小程序的订单页面核对办理。</p></>}
  {typeof payment==='string'&&payment.startsWith('https://')&&<a className="primary link-button" href={payment} target="_blank" rel="noreferrer">打开官方支付入口 ↗</a>}
  {error&&<p className="error" role="alert">{error}</p>}
 </section>;
}
