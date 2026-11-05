// Resolve real extracted TS modules while retaining each test's API/voice hooks.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const root=path.resolve(__dirname,'../src');
module.exports=function runFrontend(code,sandbox){
 const cache=new Map();
 function execute(source,file,target){
  const localRequire=name=>{
   if(name.startsWith('.')){
    const base=path.resolve(path.dirname(file),name);
    const normalized='./'+path.relative(root,base).split(path.sep).join('/');
    if(normalized.startsWith('./chat/')||normalized.startsWith('./components/')||normalized==='./FlightResults'){
     const found=['.ts','.tsx'].map(ext=>base+ext).find(fs.existsSync);
     if(!found)throw Error('Missing frontend module '+normalized);
     if(cache.has(found))return cache.get(found).exports;
     const child={exports:{}};cache.set(found,child);
     const compiled=ts.transpileModule(fs.readFileSync(found,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
     execute(compiled,found,child);return child.exports;
    }
    return sandbox.require(normalized);
   }
   return sandbox.require(name);
  };
  vm.runInNewContext(source,{URL,...sandbox,module:target,exports:target.exports,require:localRequire});
 }
 execute(code,path.join(root,'main.tsx'),sandbox.module);
};
