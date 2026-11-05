const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
const moduleObject={exports:{}};
const code=ts.transpileModule(fs.readFileSync(require.resolve('../src/ChoiceCards.tsx'),'utf8'),{
 compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}
}).outputText;
vm.runInNewContext(code,{module:moduleObject,exports:moduleObject.exports,require:name=>name==='./CardHeading'?require('./load-card-heading.cjs'):require(name),URL});
const {ChoiceCards,productImage}=moduleObject.exports;
const food={label:'麦香鱼套餐',kind:'product',price_yuan:'28.50',image:'https://example.com/fish.png',prompt:'选择第7个商品'};
function render(choices,disabled=false){return renderToStaticMarkup(React.createElement(ChoiceCards,{choices,disabled,onChoose:()=>{}}));}
test('food displays actual photo, large reference price and selection without suggesting a purchase',()=>{
 const html=render([food]);assert.match(html,/https:\/\/example.com\/fish.png/);assert.match(html,/28\.50/);
 assert.match(html,/food-choice-price/);assert.match(html,/菜单参考价/);assert.match(html,/配送等费用/);assert.match(html,/点击餐品不会下单/);assert.match(html,/选这份/);
});
test('missing or unsafe photo and absent price are explicit rather than invented',()=>{
 const html=render([{...food,image:'javascript:alert(1)',price_yuan:undefined}]);
 assert.match(html,/暂无餐品图片/);assert.match(html,/价格待查询/);assert.doesNotMatch(html,/<img|¥0|javascript:/);
 assert.equal(productImage('http://example.com/a.png'),undefined);
});
test('old choices are disabled and explain how to continue',()=>{
 const html=render([food],true);assert.match(html,/disabled=""/);assert.match(html,/最新一组/);
});
test('nonfood candidates retain store layout instead of being labelled as meals',()=>{
 const html=render([{label:'测试门店',detail:'暂不营业',prompt:'选择门店'}]);assert.match(html,/store-card/);assert.doesNotMatch(html,/麦当劳菜单|菜单参考价|food-choice-price/);
});
test('click preserves the server supplied selection prompt and never invents an order action',()=>{
 const chosen=[];const element=ChoiceCards({choices:[food],disabled:false,onChoose:p=>chosen.push(p)});
 const grid=element.props.children[1];const button=grid.props.children[0];button.props.onClick();
 assert.deepEqual(chosen,['选择第7个商品']);
});
test('preflighted single meal displays its actual total and ready default contents',()=>{
 const html=render([{...food,price_kind:'quote',price_yuan:'37.90',contents:['主食','中薯条','热美式']}]);
 assert.match(html,/37\.90/);assert.match(html,/本次已核价/);assert.match(html,/主食 · 中薯条 · 热美式/);
 assert.match(html,/付款前会最后核对/);assert.doesNotMatch(html,/菜单参考价/);
});

test('every candidate group has a visible purpose and an explicit next step',()=>{
 for(const [choices,title] of [
  [[food],'为您挑选的餐品'],
  [[{label:'经济型',detail:'预估 35 元',prompt:'选择第1个车型'}],'选择适合的车型'],
  [[{label:'示例门店',prompt:'选择第1个门店'}],'选择方便的门店'],
  [[{label:'示例地址',prompt:'选择第1个配送地址'}],'选择本次收餐地址'],
  [[], '暂时没有可选方案'],
 ]){
  const html=render(choices);assert.match(html,new RegExp('<h3>'+title+'</h3>'));
  assert.match(html,/card-heading-copy/);assert.match(html,/card-heading-icon/);
 }
});
