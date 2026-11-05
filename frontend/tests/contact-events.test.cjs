const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const moduleObject={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(require.resolve('../src/chat/contactEvents.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module:moduleObject,exports:moduleObject.exports});
const {parseContactEvent}=moduleObject.exports;
test('wire parser rejects unknown variants and malformed nested action plans before state changes',()=>{
 for(const event of [null,{type:'future'},{type:'accepted',message_id:'m',client_id:'c',text:42},{type:'completed',message_id:'m',response:{text:'x',events:[{type:'action_plan',plan:{id:'p'}}]}},{type:'progress',message_id:'m',text:{nested:'x'}},{type:'started',message_id:'m',message_ids:['m',3]}])assert.throws(()=>parseContactEvent(event));
});
test('valid speech-ready, ordinary and call events retain their discriminant',()=>{
 for(const event of [{type:'speech_ready',task_id:'t',speech_text:'真实播报'},{type:'delta',message_id:'m',text:'文本'},{type:'call_ended',call:{id:'c',started_at:1,duration_seconds:2}},{type:'completed',message_id:'m',response:{text:'结果',events:[]}}])assert.equal(parseContactEvent(event).type,event.type);
});
