const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
const moduleUnderTest={exports:{}};
const code=ts.transpileModule(fs.readFileSync(require.resolve('../src/Companion.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
vm.runInNewContext(code,{module:moduleUnderTest,exports:moduleUnderTest.exports,require:name=>name.endsWith('.css')?{}:require(name)});
const {companionMood,companionSettleDelay,Companion,CompanionAvatar}=moduleUnderTest.exports;
const state={phase:'idle',recording:false,speaking:false,loadingSpeech:false,pending:0,context:''};
test('companion follows actual capture, speech and task state instead of declaring success',()=>{
 for(const phase of ['connecting','listening','finishing'])assert.equal(companionMood({...state,phase}),'listening');
 assert.equal(companionMood({...state,speaking:true}),'speaking');
 assert.equal(companionMood({...state,pending:1,context:'查滴滴车型'}),'taxi');
 assert.equal(companionMood({...state,pending:1,context:'查瑞幸咖啡'}),'dining');
 assert.equal(companionMood({...state,context:'刚刚叫过车'}),'idle');
 const html=renderToStaticMarkup(React.createElement(Companion,{mood:'taxi',label:'正在查询车型',name:'小暖'}));
 assert.match(html,/xiaorui-taxi.png/);assert.match(html,/正在查询车型/);assert.doesNotMatch(html,/下单成功|叫车成功/);
});
test('all selected avatar variants render and the customized name is escaped',()=>{
 for(const variant of ['portrait','leaf','sun'])assert.match(renderToStaticMarkup(React.createElement(CompanionAvatar,{variant,name:'<小暖>'})),new RegExp('avatar-'+variant));
 const html=renderToStaticMarkup(React.createElement(Companion,{mood:'idle',label:'陪着您',name:'<小暖>'}));
 assert.match(html,/&lt;小暖&gt;/);assert.doesNotMatch(html,/<小暖>/);
});

test('open call microphone cannot mask playback, audio preparation or real tasks',()=>{
 assert.equal(companionMood({...state,phase:'listening',speaking:true}),'speaking');
 assert.equal(companionMood({...state,phase:'listening',loadingSpeech:true}),'working');
 assert.equal(companionMood({...state,phase:'listening',pending:1,context:'正在查滴滴车型和预估费用'}),'taxi');
 assert.equal(companionMood({...state,phase:'listening',pending:1,context:'正在查瑞幸饮品'}),'dining');
 assert.equal(companionMood({...state,recording:true,speaking:true,pending:1,context:'正在查菜单'}),'listening');
 assert.equal(companionMood({...state,pending:1,context:'正在理解您的消息'}),'working');
});
test('each visible state has a distinct pose or mark without a redundant status caption',()=>{
 for(const mood of ['idle','working','listening','speaking','taxi','dining']){
  const html=renderToStaticMarkup(React.createElement(Companion,{mood,label:'真实状态',name:'小瑞'}));
  assert.match(html,new RegExp('scene-'+mood));assert.match(html,/role="img"/);assert.doesNotMatch(html,/companion-sign|companion-caption/);
  if(mood==='idle')assert.doesNotMatch(html,/companion-state-mark/);
  else assert.match(html,new RegExp('mark-'+({working:'thinking',speaking:'speaking',listening:'listening',taxi:'taxi',dining:'dining'}[mood])));
  assert.match(html,new RegExp('xiaorui-'+(['taxi','dining'].includes(mood)?mood:'working')+'\\.png'));
 }
});
test('short task art settles gently but new speech or listening is never delayed',()=>{
 assert.equal(companionSettleDelay('taxi','idle',200),1000);
 assert.equal(companionSettleDelay('dining','idle',1500),0);
 assert.equal(companionSettleDelay('working','listening',0),0);
 assert.equal(companionSettleDelay('taxi','speaking',0),0);
 assert.equal(companionSettleDelay('dining','taxi',0),0);
});
test('reduced motion retains distinct static visual marks and stops all companion animation',()=>{
 const css=fs.readFileSync(require.resolve('../src/Companion.css'),'utf8');
 assert.match(css,/@media\(prefers-reduced-motion:reduce\)/);assert.match(css,/animation:none!important/);
 for(const mood of ['idle','listening','working','speaking','taxi','dining'])assert.ok(css.includes('.scene-'+mood));
 assert.match(css,/\.phone-active \.companion-inline\{display:block\}/);
});
test('a new activity cancels a pending settle timer instead of reverting to an old idle pose',()=>{
 const slots=[],effects=[],timers=new Map();let index=0,clock=0,nextTimer=0;
 const hooks={...React,useState(initial){const at=index++;if(!(at in slots))slots[at]=initial;return[slots[at],value=>{slots[at]=value;}];},useRef(initial){const at=index++;if(!(at in slots))slots[at]={current:initial};return slots[at];},useEffect(fn,deps){const at=index++;const previous=slots[at];if(!previous||deps.some((value,i)=>value!==previous.deps[i])){slots[at]={deps,cleanup:previous?.cleanup};effects.push(()=>{slots[at].cleanup?.();slots[at].cleanup=fn();});}}};
 const mod={exports:{}};vm.runInNewContext(code,{module:mod,exports:mod.exports,require:name=>name==='react'?hooks:name.endsWith('.css')?{}:require(name),Date:{now:()=>clock},setTimeout(fn,delay){const id=++nextTimer;timers.set(id,{fn,at:clock+delay});return id;},clearTimeout:id=>timers.delete(id)});
 const render=mood=>{index=0;const node=mod.exports.Companion({mood,label:'状态',name:'小瑞'});while(effects.length)effects.shift()();return node.props['data-state'];};
 assert.equal(render('taxi'),'taxi');clock=200;assert.equal(render('idle'),'taxi');assert.equal(timers.size,1);
 render('speaking');assert.equal(render('speaking'),'speaking');assert.equal(timers.size,0);
 clock=2000;for(const task of timers.values())if(task.at<=clock)task.fn();assert.equal(render('speaking'),'speaking');
});
