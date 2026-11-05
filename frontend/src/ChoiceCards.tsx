import React,{useState} from 'react';

export type ChoiceCard={label:string;detail?:string;image?:string;prompt:string;kind?:'product';price_yuan?:string;price_kind?:'menu'|'quote';recommendation_id?:string;contents?:string[];fee_breakdown?:string};
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
export function ChoiceCards({choices,disabled,onChoose}:{choices:ChoiceCard[];disabled:boolean;onChoose:(prompt:string)=>void}){
 const food=choices.length>0&&choices.every(c=>c.kind==='product');
 if(!food)return <div className="service-choice-grid">{choices.map((c,i)=><button className="store-card" key={i} disabled={disabled} onClick={()=>onChoose(c.prompt)}>{productImage(c.image)&&<img src={productImage(c.image)} alt={c.label} loading="lazy"/>}<strong>{c.label}</strong>{c.detail&&<span>{c.detail}</span>}</button>)}</div>;
 return <section className="food-choices" aria-label="餐品图片和价格">
  <div className="food-choices-heading"><strong>看看这些餐品</strong><span>{choices.every(c=>c.price_kind==='quote')?'麦当劳 · 已核价':'麦当劳菜单'}</span></div>
  <div className={"food-choice-grid"+(choices.every(c=>c.price_kind==='quote')?' ready-meals':'')}>{choices.map((c,i)=><button type="button" className="food-choice" key={`${i}-${c.label}`} disabled={disabled} onClick={()=>onChoose(c.prompt)} aria-label={`选择${c.label}，${c.price_yuan!==undefined?`${c.price_kind==='quote'?'本次核价':'菜单参考价'}${c.price_yuan}元`:'价格待查询'}，继续核对`}>
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
