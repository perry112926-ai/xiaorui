import type {ActionPlan} from '../ActionCard';
import type {ChoiceCard} from '../ChoiceCards';
import type {PhoneCall} from '../CallBar';
export type Store={code:string;name:string;address:string;open?:boolean};
export type Selection={store_code:string;product_code:string;quantity:number;rounds:{round_id:string;code:string;quantity:number}[]};
export type Meal={product_code:string;name:string;image?:string;amount_cents:number;choices:string[];request:Selection};
export type LegacyPlan={id:string;version:number;status:string;amount_cents:number;summary:Record<string,unknown>;expires_at:number;confirmation_token:string;order?:ActionPlan['order'];error?:string;provider?:ActionPlan['provider'];action?:ActionPlan['action'];execution_enabled?:boolean;confirmation_text?:string};
export type ImageMessage={id:string;url:string};
export type Message={flightResult?:unknown;ackFor?:string;task_id?:string;pending?:boolean;progress?:string;stream?:string;replyTo?:string;call?:PhoneCall;locationRequest?:boolean;images?:ImageMessage[];client_id?:string;message_id?:string;delivery?:string;id:number;role:'user'|'assistant';text:string;speech_text?:string;stores?:Store[];meals?:Meal[];actionPlan?:ActionPlan;choices?:ChoiceCard[]};
export type Health={read_only?:boolean;order_execution_enabled:boolean;mcd_configured:boolean;agent_configured?:boolean};
export type ChatEvent={type:'flight_result';data:unknown}|{type:'location_request'}|{type:'stores';stores:Store[]}|{type:'meals';meals:Meal[]}|{type:'plan';plan:LegacyPlan}|{type:'action_plan';plan:ActionPlan}|{type:'service_choices';choices:ChoiceCard[]}|{type:'service_result';provider:string;data:unknown}|{type:'query_result';provider:string;tool:string;success:boolean;source:string;data:unknown};
export type ChatResponse={task_id?:string;speech_deferred?:boolean;text:string;speech_text?:string;events:ChatEvent[];conversation_reset?:boolean};
export function legacyAction(plan:LegacyPlan):ActionPlan {
 const summary={...plan.summary};
 for(const [old,key] of Object.entries({product_name:'product',store_name:'store',store_address:'address',take_way:'fulfillment'})){
  if(summary[key]===undefined&&summary[old]!==undefined)summary[key]=summary[old];
  delete summary[old];
 }
 return {...plan,provider:plan.provider??'mcd',action:plan.action??'create',summary,
   execution_enabled:plan.execution_enabled??false,confirmation_text:plan.confirmation_text??'确认下单'};
}
