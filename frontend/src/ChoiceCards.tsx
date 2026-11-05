import React,{useState} from 'react';
import {CardHeading} from './CardHeading';

export type ChoiceCard={available?:boolean;label:string;detail?:string;image?:string;prompt:string;kind?:'product';price_yuan?:string;price_kind?:'menu'|'quote';recommendation_id?:string;contents?:string[];fee_breakdown?:string};
export function productImage(source?:string){
 if(!source)return undefined;
 // Provider images only. No invented stock pictures for missing food photos.
 try{const url=new URL(source);return url.protocol==='https:'?url.href:undefined;}catch{return undefined;}
}
function ProductPhoto({source,name,eager=false}:{source?:string;name:string;eager?:boolean}){
 const url=productImage(source);
 const [failed,setFailed]=useState('');
 return <div className="food-choice-photo">{url&&failed!==url?<img src={url} alt={name} loading={eager?'eager':'lazy'} fetchPriority={eager?'high':'auto'} decoding="async" referrerPolicy="no-referrer" onError={()=>setFailed(url)}/>:<div className="food-photo-missing"><span aria-hidden="true">♧</span><span>暂无餐品图片</span></div>}</div>;
}
export function choiceHeading(choices:ChoiceCard[]){
 const all=(pattern:RegExp)=>choices.length>0&&choices.every(c=>pattern.test(c.prompt));
 if(!choices.length)return {title:'暂时没有可选方案',description:'可以换个条件，让小瑞再查一次。',icon:'document' as const};
 if(all(/车型/))return {title:'选择适合的车型',description:'看看车型与费用信息，选好后再核对行程。',icon:'route' as const};
 if(all(/配送地址|收餐地址/))return {title:'选择本次收餐地址',description:'核对完整地址，选定后再继续点餐。',icon:'pin' as const};
 if(all(/门店/))return {title:'选择方便的门店',description:'看看地址与营业信息，选一家方便的。',icon:'place' as const};
 if(all(/地点|位置|上车|下车/))return {title:'选择准确的位置',description:'核对地点名称和地址，再选择。',icon:'pin' as const};
 return {title:'请选一个合适的选项',description:'点选后，小瑞会继续为您核对。',icon:'document' as const};
}
export function ChoiceCards({choices,disabled,onChoose}:{choices:ChoiceCard[];disabled:boolean;onChoose:(prompt:string)=>void}){
 const heading=choiceHeading(choices);
 const food=choices.length>0&&choices.every(c=>c.kind==='product');
 if(!food)return <section className="choice-panel" aria-label="可选方案"><CardHeading icon={heading.icon} eyebrow="供您选择" title={heading.title} description={heading.description} status={`${choices.length} 个选项`}/><div className="service-choice-grid">{choices.map((c,i)=><button className="store-card" key={i} disabled={disabled||c.available===false} onClick={()=>onChoose(c.prompt)}>{productImage(c.image)&&<img src={productImage(c.image)} alt={c.label} loading="lazy"/>}<strong>{c.label}</strong>{c.detail&&<span>{c.detail}</span>}</button>)}</div></section>;
 return <section className="food-choices choice-panel" aria-label="餐品图片和价格">
  <CardHeading icon="meal" eyebrow="麦当劳 · 本次推荐" title="为您挑选的餐品" description="看看图片、搭配和价格，选一份喜欢的。" status={choices.every(c=>c.price_kind==='quote')?'已核价':'菜单参考价'}/>
  <div className={"food-choice-grid"+(choices.every(c=>c.price_kind==='quote')?' ready-meals':'')}>{choices.map((c,i)=><button type="button" className="food-choice" key={`${i}-${c.label}`} disabled={disabled||c.available===false} onClick={()=>onChoose(c.prompt)} aria-label={`选择${c.label}，${c.price_yuan!==undefined?`${c.price_kind==='quote'?'本次核价':'菜单参考价'}${c.price_yuan}元`:'价格待查询'}，继续核对`}>
   <ProductPhoto source={c.image} name={c.label} eager={!disabled}/>
   <div className="food-choice-content"><span className="food-choice-number">第 {i+1} 份</span><strong className="food-choice-name">{c.label}</strong>
    <span className="food-choice-price">{c.price_yuan!==undefined?<><span className="food-currency">¥</span>{c.price_yuan}</>:<span className="food-price-missing">价格待查询</span>}</span>
    <span className="food-choice-price-note">{c.price_kind==='quote'?'本次已核价':'菜单参考价'}</span>{c.fee_breakdown&&<span className="food-choice-fees">{c.fee_breakdown}</span>}{c.contents?.length?<span className="food-choice-contents">{c.contents.join(' · ')}</span>:null}<span className="food-choice-select">选这份<span aria-hidden="true"> →</span></span>
   </div>
  </button>)}</div>
  <p className="food-choice-note">{choices.every(c=>c.price_kind==='quote')?'已按图示搭配核对本次总价；可以直接选，也可以说想换什么。付款前会最后核对。图片为官方示意，实际以文字搭配为准。':'选好后再核对套餐内容和总价，配送等费用以核价为准。'}点击餐品不会下单。</p>
  {disabled&&<p className="food-choice-inactive">这组餐品暂时不能选择，请以最新一组为准。</p>}
 </section>;
}
