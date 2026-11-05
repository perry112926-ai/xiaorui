import {CardHeading} from './CardHeading';

type Segment={marketingTransportNo?:string;marketingTransportName?:string;depStationName?:string;arrStationName?:string;depDateTime?:string;arrDateTime?:string;depTerm?:string;arrTerm?:string;seatClassName?:string};
type Flight={index:number;ticket_price_yuan:string;booking_url:string;segments:Segment[];types:string[]};
const object=(value:unknown):value is Record<string,unknown>=>typeof value==='object'&&value!==null&&!Array.isArray(value);
export function officialFlightUrl(value:unknown):string|undefined{
 if(typeof value!=='string'||/[\r\n<>]/.test(value))return;
 try{const url=new URL(value);if(url.protocol==='https:'&&url.hostname==='router.feizhu.com'&&!url.username&&!url.password&&(!url.port||url.port==='443'))return url.href;}catch{/* Hide malformed booking links. */}
}
export function flightView(result:unknown):{flights:Flight[];error?:string;checked_at?:string}{
 if(!object(result))return{flights:[],error:'航班结果格式不正确，请重新查询。'};
 if(typeof result.error==='string')return{flights:[],error:result.error};
 const flights:Flight[]=[];
 for(const row of Array.isArray(result.flights)?result.flights.slice(0,5):[]){
  if(!object(row))continue;
  const link=officialFlightUrl(row.booking_url);if(!link)continue;
  const segments:Segment[]=[],types:string[]=[];
  for(const journey of Array.isArray(row.journeys)?row.journeys.slice(0,4):[]){
   if(!object(journey))continue;
   if(typeof journey.type==='string')types.push(journey.type);
   for(const segment of Array.isArray(journey.segments)?journey.segments.slice(0,8):[]){
    if(!object(segment))continue;
    const clean:Record<string,string>={};
    for(const key of ['marketingTransportNo','marketingTransportName','depStationName','arrStationName','depDateTime','arrDateTime','depTerm','arrTerm','seatClassName'])if(typeof segment[key]==='string')clean[key]=segment[key];
    if(clean.depStationName&&clean.arrStationName&&clean.depDateTime&&clean.arrDateTime)segments.push(clean);
   }
  }
  if(segments.length)flights.push({index:flights.length+1,ticket_price_yuan:typeof row.ticket_price_yuan==='string'||typeof row.ticket_price_yuan==='number'?String(row.ticket_price_yuan):'待核对',booking_url:link,segments,types});
 }
 return{flights,checked_at:typeof result.checked_at==='string'?result.checked_at:undefined};
}
export function FlightResults({result}:{result:unknown}){
 const view=flightView(result);
 return <section className="choice-panel flight-results" aria-label="飞猪航班查询结果">
  <CardHeading icon="pin" title="飞猪航班" description="搜索报价，最终含税总价以飞猪结算页为准。"/>
  {view.error?<p role="alert">{view.error}</p>:view.flights.length?<div className="flight-list">{view.flights.map(flight=><article className="flight-card" key={flight.index}>
   <div className="flight-card-heading"><strong>方案 {flight.index} · {flight.types.join(' / ')}</strong><span>票价 ¥{flight.ticket_price_yuan}</span></div>
   {flight.segments.map((segment,i)=><div className="flight-segment" key={i}><strong>{segment.marketingTransportName} {segment.marketingTransportNo} · {segment.seatClassName}</strong><p>{segment.depStationName} {segment.depTerm} · {segment.depDateTime}<br/>→ {segment.arrStationName} {segment.arrTerm} · {segment.arrDateTime}</p></div>)}
   <a className="primary link-button" href={flight.booking_url} target="_blank" rel="noopener noreferrer" aria-label={`在飞猪预订方案${flight.index}`}>去飞猪核对并预订 ↗</a>
  </article>)}</div>:<p>本次没有可展示的航班，请调整日期或条件。</p>}
  {view.checked_at&&<small>查询时间：{view.checked_at.replace('T',' ')}</small>}
  <p className="flight-boundary">尚未订票或付款。请在飞猪核对乘机人、总价、行李和退改规则后确认付款。</p>
 </section>;
}
