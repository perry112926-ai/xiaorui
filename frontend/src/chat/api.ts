export async function api<T>(url:string,body?:unknown):Promise<T>{
 const r=await fetch(url,{method:body===undefined?'GET':'POST',headers:body===undefined?undefined:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
 if(!r.headers.get('content-type')?.includes('application/json'))throw Error('本地服务暂时不可用，请稍后重试。');
 const d:unknown=await r.json();
 if(!r.ok)throw Error(typeof d==='object'&&d!==null&&'detail' in d&&typeof d.detail==='string'?d.detail:'这一步暂时没有完成，请稍后重试。');
 return d as T;
}
