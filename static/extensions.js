"use strict";
function renderAssembly(tree, opts = {}) {
  // opts 供检测历史详情复用：不传时保持主页面原有行为与全局状态。
  const tableSel = opts.tableSel || '#assembly-table';
  const statusSel = opts.statusSel || '#assembly-status';
  const editorEl = opts.editorSel === null ? null : document.querySelector(opts.editorSel || '#assembly-editor');
  const components = opts.components || bomComponents;
  const legacyContains = tree.relation_semantics === 'bom_contains';
  if (editorEl) editorEl.value = JSON.stringify({nodes: tree.nodes || [], ...(tree.context_components?.length ? {context_components:tree.context_components} : {})}, null, 2);
  document.querySelector(statusSel).textContent = '已识别 ' + (tree.nodes || []).length + ' 个装配节点，最大 ' + (tree.max_depth || 0) + ' 层；' + (tree.unresolved_component_indices || []).length + ' 行尚未建立关系。' + (tree.status === 'reviewed' ? '层级已人工确认。' : tree.status === 'reviewed_partial' ? '已有关系已人工确认，未建立的关系仍待处理。' : '已识别关系仍需人工复核。');
  const assemblyComponents = [...components, ...(tree.context_components || [])];
  const names = index => { const c = assemblyComponents[index] || {}; return [c.part_number, c.name_zh || c.name_en, index >= components.length ? '标题栏总成' : ''].filter(Boolean).join(' · '); };
  const referenceName = ref => names(tree.component_refs?.[ref] ?? (ref?.startsWith('c') ? Number(ref.slice(1)) : -1)) || ref || '未知';
  const nodesById = new Map((tree.nodes || []).map(n => [n.id, n]));
  const children = new Map();
  (tree.nodes || []).forEach(n => { const key = n.parent_id ?? null; if (!children.has(key)) children.set(key, []); children.get(key).push(n); });
  const ordered = [], seen = new Set();
  function visit(parent) { for (const n of children.get(parent) || []) { if (seen.has(n.id)) continue; seen.add(n.id); ordered.push(n); visit(n.id); } }
  visit(null);
  fillTable(tableSel, ['子件','安装父件','层级','每父件用量','图面配合证据'], (legacyContains ? [] : ordered).map(n => [
    '　'.repeat(Math.min(12, Math.max(0, (n.level || 1) - 1))) + names(n.component_index),
    n.parent_id == null ? '安装基体（根）' : names(nodesById.get(n.parent_id)?.component_index), n.level,
    n.parent_id == null ? '不适用（顶层）' : (n.quantity_per_parent ?? '待确认'),
    '第' + n.source_page + '页：' + n.evidence]));
  let pending = opts.pendingSel ? document.querySelector(opts.pendingSel)
    : ($('#assembly-pending') || (() => { const d = document.createElement('details'); d.id = 'assembly-pending'; $('#assembly-table').after(d); return d; })());
  const relations = tree.unresolved_relations || [];
  const unresolved = tree.unresolved_component_indices || [];
  const unverified = tree.unverified_nodes || [];
  pending.hidden = !relations.length && !unresolved.length && !unverified.length;
  pending.innerHTML = '<summary>待核实的关系与原因（' + (relations.length + unverified.length) + '条候选，' + unresolved.length + '项归属未确认）</summary>' + relations.map(r =>
    '<p><b>' + esc(r.parent ? referenceName(r.parent) + ' → ' + referenceName(r.child) : referenceName(r.component_id) + ' 顶层身份') +
    '</b><br>' + esc(r.verification_reason) + '<br>第' + esc(r.source_page) + '页：' + esc(r.evidence) + '</p>').join('');
  pending.innerHTML += unverified.map(n => '<p><b>' + esc(names(n.component_index)) + '</b><br>' +
    esc(n.verification_reason) + '<br>原候选证据：' + esc(n.evidence) + '</p>').join('');
  if (unresolved.length) pending.innerHTML += '<p>安装归属待确认：' + unresolved.map(i => esc(names(i) || ('BOM行' + (i + 1)))).join('；') + '</p>';
  const statusEl = document.querySelector(statusSel);
  if (legacyContains) statusEl.textContent = '此历史结果仅有总成明细，尚未识别安装父子关系。请重新识别图纸；原始结果保留在高级编辑中。';
  else statusEl.textContent += ' 父件表示直接安装承载对象，根表示安装基体。';
  if (tree.warning) statusEl.textContent += ' ' + tree.warning;
  if ((tree.unverified_nodes || []).length) {
    statusEl.textContent += ' 待核实候选：' + tree.unverified_nodes.map(n =>
      'BOM行' + (n.component_index + 1) + '（' + n.verification_reason + '）').join('；');
  }
  if (tree.status === 'reviewed_with_conflicts') statusEl.textContent += ' 层级已人工复核，数量冲突仍待处理。';
  if (tree.quantity_status === 'incomplete') statusEl.textContent += ' 数量信息不足，尚不能确认展开总量一致。';
  if ((tree.quantity_conflicts || []).length) statusEl.textContent += '\n' + tree.quantity_conflicts.map(c => c.message).join('\n');
}
function refreshBomValidation(issues) {
  const panel = $('#bom-validation-issues');
  panel.classList.toggle('hidden', !issues.length);
  panel.textContent = issues.length ? 'BOM 校验提示：' + issues.join('；') : '';
}
$('#assembly-save').addEventListener('click', async () => {
  try {
    const data = await api('/api/assembly/save', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({job_id:bomJobId, bom_revision:bomRevision, reviewer:$('#assembly-reviewer').value, assembly:JSON.parse($('#assembly-editor').value)})});
    renderAssembly(data.assembly); refreshBomValidation(data.validation_issues || []);
    $('#assembly-message').textContent = '层级已保存并重新对账，JSON/Excel导出包含更新后的层级';
  } catch(error) { $('#assembly-message').textContent = error.message; }
});
$('#impact-index-save').addEventListener('click', async () => {
  try {
    const file = $('#impact-index-file').files[0];
    if (!file) throw new Error('请选择关联索引JSON');
    const result = await api('/api/impact/index', {method:'POST', headers:{'Content-Type':'application/json'}, body:await file.text()});
    $('#impact-index-message').textContent = '已导入 ' + result.objects + ' 个对象，请重新执行版本对比';
  } catch(error) { $('#impact-index-message').textContent = error.message; }
});
$('#doc-tables').addEventListener('change', event => {
  const select = event.target.closest('.doc-decision');
  if (select) docExtraction[select.dataset.section][Number(select.dataset.row)].review_status = select.value;
});
$('#doc-tables').addEventListener('click', event => {
  const button = event.target.closest('.doc-locate');
  if (!button) return;
  const row = docExtraction[button.dataset.section][Number(button.dataset.row)];
  $('#doc-source-text').textContent = row.source_text || row.source || row.location || '当前项无可定位的原文证据，请人工核查';
  const canvas = $('#doc-source-canvas');
  canvas.width = 0; canvas.height = 0;
  if (!row.source_page || !row.bbox) return;
  const image = new Image();
  image.onload = () => {
    canvas.width = image.width; canvas.height = image.height;
    const ctx = canvas.getContext('2d'); ctx.drawImage(image,0,0);
    const [x0,y0,x1,y1] = row.bbox;
    ctx.strokeStyle='#b00020'; ctx.lineWidth=3;
    ctx.strokeRect(x0*image.width,y0*image.height,(x1-x0)*image.width,(y1-y0)*image.height);
  };
  image.onerror = () => { $('#doc-source-text').textContent += '\n原图加载失败'; };
  image.src = '/api/pages/' + docJobId + '?page=' + row.source_page;
});
$('#drawing-regions').addEventListener('click', event => {
  const button = event.target.closest('.region-locate');
  if (!button) return;
  const image = new Image();
  const page = Number(button.dataset.page);
  const request = ++insImageRequest;
  clearInsSelection(); insPreviewImage = null;
  $('#ins-box-status').textContent = '正在定位；蓝框仅供查看，修订前请重新拖动框选文字';
  image.onload = () => {
    if (request !== insImageRequest) return;
    insPreviewImage = image; insPreviewPage = page;
    insRegionBox = JSON.parse(button.dataset.box);
    setInsMode('view');
    $('#ins-box-status').textContent = (button.dataset.warning || '自动范围完整性待复核') + ' 可拖动调整蓝框；文字修订请切换框选模式。';
    const canvas = $('#ins-preview'); canvas.width=image.width; canvas.height=image.height;
    $('#ins-page').value = page; drawInsPreview(); canvas.scrollIntoView({block:'center'});
  };
  image.onerror = () => { if (request === insImageRequest) { $('#ins-box-status').textContent = '区域原图加载失败，请重新定位'; showError('bom','区域原图加载失败，请重新定位'); } };
  image.src='/api/pages/' + insJobId + '?page=' + page;
});
let reviewRevision = 0;
let reviewLoadedId = '';
function displayReview(result) {
  $('#workflow-detail').open = true;
  reviewRevision = result.revision;
  $('#workflow-status').textContent = '状态：' + result.state + '；版本：' + result.revision + '\n内容指纹：' + (result.hash || '') + '\n' + (result.audit || []).map(x => x.actor + ' / ' + x.role + ' / ' + x.action).join('\n');
  if (result.payload) $('#workflow-payload').value = JSON.stringify(result.payload,null,2);
}
$('#workflow-load').onclick = async () => {
  try {
    const id = $('#workflow-id').value.trim();
    const result = await api('/api/reviews/' + encodeURIComponent(id), {headers:{'X-Review-Token':$('#workflow-token').value}});
    reviewLoadedId = id; displayReview(result);
  } catch(e) { $('#workflow-status').textContent=e.message; }
};
$('#workflow-bom').onclick = async () => {
  try {
  if (!bomJobId) throw new Error('请先在“BOM 与图纸纠错”完成识别，再载入结果');
  $('#workflow-detail').open = true;
  const job = await api('/api/jobs/' + bomJobId);
  $('#workflow-id').value = bomJobId; reviewLoadedId = ''; reviewRevision = 0;
  $('#workflow-payload').value = JSON.stringify({...job.result.bom, components:bomComponents},null,2);
  $('#workflow-status').textContent='当前BOM已载入，提交前请加载版本（已有版本会覆盖编辑框，请先保存编辑内容）';
  } catch(e) { $('#workflow-status').textContent=e.message; }
};
$('#workflow-doc').onclick = () => {
  if (!docJobId) { $('#workflow-status').textContent='请先在“文档要素与复核”完成提取，再载入结果'; return; }
  $('#workflow-detail').open = true;
  $('#workflow-id').value=docJobId; reviewLoadedId=''; reviewRevision=0;
  $('#workflow-payload').value=JSON.stringify(docExtraction,null,2);
};
document.querySelectorAll('[data-review-action]').forEach(button => button.onclick = async () => {
  try {
    const id=$('#workflow-id').value.trim();
    if (reviewLoadedId !== id) {
      const current=await api('/api/reviews/' + encodeURIComponent(id), {headers:{'X-Review-Token':$('#workflow-token').value}});
      if (current.revision) throw new Error('已有版本，请先加载并审查内容');
      reviewLoadedId=id; reviewRevision=0;
    }
    const action=button.dataset.reviewAction;
    const result=await api('/api/reviews/transition',{method:'POST',headers:{'Content-Type':'application/json','X-Review-Token':$('#workflow-token').value},body:JSON.stringify({document_id:id,revision:reviewRevision,action,payload:JSON.parse($('#workflow-payload').value)})});
    displayReview(result);
  } catch(e) { $('#workflow-status').textContent=e.message; }
});
$('#enterprise-save').onclick = async () => {
  try {
    const file=$('#enterprise-file').files[0];
    if (!file) throw new Error('请选择企业配置JSON');
    await api('/api/enterprise/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:await file.text()});
    $('#enterprise-message').textContent='已保存，下一次任务生效';
  } catch(e) { $('#enterprise-message').textContent=e.message; }
};
['json','csv','xlsx'].forEach(fmt => $('#enterprise-'+fmt).onclick = () => {
  if (!bomJobId) { $('#enterprise-message').textContent='请先完成BOM识别'; return; }
  window.open('/api/export/bom/'+bomJobId+'?profile=enterprise&fmt='+fmt,'_blank');
});
