const {test}=require('node:test'),assert=require('node:assert/strict');
const ts=require('typescript'),fs=require('node:fs'),vm=require('node:vm');
const moduleObject={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(require.resolve('../src/money.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,{exports:moduleObject.exports,module:moduleObject});
const {formatCents}=moduleObject.exports;
test('formats integer cents exactly, including the largest safe integer',()=>{
 for(const [n,s] of [[0,'0.00'],[1,'0.01'],[10,'0.10'],[101,'1.01'],[-1,'-0.01'],[Number.MAX_SAFE_INTEGER,'90071992547409.91']])assert.equal(formatCents(n),s);
});
test('rejects malformed and unsafe amounts',()=>{
 for(const n of [NaN,Infinity,1.1,'100',true,Number.MAX_SAFE_INTEGER+1])assert.throws(()=>formatCents(n),{name:'TypeError'});
});
