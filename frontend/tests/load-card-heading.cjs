const fs=require('node:fs'),vm=require('node:vm'),ts=require('typescript');
const loaded={exports:{}};
const code=ts.transpileModule(fs.readFileSync(require.resolve('../src/CardHeading.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
vm.runInNewContext(code,{module:loaded,exports:loaded.exports,require});
module.exports=loaded.exports;
