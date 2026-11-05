import React,{useState} from 'react';

export type ChoiceCard={label:string;detail?:string;image?:string;prompt:string;kind?:'product';price_yuan?:string;price_kind?:'menu'};
export function productImage(source?:string){
 if(!source)return undefined;
 // Provider images only. No invented stock pictures for missing food photos.
 try{const url=new URL(source);return url.protocol==='https:'?url.href:undefined;}catch{return undefined;}
}
function ProductPhoto({source,name}:{source?:string;name:string}){
 const url=productImage(source);
 const [failed,setFailed]=useState('');
 return <div className="food-choice-photo">{url&&failed!==url?<img src={url} alt={name} loading="lazy" referrerPolicy="no-referrer" onError={()=>setFailed(url)}/>:<div className="food-photo-missing"><span aria-hidden="true">♧</span><span>暂无餐品图片</span></div>}</div>;
}
export function ChoiceCards({choices,disabled,onChoose}:{choices:ChoiceCard[];disabled:boolean;onChoose:(prompt:string)=>void}){
 const food=choices.length>0&&choices.every(c=>c.kind==='product');
 if(!food)return <div className="service-choice-grid">{choices.map((c,i)=><button className="store-card" key={i} disabled={disabled} onClick={()=>onChoose(c.prompt)}>{productImage(c.image)&&<img src={productImage(c.image)} alt={c.label} loading="lazy"/>}<strong>{c.label}</strong>{c.detail&&<span>{c.detail}</span>}</button>)}</div>;
 return <section className="food-choices" aria-label="餐品图片和价格">
  <div className="food-choices-heading"><strong>看看这些餐品</strong><span>麦当劳菜单</span></div>
  <div className="food-choice-grid">{choices.map((c,i)=><button type="button" className="food-choice" key={`${i}-${c.label}`} disabled={disabled} onClick={()=>onChoose(c.prompt)} aria-label={`选择${c.label}，${c.price_yuan!==undefined?`菜单参考价${c.price_yuan}元`:'价格待查询'}，继续核对`}>
   <ProductPhoto source={c.image} name={c.label}/>
   <div className="food-choice-content"><span className="food-choice-number">第 {i+1} 份</span><strong className="food-choice-name">{c.label}</strong>
    <span className="food-choice-price">{c.price_yuan!==undefined?<><span className="food-currency">¥</span>{c.price_yuan}</>:<span className="food-price-missing">价格待查询</span>}</span>
    <span className="food-choice-price-note">菜单参考价</span><span className="food-choice-select">选这份<span aria-hidden="true"> →</span></span>
   </div>
  </button>)}</div>
  <p className="food-choice-note">选好后再核对套餐内容和总价，配送等费用以核价为准。点击餐品不会下单。</p>
  {disabled&&<p className="food-choice-inactive">这组餐品暂时不能选择，请以最新一组为准。</p>}
 </section>;
}
