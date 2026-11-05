const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
const moduleObject={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(require.resolve('../src/FlightResults.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,{module:moduleObject,exports:moduleObject.exports,require:name=>name==='./CardHeading'?require('./load-card-heading.cjs'):require(name),URL});
const {FlightResults,officialFlightUrl}=moduleObject.exports;
const data={checked_at:'2026-11-06T12:00:00+08:00',flights:[{index:1,ticket_price_yuan:'400.00',booking_url:'https://router.feizhu.com/ws/example',journeys:[{type:'直达',segments:[{marketingTransportNo:'MF8561',depStationName:'大兴国际机场',arrStationName:'浦东国际机场',depDateTime:'2026-11-13 08:00',arrDateTime:'2026-11-13 10:10',seatClassName:'经济舱'}]}]}]};
test('flight cards show actual airports, times, quote and explicit external booking action',()=>{
 const html=renderToStaticMarkup(React.createElement(FlightResults,{result:data}));
 for(const expected of ['MF8561','大兴国际机场','浦东国际机场','2026-11-13 08:00','400.00','最终含税总价','尚未订票或付款','去飞猪核对并预订'])assert.ok(html.includes(expected));
 assert.match(html,/href="https:\/\/router.feizhu.com\/ws\/example"/);
 assert.match(html,/target="_blank"/);assert.match(html,/noopener noreferrer/);
 assert.doesNotMatch(html,/确认下单|confirmation_token/);
});
test('unsafe booking targets and malformed rows cannot produce clickable booking links',()=>{
 for(const url of ['javascript:alert(1)','http://router.feizhu.com/ws/x','https://router.feizhu.com.evil.test/x','https://private@router.feizhu.com/x','https://router.feizhu.com:444/x'])assert.equal(officialFlightUrl(url),undefined);
 for(const result of [null,{flights:[null,{}, {booking_url:'javascript:alert(1)',journeys:[]}]},{flights:[{...data.flights[0],journeys:[{segments:[null,{}]}]}]}]){
  const html=renderToStaticMarkup(React.createElement(FlightResults,{result}));assert.doesNotMatch(html,/<a /);
 }
});
test('errors and empty searches stay explicit and do not look like booked tickets',()=>{
 assert.match(renderToStaticMarkup(React.createElement(FlightResults,{result:{error:'请先配置飞猪'}})),/请先配置飞猪/);
 assert.match(renderToStaticMarkup(React.createElement(FlightResults,{result:{flights:[]}})),/没有可展示的航班/);
});
