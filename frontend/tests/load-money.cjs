// Use the production TypeScript formatter inside the VM-based UI harnesses.
const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const compiled=ts.transpileModule(fs.readFileSync(require.resolve('../src/money.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const target={exports:{}};
vm.runInNewContext(compiled,{module:target,exports:target.exports});
module.exports=target.exports;
