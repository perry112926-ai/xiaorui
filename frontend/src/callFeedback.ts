// Fixed turn acknowledgements: never results, prices, approvals or task completion.
export const feedbackText={present:'我在，您说。',heard:'嗯，听到了。',checking:'好，我帮您看看。',wait:'好，您慢慢说。',review:'好，我先核对一下。'} as const;
export type FeedbackKind=keyof typeof feedbackText;
const normalized=(text:string)=>text.replace(/[\s，。！？,.!?、]/g,'');
export function isGreeting(text:string){return /^(?:喂{1,3}|你好(?:小瑞)?|您好|小瑞|你在吗|您在吗|在吗|听得到吗|能听到吗)$/.test(normalized(text));}
export function isHolding(text:string){return /^(?:等一下|等会儿|等等|稍等|我想想|让我想想|等我一下)$/.test(normalized(text));}
export function feedbackKind(text:string):FeedbackKind{
 if(isGreeting(text))return 'present';
 if(isHolding(text))return 'wait';
 if(/确认|取消|付款|支付|下单/.test(text))return 'review';
 if(/查|看看|找|天气|附近|外卖|点餐|打车|叫车|怎么去|路线/.test(text))return 'checking';
 return 'heard';
}
const clips=new Map<FeedbackKind,Promise<Blob>>();
export function feedbackClip(kind:FeedbackKind){
 let pending=clips.get(kind);
 if(!pending){
  pending=fetch(`/assets/voice-feedback/${kind}.wav`,{cache:'force-cache'}).then(async response=>{
   if(!response.ok)throw Error('通话短回应未加载，请刷新页面后重试。');
   return response.blob();
  }).catch(error=>{clips.delete(kind);throw error;});
  clips.set(kind,pending);
 }
 return pending;
}
export function warmFeedback(){return Promise.all((Object.keys(feedbackText) as FeedbackKind[]).map(feedbackClip));}
