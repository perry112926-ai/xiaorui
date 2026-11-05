const {test}=require('node:test'),assert=require('node:assert/strict');
const ts=require('typescript'),fs=require('node:fs'),vm=require('node:vm');
const exported={exports:{}},opened=[];
vm.runInNewContext(ts.transpileModule(fs.readFileSync(require.resolve('../src/payment.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module:exported,exports:exported.exports,URL,window:{open:(...args)=>opened.push(args),location:{assign:()=>{throw Error('must preserve the assistant page')}}}});
const {officialPaymentUrl,openOfficialPayment}=exported.exports;
const created={provider:'mcd',action:'create',status:'created',order:{order_id:'fixture-order',payment_url:'https://example.invalid/fixture-payment'}};
test('a successful final confirmation can hand off to the returned payment URL without paying',()=>{assert.equal(openOfficialPayment(created),true);assert.deepEqual(Array.from(opened.at(-1)),[created.order.payment_url,'_blank','noopener,noreferrer']);});
test('pending, changed, unknown, missing order and unsafe URLs never navigate',()=>{
 for(const status of ['awaiting_confirmation','needs_review','unknown','failed'])assert.equal(officialPaymentUrl({...created,status}),undefined);
 for(const payment_url of ['javascript:alert(1)','http://example.invalid','https://user:password@example.invalid'])assert.equal(officialPaymentUrl({...created,order:{order_id:'x',payment_url}}),undefined);
 assert.equal(officialPaymentUrl({...created,order:{payment_url:created.order.payment_url}}),undefined);
});

test('a blocked popup never replaces the assistant page',()=>{
 const blocked={exports:{}};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(require.resolve('../src/payment.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module:blocked,exports:blocked.exports,URL,window:{open:()=>null,location:{assign:()=>{throw Error('must not navigate current page')}}}});
 blocked.exports.openOfficialPayment(created);
});
