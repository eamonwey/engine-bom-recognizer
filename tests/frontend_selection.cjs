const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const elements={}, images=[], errors=[]; let calls=0;
function element(id) { return elements[id] ||= {value:'', files:[{name:'test.png'}], classList:{add(){},remove(){}},
  handlers:{}, setAttribute(k,v){this[k]=v;}, addEventListener(n,f){this.handlers[n]=f;}, getContext(){return {clearRect(){},drawImage(){},strokeRect(){}};},
  scrollIntoView(){}, setPointerCapture(){}, getBoundingClientRect(){return {left:0,top:0,width:100,height:100};}}; }
const c={ $:element, Image:class{constructor(){images.push(this);this.width=100;this.height=100;}},
  showError:(v,m)=>errors.push(m), hideError(){}, showProgress(){}, hideProgress(){},
  api:async()=>{calls++;}, FormData:class{append(){}}, pollJob(){} };
vm.createContext(c);
let app=fs.readFileSync('static/app.js','utf8');
vm.runInContext(app.slice(app.indexOf('let insJobId ='),app.indexOf('/* ───────── 复核与历史')),c);
let ext=fs.readFileSync('static/extensions.js','utf8');
vm.runInContext(ext.slice(ext.indexOf("$('#drawing-regions').addEventListener"),ext.indexOf('let reviewRevision')),c);
async function main(){
  vm.runInContext("insJobId='test'; insSelectedBox=[.1,.1,.2,.2];",c);
  element('#ins-reviewed').value='stale advanced edits';
  const locate=()=>element('#drawing-regions').handlers.click({target:{closest:()=>({dataset:{page:'1',box:'[0,0,1,1]'}})}});
  locate(); images.at(-1).onload();
  assert.match(element('#ins-box-status').textContent,/范围完整性待复核/);
  assert.equal(vm.runInContext('insSelectedBox',c),null);
  assert.equal(vm.runInContext('insRegionBox.length',c),4);
  assert.equal(element('#ins-reviewed').value,'');
  await element('#ins-correct').handlers.click();
  assert.equal(calls,0); assert.match(errors.at(-1),/框选/);
  assert.match(element('#ins-box-status').textContent,/修订未生成/);
  element('#ins-mode-text').handlers.click();
  const canvas=element('#ins-preview');
  canvas.handlers.pointerdown({clientX:10,clientY:10,currentTarget:canvas,pointerId:1});
  canvas.handlers.pointermove({clientX:30,clientY:25}); canvas.handlers.pointerup();
  assert.equal(vm.runInContext('insRegionBox',c),null);
  assert.deepEqual(Array.from(vm.runInContext('insSelectedBox',c)),[.1,.1,.3,.25]);
  locate(); const stale=images.at(-1); locate(); const latest=images.at(-1);
  latest.onload(); stale.onload();
  assert.equal(vm.runInContext('insPreviewImage',c),latest);
  assert.equal(vm.runInContext('insSelectedBox',c),null);
  console.log('PASS: region cannot submit correction; fresh manual selection required; stale image loads ignored');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
