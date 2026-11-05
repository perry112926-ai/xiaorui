const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const compiled=ts.transpileModule(fs.readFileSync(require.resolve('../src/ActionCard.tsx'),'utf8'),{
 compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React,esModuleInterop:true}
}).outputText;
const moduleObject={exports:{}};
vm.runInNewContext(compiled,{module:moduleObject,exports:moduleObject.exports,require:name=>name==='./payment'?{openOfficialPayment:()=>false}:require(name),console,setInterval,clearInterval});
const {ActionCard}=moduleObject.exports;
function card(overrides={}){
 const plan={id:'ours',provider:'mcd',action:'create',status:'created',summary:{address:'测试大楼',product:'麦香鱼 × 1；薯条 × 1'},
  amount_cents:3800,version:1,confirmation_token:'test',confirmation_text:'确认下单',execution_enabled:true,
  expires_at:Date.now()/1000+300,order:{order_id:'real-order'},...overrides};
 return renderToStaticMarkup(React.createElement(ActionCard,{plan,active:true,speak:()=>{},onChange:()=>{}}));
}
test('created McDonald order offers progress and cancellation conditions without claiming cancellation',()=>{
 const html=card();assert.match(html,/查看取消条件/);assert.match(html,/查询最新进度/);
 assert.match(html,/不会直接取消/);assert.match(html,/38\.00/);assert.match(html,/薯条/);
});
test('address confirmation is distinct and does not offer order cancellation or a meal price',()=>{
 const html=card({action:'create_address',status:'awaiting_confirmation',confirmation_text:'确认新增地址',order:undefined,
  summary:{contact:'测试',phone:'13800000000',address:'测试楼',address_detail:'前台',privacy:'确认后保存至麦当劳'}});
 assert.match(html,/新增配送地址/);assert.match(html,/确认新增地址/);assert.match(html,/13800000000/);
 assert.doesNotMatch(html,/查看取消条件|本次总价|确认下单/);
});
test('unknown outcome asks for verification instead of offering another confirmation',()=>{
 const html=card({status:'unknown',order:undefined});
 assert.match(html,/不会自动重复提交/);assert.doesNotMatch(html,/>确认下单<|查看取消条件/);
});
test('pending meal does not offer cancellation of a real order',()=>{
 const html=card({status:'awaiting_confirmation',order:undefined});
 assert.match(html,/确认下单/);assert.doesNotMatch(html,/查看取消条件/);
});
test('Luckin is described as a drink plan rather than a general meal service',()=>{
 const html=card({provider:'luckin'});assert.match(html,/饮品方案/);assert.doesNotMatch(html,/点餐方案|查看取消条件/);
});
