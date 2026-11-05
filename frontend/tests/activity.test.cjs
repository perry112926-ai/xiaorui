const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const moduleUnderTest={exports:{}};
const code=ts.transpileModule(fs.readFileSync(require.resolve('../src/main.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
require('./load-frontend.cjs')(code,{module:moduleUnderTest,exports:moduleUnderTest.exports,require:name=>{
 if(name==='./CardHeading')return require('./load-card-heading.cjs');
 if(name==='react-dom/client')return{createRoot:()=>({render(){}})};
 if(name==='./payment')return{};
 if(name==='./CallBar'||name==='./ChoiceCards')return{};
 if(name==='./useVoice'||name==='./ProfileCard'||name==='./location')return{};
 if(name==='./ActionCard'||name==='./Companion'||name==='./SettingsDialog'||name==='./HoldToTalk')return{};
 if(name.endsWith('.css'))return{};
 return name==='./money'?require('./load-money.cjs'):require(name);
},document:{getElementById:()=>({})}});
const {MessageProgress}=moduleUnderTest.exports;
const render=props=>renderToStaticMarkup(React.createElement(MessageProgress,props));
test('message progress shows the actual turn stage without a permanent idle bar',()=>{
 const html=render({text:'正在查麦当劳菜单'});assert.match(html,/正在查麦当劳菜单/);assert.match(html,/role="status"/);assert.doesNotMatch(html,/小瑞在这里|取消任务|\d+%|activity-strip/);
});
test('partial reply is shown alongside this message stage and safely escaped',()=>{
 const html=render({text:'正在回复',stream:'<脚本>这是逐步生成的回复'});assert.match(html,/message-text/);assert.match(html,/&lt;脚本&gt;/);assert.doesNotMatch(html,/<脚本>/);
});
