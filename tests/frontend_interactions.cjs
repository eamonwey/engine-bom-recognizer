// Run: node tests/frontend_interactions.cjs (no browser or API credentials needed).
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('static/app.js', 'utf8');
async function main() {
  let tick, resolve, requests = 0;
  const errors = [], hidden = [];
  const context = {
    currentView: () => 'settings',
    setInterval: fn => { tick = fn; return 1; }, clearInterval: () => {},
    api: () => { requests++; return new Promise(r => resolve = r); },
    showError: (view, message) => errors.push([view, message]),
    hideProgress: view => hidden.push(view)
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function pollJob('), source.indexOf('const currentView')), context);
  context.pollJob('a', () => {}, 'bom');
  const pending = tick();
  await tick();
  assert.equal(requests, 1, 'Slow requests must not overlap');
  resolve({status:'failed', error:'额度不足'});
  await pending;
  assert.deepEqual(errors, [['bom','额度不足']], 'Failure belongs to original page');
  assert.deepEqual(hidden, ['bom']);

  const events = {}, inputEvents = {}, title = {}, meta = {};
  let clicks = 0, selected;
  const input = {files:[{name:'drawing.pdf',size:1048576}], disabled:false,
    addEventListener:(name,fn) => inputEvents[name]=fn,
    click:() => { clicks++; events.click({target:input}); }};
  const drop = {setAttribute:()=>{},classList:{add:()=>{},remove:()=>{}},
    addEventListener:(name,fn) => events[name]=fn,
    querySelector:sel => sel === '.drop-title' ? title : meta};
  context.$ = sel => sel === '#drop' ? drop : input;
  vm.runInContext(source.slice(source.indexOf('function bindDrop('), source.indexOf('/* ───────── BOM')), context);
  context.bindDrop('#drop','#file',file => selected=file);
  events.click({target:drop});
  assert.equal(clicks,1,'Hidden file input must not recursively trigger itself');
  inputEvents.change();
  assert.equal(title.textContent,'drawing.pdf');
  assert.equal(selected.name,'drawing.pdf');
  assert.match(meta.textContent,/1.00 MB/);
  events.keydown({key:'Enter',preventDefault:()=>{}});
  assert.equal(clicks,2,'Keyboard can open picker');
  input.disabled=true;
  events.keydown({key:'Enter',preventDefault:()=>{}});
  events.drop({preventDefault:()=>{}, dataTransfer:{files:[{name:'other.pdf'}]}});
  assert.equal(clicks,2);
  assert.equal(input.files[0].name,'drawing.pdf','Busy uploads cannot be replaced');
  console.log('PASS: polling ownership, request serialization, picker recursion, file details, keyboard and busy upload protection');
}
main().catch(error => { console.error(error); process.exitCode=1; });
