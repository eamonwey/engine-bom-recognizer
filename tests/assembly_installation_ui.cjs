const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const elements = new Map();
let rows;
const context = {
  $: selector => { if (!elements.has(selector)) elements.set(selector, {textContent: '', after() {}}); return elements.get(selector); },
  bomComponents: [{name_zh: '泵体'}, {name_zh: '阀体'}, {name_zh: '钢球'}],
  fillTable: (selector, headers, data) => { rows = data; },
  esc: String,
};
context.document = {querySelector: context.$};
vm.createContext(context);
const source = fs.readFileSync('static/extensions.js', 'utf8');
vm.runInContext(source.slice(0, source.indexOf('function refreshBomValidation')), context);
const tree = {relation_semantics: 'installation', nodes: [
  {id:'ball', parent_id:'valve', component_index:2, level:3, quantity_per_parent:1},
  {id:'body', parent_id:null, component_index:0, level:1},
  {id:'valve', parent_id:'body', component_index:1, level:2, quantity_per_parent:2},
]};
context.renderAssembly(tree);
assert.equal(rows[0][1], '安装基体（根）');
assert.equal(rows[1][1], '泵体');
assert.equal(rows[2][1], '阀体');
context.renderAssembly({...tree, relation_semantics:'bom_contains'});
assert.equal(rows.length, 0);
assert.match(elements.get('#assembly-status').textContent, /尚未识别安装父子关系/);
console.log('Installation hierarchy UI checks passed');
