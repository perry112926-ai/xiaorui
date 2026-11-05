import React from 'react';
import {CardHeading} from '../CardHeading';
import {formatCents} from '../money';
import type {Store,Meal} from '../chat/types';

export function StoreCards({stores,disabled,onChoose}:{stores:Store[];disabled:boolean;onChoose:(store:Store)=>void}){
 return <section className="choice-panel">
  <CardHeading icon="place" title="选择方便的取餐门店" description="先看地址和营业情况，再选一家。"/>
  <div className="store-list">{stores.map(store=><button className="store-card" key={store.code} disabled={disabled||store.open===false} onClick={()=>onChoose(store)}>
   <strong>{store.name}</strong><span>{store.address}{store.open===false?' · 暂未营业':''}</span><small>在这家取餐 →</small>
  </button>)}</div>
 </section>;
}
export function MealCards({meals,disabled,onChoose}:{meals:Meal[];disabled:boolean;onChoose:(meal:Meal,index:number)=>void}){
 return <section className="choice-panel">
  <CardHeading icon="meal" title="挑选一份喜欢的餐品" description="选好后，还会核对搭配与总价。"/>
  <div className="meal-grid">{meals.map((meal,index)=><div className="meal-card" key={meal.product_code}>
   <div className="meal-image">{meal.image?<img src={meal.image} alt={meal.name} loading="lazy"/>:<span>暂无餐品图片</span>}<span className="letter">{String.fromCharCode(65+index)}</span></div>
   <div className="meal-content"><h3>{meal.name}</h3><p>{meal.choices.join(' · ')}</p><strong className="meal-price">¥{formatCents(meal.amount_cents)}</strong><small>到店自取 · 本次官方核价</small><button disabled={disabled} onClick={()=>onChoose(meal,index)}>选 {String.fromCharCode(65+index)} 这份</button></div>
  </div>)}</div>
 </section>;
}
