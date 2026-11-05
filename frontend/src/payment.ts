// Only an already-created merchant order may hand off to payment. No money is moved here.
export function officialPaymentUrl(plan:{provider?:string;action?:string;status?:string;order?:{payment_url?:unknown;order_id?:unknown}}):string|undefined{
 if(plan.provider!=='mcd'||plan.action!=='create'||plan.status!=='created'||!plan.order?.order_id||typeof plan.order.payment_url!=='string')return;
 try{const url=new URL(plan.order.payment_url);if(url.protocol==='https:'&&!url.username&&!url.password)return url.href;}catch{}
}
export function openOfficialPayment(plan:Parameters<typeof officialPaymentUrl>[0]){
 const url=officialPaymentUrl(plan);if(!url)return false;
 window.location.assign(url);return true;
}
