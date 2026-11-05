const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
test('all fixed acknowledgements ship as real local WAV files',()=>{
 for(const name of ['present','heard','checking','wait','review']){
  const bytes=fs.readFileSync(path.join(__dirname,'../public/assets/voice-feedback',name+'.wav'));
  assert.equal(bytes.toString('ascii',0,4),'RIFF');assert.equal(bytes.toString('ascii',8,12),'WAVE');
  assert.ok(bytes.length>1000&&bytes.length<100000,name);
 }
});
