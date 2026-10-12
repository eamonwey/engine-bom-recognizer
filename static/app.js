/* 发动机元器件 BOM 智能识别系统 - 前端逻辑（无框架依赖） */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const API_TOKEN = document.querySelector('meta[name="api-token"]')?.content || "";

/* ───────── 导航与状态 ───────── */
$("#nav").addEventListener("click", (e) => {
  const a = e.target.closest("a[data-view]");
  if (!a) return;
  $$("#nav a").forEach((x) => x.classList.remove("active"));
  a.classList.add("active");
  $$(".view").forEach((v) => v.classList.remove("active"));
  $("#view-" + a.dataset.view).classList.add("active");
  if (a.dataset.view === "review") loadReview();
  if (a.dataset.view === "dethistory") loadDetectionHistory();
  if (a.dataset.view === "settings") loadStatus();
});

async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {}, { "X-API-Token": API_TOKEN });
  const resp = await fetch(path, Object.assign({}, opts, { headers }));
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || ("HTTP " + resp.status));
  return data;
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const model = s.model || "(未配置)";
    $("#status-line").innerHTML =
      "模型: <b>" + esc(model) + "</b><br>Provider: " + esc(s.provider || "") +
      (s.preprocess_available ? " · 预处理可用" : "") +
      (s.provider === "openai_compat" && !s.api_key_set ? "<br><span style='color:#e8a'>⚠ API Key 未设置</span>" : "");
  } catch (e) {
    $("#status-line").textContent = "服务未连接";
  }
}

/* ───────── 任务轮询 ───────── */
function pollJob(jobId, onDone, owner = currentView()) {
  let pending = false;
  const timer = setInterval(async () => {
    if (pending) return;
    pending = true;
    try {
      const job = await api("/api/jobs/" + jobId);
      if (job.status === "done") { clearInterval(timer); onDone(job.result); }
      else if (job.status === "failed") {
        clearInterval(timer);
        throw new Error(job.error || "任务失败");
      }
    } catch (e) { clearInterval(timer); showError(owner, e.message); hideProgress(owner); }
    finally { pending = false; }
  }, 1500);
}

const currentView = () => $("#nav a.active").dataset.view;
const resultView = v => v === "inspect" ? "bom" : v;
const showError = (v, msg) => { const el = $("#view-" + resultView(v) + " .alert.error"); el.textContent = "❌ " + msg; el.classList.remove("hidden"); };
const hideError = (v) => $("#view-" + resultView(v) + " .alert.error").classList.add("hidden");
const showProgress = (v) => $("#view-" + resultView(v) + " .progress").classList.remove("hidden");
const hideProgress = (v) => $("#view-" + resultView(v) + " .progress").classList.add("hidden");

/* ───────── 通用上传控件 ───────── */
function bindDrop(dropSel, inputSel, onFile = () => {}) {
  const drop = $(dropSel), input = $(inputSel);
  drop.setAttribute("role", "button");
  drop.tabIndex = 0;
  drop.addEventListener("click", (e) => { if (e.target !== input && !input.disabled) input.click(); });
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (!input.disabled) input.click(); }
  });
  const updateFile = () => {
    const file = input.files[0];
    drop.classList.add("has-file");
    drop.querySelector(".drop-title").textContent = file.name;
    drop.querySelector(".file-meta").textContent = (file.size / 1024 / 1024).toFixed(2) + " MB · 点击更换文件";
    onFile(file);
  };
  input.addEventListener("change", () => {
    if (input.files.length) {
      updateFile();
    }
  });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    if (e.dataTransfer.files.length && !input.disabled) {
      input.files = e.dataTransfer.files;
      updateFile();
    }
  });
}

/* ───────── BOM 识别 ───────── */
let bomJobId = null, bomComponents = [], BOM_COLS = null, bomRevision = 0;
bindDrop("#bom-drop", "#bom-file", () => {
  bomJobId = null; insJobId = null; insSourceSha = null; insPreviewImage = null; insSelectedBox = null;
  insRegionBox = null; insImageRequest++; insDragStart = null;
  $("#bom-result").classList.add("hidden");
  $("#ins-correct-download").classList.add("hidden");
  $("#ins-reviewed").value = "";
  $("#ins-page").value = "1";
});

$("#bom-start").addEventListener("click", async () => {
  const file = $("#bom-file").files[0];
  if (!file) return showError("bom", "请先选择图纸文件");
  hideError("bom"); showProgress("bom");
  $("#bom-result").classList.add("hidden");
  const fd = new FormData();
  fd.append("file", file);
  fd.append("options", JSON.stringify({
    provider: $("#bom-provider").value || null,
    preprocess: {
      deskew: $("#bom-pre-deskew").checked,
      denoise: $("#bom-pre-denoise").checked,
      binarize: $("#bom-pre-binarize").checked,
    },
  }));
  try {
    const { job_id } = await api("/api/jobs/bom", { method: "POST", body: fd });
    bomJobId = job_id; insJobId = job_id;
    pollJob(job_id, renderBomResult, "bom");
  } catch (e) { showError("bom", e.message); hideProgress("bom"); }
});

function renderBomResult(res) {
  hideProgress("bom");
  $("#bom-result").classList.remove("hidden");
  renderKV("#bom-titleblock", res.title_block || {});
  $('#bom-result .badge').textContent = res.model_info?.provider === 'mock' ? '离线演示数据 · 与上传内容无关，不可用于准确率验收' : '识别结果 · 待人工复核';
  const warnings = res.title_block?.extraction_warnings || [];
  if (warnings.length) $('#bom-titleblock').insertAdjacentHTML('beforeend', '<p class="alert error">标题栏证据校验未通过：' + esc(warnings.join('；')) + '</p>');
  bomComponents = res.bom.components;
  bomRevision = res.bom.revision || 0;
  const vissues = res.bom.validation_issues || [];
  const vi = $("#bom-validation-issues");
  if (vi) {
    vi.classList.toggle("hidden", !vissues.length);
    vi.textContent = vissues.length ? "BOM 校验提示：" + vissues.join("；") : "";
  }
  renderAssembly(res.bom.assembly || {nodes: []});
  const regionLabels = {frame:'图框',title_block:'标题栏',bom_table:'明细栏',technical_notes:'技术要求',view:'视图'};
  $('#drawing-regions').innerHTML = (res.layout?.regions || []).map(r =>
    '<button class="region-locate" data-page="' + esc(r.source_page) + '" data-box="' + esc(JSON.stringify(r.bbox)) + '" data-warning="' + esc(r.bbox_warning || '模型粗定位，范围完整性待复核') + '" title="' + esc(r.evidence) + '">' + esc(regionLabels[r.kind] || r.kind) + ' · 第' + esc(r.source_page) + '页 · ' + esc(r.bbox_status === 'refined' ? '已补边（待复核）' : r.bbox_status === 'uncertain' ? '范围待调整' : '待复核') + '</button>').join('') || '区域尚未定位，仍可使用下方原图进行人工复核';
  BOM_COLS = [...new Set([...Object.keys(BOM_LABELS), ...bomComponents.flatMap(comp => Object.keys(comp))])]
    .filter(c => !HIDDEN_COLS.has(c));
  renderBomTable();
  const issues = res.issues || [];
  $("#bom-issues-count").textContent = issues.length;
  renderIssues("#bom-issues", issues);
  insSourceSha = res.source_sha256;
  $("#combined-visual-status").textContent = res.inspection && res.inspection.visual_status === "validated"
    ? "视觉回复已通过结构与检查清单校验，不代表无漏检；问题和检查依据均需人工复核。" : "视觉审图未完成或未启用，当前问题清单不代表完整审图。";
  let coveragePanel = $('#inspection-coverage');
  if (!coveragePanel) {
    coveragePanel = document.createElement('details'); coveragePanel.id = 'inspection-coverage'; coveragePanel.className = 'card';
    $('#combined-visual-status').after(coveragePanel);
  }
  coveragePanel.innerHTML = renderInspectionCoverage(res);
  fillTable("#combined-dims", ["尺寸代号", "数值", "视图"], (res.dimensions || []).map(d => [d.tag || "", d.value || "", d.view || ""]));
  $("#ins-preview-load").click();
  $$('#view-bom [data-dl]').forEach(b =>
    b.dataset.dl = "/api/export/bom/" + bomJobId + "?fmt=" + new URL(b.dataset.dl, location.origin).searchParams.get("fmt"));
}

function renderInspectionCoverage(res) {
  // 审图覆盖/专项规则/尺寸链证据 —— 主页面与检测历史详情共用。
  const stateLabels = {checked:'有检查结果（待复核）', uncertain:'依据不足', not_applicable:'不适用', insufficient_dimensions:'尺寸不足，未执行', needs_review:'校验未通过', provider_failed:'模型调用失败', not_run:'未执行'};
  const chain = res.inspection?.dimension_chains;
  const engineering = res.inspection?.engineering;
  const dimensionExtraction = res.inspection?.dimension_extraction;
  const links = res.inspection?.dimension_links;
  const stageNames = {primary_visual:'整页视觉审图',engineering_facts:'专项事实提取',dimension_links:'尺寸与配合对应复核',focus_sweep:'局部防漏复查'};
  const stageLabels = {...stateLabels,validated:'回复校验通过，仍需复核',partial:'部分事实可用，仍有待核实事实',checked:'已定位并比较，仍需复核',insufficient_evidence:'未找到可确认对应，不能认定无问题'};
  const stageHtml = Object.entries(res.inspection?.stages || {}).map(([key,value]) => '<p><b>' + esc(stageNames[key] || key) + '：</b>' + esc(stageLabels[value] || value) + '</p>').join('');
  const repeat = res.run_consistency;
  const repeatFields = {bom:'BOM字段或数量',assembly:'安装父子关系或每父用量',dimension_count:'尺寸读取数量',finding_types:'问题类型或数量'};
  const repeatHtml = repeat ? '<details><summary>同一文件重复检测：' + esc(({disagreement:'结果存在差异，需回图复核',consistent_summary:'摘要一致，仍不能证明正确',no_reference:'无历史参考'})[repeat.status] || repeat.status) + '</summary><p>' + esc(repeat.warning) + '</p>' +
    (repeat.references || []).map(r => '<p>检测记录 ' + esc(r.job_id) + '：' + esc(r.different_fields.length ? r.different_fields.map(f => repeatFields[f] || f).join('、') + '不同' : '摘要一致') + '</p>').join('') + '</details>' : '';
  const linkHtml = links ? '<details><summary>尺寸与配合对应：' + esc(stageLabels[links.status] || links.status) + '</summary>' +
    (links.local_text ? '<details><summary>本地尺寸文字定位：' + esc(({read:'已读取，仍需回图核实',not_available:'本地组件不可用',no_readable_fit_text:'未读到可用配合文字'})[links.local_text.status] || links.local_text.status) + '</summary><p>' + esc(links.local_text.warning) + '</p>' +
      (links.local_text.observations || []).map(o => '<p>第' + esc(o.source_page) + '页 · 原文 ' + esc(o.raw_text) + ' · 位置 ' + esc(JSON.stringify(o.bbox)) + '</p>').join('') + '</details>' : '') +
    (links.micro_text ? '<details><summary>局部文字回读（视觉模型）：' + esc(stageLabels[links.micro_text.status] || links.micro_text.status) + '</summary><p>' + esc(links.micro_text.warning) + '</p>' +
      (links.micro_text.observations || []).map(o => '<p>第' + esc(o.source_page) + '页 · 局部原文 ' + esc(o.raw_text) + ' · 位置 ' + esc(JSON.stringify(o.bbox)) + (o.fit_unreadable ? ' · 公差代号未确认，未自动补全' : '') + '</p>').join('') + '</details>' : '') +
    (links.fit_text_unverified || []).map(o => '<p>公差文字待核实：' + esc(o.local_text_evidence?.raw_text || o.value) + '；这里只核对清晰的名义数字，没有确认公差字母。</p>').join('') +
    (links.unmapped_text || []).map(o => '<p>局部文字尚未确定实体对象：' + esc(o.id) + ' · ' + esc(o.reason) + '</p>').join('') +
    (links.issues || []).map(i => '<p><b>' + esc(i.message) + '</b><br>' + (i.linked_dimensions || []).map(d => '第' + esc(d.source_page) + '页 · ' + esc(d.view) + ' · ' + esc(d.feature) + '：' + esc(d.value) + '（位置 ' + esc(JSON.stringify(d.bbox)) + '）').join('<br>') + '<br>' + esc(i.evidence) + '</p>').join('') +
    (links.unverified_links || []).map(l => '<p>待核实：' + esc(l.evidence || l.link?.evidence || '对应关系无效') + '<br>' + esc(l.verification_reason) + '</p>').join('') +
    (links.rejected_observations || []).map(o => '<p>尺寸观察待核实：' + esc(o.observation?.value || '无有效原文') + '<br>' + esc((o.reasons || []).join('；')) + '</p>').join('') + '</details>' : '';
  const checkLabels = {checked:'该项规则已计算', issue:'发现问题候选', uncertain:'待核实', not_applicable:'该项不适用'};
  return '<p class="hint">规则验证已提取的事实；事实和对应关系仍需对照原图复核。没有问题不代表全图合格。</p>' + repeatHtml + stageHtml + linkHtml + '<p>尺寸链：' + esc(stateLabels[chain?.status] || '本次结果未提供') + '</p><p>' + esc(chain?.evidence || '') + '</p>' +
    (dimensionExtraction && dimensionExtraction.status !== 'validated' ? '<p id="dimension-extraction-warning">尺寸抽取校验未通过，本次没有可信尺寸输入；请重新识别或人工核实。' + esc((dimensionExtraction.warnings || []).join('；')) + '</p>' : '') +
    renderToleranceChainEvidence(chain, stateLabels) +
    Object.entries(res.inspection?.checklist || {}).map(([code, item]) => '<p><b>' + esc(code) + ' · ' + esc(stateLabels[item.status] || item.status) + '</b> ' + esc(item.evidence) + '</p>').join('') +
    (engineering ? '<p>标准状态快照：' + esc(engineering.standards_snapshot_date) + '（非实时标准库）</p>' +
      (engineering.warning ? '<p>' + esc(engineering.warning) + '</p>' : '') +
      Object.entries(engineering.coverage || {}).map(([code, item]) => '<p><b>' + esc(code) + '</b> 已计算 ' + esc(item.checked) + ' 项 · 问题候选 ' + esc(item.issues) + ' 项 · 待核实 ' + esc(item.uncertain) + ' 项</p>').join('') +
      '<details><summary>逐条查看专项规则、原文与计算值</summary>' + (engineering.checks || []).map(item => '<p><b>' + esc(item.err_id) + ' · ' + esc(checkLabels[item.status] || item.status) + '</b> ' + esc(item.message) + '<br>位置：' + esc(item.location || '待定位') + ' · 页码：' + esc(item.source_page || '未确认') + '<br>原文证据：' + esc(item.evidence || '未提供') + (item.calculation ? '<br>计算记录：' + esc(JSON.stringify(item.calculation)) : '') + '</p>').join('') + '</details>' : '') +
    (res.inspection?.unverified_findings || []).map(item => '<p><b>' + esc(item.err_id || '') + ' 未确认观察（不计为已验证错误）</b> ' + esc(item.message) + '<br>' + esc(item.verification_reason) + '</p>').join('');
}

function renderToleranceChainEvidence(report, stateLabels) {
  if (!report) return '';
  const labels = {within_limits:'极限范围满足本项要求（待复核）', may_exceed_limits:'部分极限组合可能超差', outside_limits:'全范围不满足本项要求'};
  return '<section id="tolerance-chain-evidence"><h3>装配公差尺寸链</h3><p>' + esc(stateLabels[report.tolerance_status] || '本次未提供公差链检查') + ' · ' + esc(report.tolerance_evidence || '') + '</p>' +
    '<p class="hint">按明确标注的公差计算一维极限组合；未注公差不会按零公差处理。计算结果依赖原文和装配界面识别，不代表全图合规或每件实物都会超差。</p>' +
    (report.tolerance_chains || []).map((chain, i) => '<details class="tolerance-chain"><summary>尺寸链 ' + (i + 1) + ' · ' + esc(labels[chain.conformance] || '待核实') + (chain.at_boundary ? ' · 恰好达到允许边界' : '') + '</summary>' +
      '<p><b>' + esc(chain.display_formula || chain.formula) + '</b><br>第 ' + esc(chain.source_page) + ' 页 · ' + esc(chain.view) + '</p>' +
      '<p>封闭环极限范围：<b>[' + esc(chain.minimum_mm) + ', ' + esc(chain.maximum_mm) + '] mm</b><br>允许范围：[' + esc(chain.allowed_min_mm) + ', ' + esc(chain.allowed_max_mm) + '] mm<br>名义计算值：' + esc(chain.nominal_mm === null ? '原文未提供全部名义值' : chain.nominal_mm + ' mm') + '<br>累积公差宽度：' + esc(chain.tolerance_width_mm) + ' mm<br>下限裕量：' + esc(chain.lower_margin_mm) + ' mm · 上限裕量：' + esc(chain.upper_margin_mm) + ' mm（负数表示超出）</p>' +
      '<div class="table-wrap"><table><thead><tr><th>组成尺寸</th><th>原文</th><th>增/减环</th><th>下极限 mm</th><th>上极限 mm</th><th>对封闭环的贡献 mm</th></tr></thead><tbody>' +
      (chain.terms || []).map(term => '<tr>' + [term.label, term.original_value, term.role, term.lower_mm, term.upper_mm, '[' + term.contribution_min_mm + ', ' + term.contribution_max_mm + ']'].map(v => '<td>' + esc(v) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>' +
      '<p>装配要求原文：' + esc(chain.requirement_evidence) + '<br>端点关系证据：' + esc(chain.evidence) + '</p><p class="hint">请对照原图复核增减环、公差和功能要求；系统不自动指定应修改的尺寸。</p></details>').join('') +
    (report.unresolved_chains || []).map(item => '<p>待核实的功能要求：' + esc(item.requirement_value) + ' · 第 ' + esc(item.source_page) + ' 页<br>原因：' + esc(item.reason) + '</p>').join('') +
    (report.validation_errors || []).map(error => '<p>未完成原因：' + esc(error) + '</p>').join('') + '</section>';
}

const BOM_LABELS = { item_no: "序号", part_number: "图号/件号", name_zh: "名称(中文)", name_en: "名称(英文)",
  category: "功能系统", specification: "规格型号", material: "材料", quantity: "数量", weight: "重量(g)", unit: "单位",
  position: "装配位置", supplier: "供应商", remark: "备注", source_page: "来源页" };
const EDITABLE = new Set(["part_number", "name_zh", "name_en", "category", "specification",
  "material", "quantity", "weight", "unit", "position", "supplier", "remark"]);
const NUMERIC_COLS = new Set(["quantity", "weight", "item_no"]);
const HIDDEN_COLS = new Set(["needs_review", "review_reasons", "confidence"]);

function renderBomTable() {
  const t = $("#bom-table");
  const cols = BOM_COLS;
  let html = "<tr>" + cols.map(c => "<th>" + (BOM_LABELS[c] || c) + "</th>").join("") + "</tr>";
  bomComponents.forEach((comp, i) => {
    const reasons = (comp.review_reasons || []).join("\n");
    const flagged = comp.needs_review && reasons;
    html += "<tr" + (flagged ? ' class="row-review" title="' + esc(reasons) + '"' : "") + ">" + cols.map((c, ci) => {
      const v = comp[c] === null || comp[c] === undefined ? "" : comp[c];
      const badge = (flagged && ci === 0) ? '<span class="review-flag" title="' + esc(reasons) + '">⚠</span> ' : "";
      if (EDITABLE.has(c)) return "<td class=\"editable\">" + badge + '<span contenteditable="true" data-i="' + i + '" data-c="' + c + '">' + esc(v) + '</span></td>';
      return "<td>" + badge + esc(v) + "</td>";
    }).join("") + "</tr>";
  });
  t.innerHTML = html;
  t.oninput = (e) => {
    const td = e.target;
    if (td.dataset.i === undefined) return;
    const i = +td.dataset.i, c = td.dataset.c;
    bomComponents[i][c] = NUMERIC_COLS.has(c) ? (td.textContent.trim() === "" ? null : Number(td.textContent)) : td.textContent.trim();
    if (NUMERIC_COLS.has(c) && td.textContent.trim() !== '' && !Number.isFinite(Number(td.textContent))) bomComponents[i][c] = td.textContent.trim();
  };
}

$("#bom-save").addEventListener("click", async () => {
  if (!bomComponents.length) return;
  try {
    const r = await api("/api/bom/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: bomJobId, document_id: "web_" + bomJobId, components: bomComponents, comment: "网页复核" }),
    });
    bomRevision = r.bom.revision || 0;
    bomComponents = r.bom.components;
    renderBomTable();
    renderAssembly(r.bom.assembly || {nodes: []});
    refreshBomValidation(r.bom.validation_issues || []);
    $("#bom-save-msg").textContent = "已保存编辑稿；BOM变化会清除旧层级，请重新复核。正式批准请到“复核与历史”";
    $("#bom-save-msg").classList.remove("hidden");
  } catch (e) { showError("bom", e.message); }
});

/* ───────── 文档要素提取 ───────── */
let docJobId = null, docExtraction = null;
bindDrop("#doc-drop", "#doc-file");

$("#doc-start").addEventListener("click", async () => {
  const file = $("#doc-file").files[0];
  if (!file) return showError("doc", "请先选择文档文件");
  hideError("doc"); showProgress("doc");
  $("#doc-result").classList.add("hidden");
  const fd = new FormData();
  fd.append("file", file);
  if ($("#doc-provider").value) fd.append("provider", $("#doc-provider").value);
  try {
    const { job_id } = await api("/api/jobs/doc", { method: "POST", body: fd });
    docJobId = job_id;
    pollJob(job_id, renderDocResult, "doc");
  } catch (e) { showError("doc", e.message); hideProgress("doc"); }
});

const DOC_SECTIONS = [
  ["tech_params", "技术参数", ["参数名", "数值", "单位", "适用条件", "来源"]],
  ["materials", "材料要求", ["名称", "牌号", "规格", "标准", "热/表面处理"]],
  ["process_requirements", "工艺要求", ["类型", "内容", "位置"]],
  ["inspection", "检验标准", ["检验项目", "方法", "验收标准", "引用标准"]],
];
const DOC_KEYS = {
  tech_params: ["name", "value", "unit", "condition", "source"],
  materials: ["name", "brand", "spec", "standard", "treatment"],
  process_requirements: ["type", "content", "location"],
  inspection: ["item", "method", "criteria", "standard"],
};

function renderDocResult(res) {
  hideProgress("doc");
  $("#doc-result").classList.remove("hidden");
  docExtraction = res.extraction;
  $('#doc-status').textContent = (docExtraction.warnings || []).join('；') || '逐段抽取完成，结果待人工复核';
  if (res.model?.provider === 'mock') $('#doc-status').textContent = '离线演示数据 · 与上传内容无关，不可用于准确率验收';
  const wrap = $("#doc-tables");
  wrap.innerHTML = "";
  DOC_SECTIONS.forEach(([key, title, labels]) => {
    const rows = docExtraction[key] || [];
    const card = document.createElement("div");
    card.className = "card";
    const keys = DOC_KEYS[key];
    let html = "<h2>" + title + "（" + rows.length + "）</h2>";
    if (!rows.length) { html += '<div class="empty">未提取到内容</div>'; }
    else {
      html += '<div class="table-wrap"><table><tr>' + labels.map(l => "<th>" + l + "</th>").join("") + '<th>来源与复核</th></tr>';
      rows.forEach((row, i) => {
        html += "<tr>" + keys.map(k =>
          '<td contenteditable class="editable" data-k="' + key + '" data-i="' + i + '" data-c="' + k + '">' +
          esc(row[k] === undefined || row[k] === null ? "" : row[k]) + "</td>").join("") +
          '<td><button class="doc-locate" data-section="' + key + '" data-row="' + i + '">定位原文</button>' +
          '<select class="doc-decision" data-section="' + key + '" data-row="' + i + '">' +
          ['pending','confirmed','rejected'].map((state,j) => '<option value="' + state + '"' + ((row.review_status || 'pending') === state ? ' selected' : '') + '>' + ['待复核','确认','驳回'][j] + '</option>').join('') + '</select></td></tr>';
      });
      html += "</table></div>";
    }
    card.innerHTML = html;
    wrap.appendChild(card);
  });
  wrap.oninput = (e) => {
    const td = e.target.closest("td[data-k]");
    if (!td) return;
    docExtraction[td.dataset.k][+td.dataset.i][td.dataset.c] = td.textContent.trim();
  };
  $$('#view-doc [data-dl]').forEach(b => b.dataset.dl = "/api/export/doc/" + docJobId + "?fmt=" + new URL(b.dataset.dl, location.origin).searchParams.get("fmt"));
}

$("#doc-save").addEventListener("click", async () => {
  if (!docExtraction) return;
  try {
    await api("/api/doc/save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: docJobId, file_name: "web_" + docJobId, extraction: docExtraction, comment: "网页复核" }),
    });
    $("#doc-save-msg").textContent = "已保存复核结果 ✓";
    $("#doc-save-msg").classList.remove("hidden");
  } catch (e) { showError("doc", e.message); }
});

/* ───────── 文件对比 ───────── */
let cmpJobId = null, cmpItems = [];
bindDrop("#cmp-before", "#cmp-file-before");
bindDrop("#cmp-after", "#cmp-file-after");
$("#cmp-filter").addEventListener("change", renderCmpItems);

$("#cmp-start").addEventListener("click", async () => {
  const a = $("#cmp-file-before").files[0], b = $("#cmp-file-after").files[0];
  if (!a || !b) return showError("compare", "请选择变更前后两个版本的文件");
  hideError("compare"); showProgress("compare");
  const fd = new FormData();
  fd.append("before", a);
  fd.append("after", b);
  fd.append("ignore_format", $("#cmp-ignore-format").checked ? "true" : "false");
  try {
    const { job_id } = await api("/api/jobs/compare", { method: "POST", body: fd });
    cmpJobId = job_id;
    pollJob(job_id, renderCmpResult, "compare");
  } catch (e) { showError("compare", e.message); hideProgress("compare"); }
});

function renderCmpResult(res) {
  hideProgress("compare");
  $("#compare-empty").classList.add("hidden");
  $("#cmp-result").classList.remove("hidden");
  const s = res.summary || { total: 0, by_type: { added: 0, removed: 0, modified: 0 } };
  $("#cmp-summary").innerHTML =
    '<span class="chip">共 <b>' + s.total + "</b> 处变更</span>" +
    '<span class="chip">新增 <b>' + s.by_type.added + '</b></span>' +
    '<span class="chip">删除 <b>' + s.by_type.removed + '</b></span>' +
    '<span class="chip">修改 <b>' + s.by_type.modified + '</b></span>';
  cmpItems = res.items || [];
  renderCmpItems();
  const imp = res.impact || null;
  $("#impact-status").textContent = imp
    ? (imp.status === "not_configured" ? (imp.coverage || "尚未导入企业关联索引")
       : "命中 " + (imp.objects || []).length + " 个受影响对象（共索引 " + (imp.indexed_objects || 0) + " 个）；" + (imp.coverage || ""))
    : "未导入企业关联索引，无法判定影响范围";
  $("#impact-results").innerHTML = imp ? (imp.objects || []).map(o =>
    '<div class="diff-item modified"><span class="tag">' + esc(o.severity || "中") + '</span><b>' + esc(o.name || o.id) + '</b>' +
    (o.kind ? '<span class="cat">' + esc(o.kind) + '</span>' : '') +
    (o.reasons || []).map(r => '<p>变更 #' + (r.change_index + 1) + '，命中：' + esc(r.matched_terms.join('、')) +
      '；依赖路径：' + esc(r.dependency_path.join(' → ')) + '</p>').join('') + '</div>').join('') : '';
}

function renderCmpItems() {
  const f = $("#cmp-filter").value;
  const list = cmpItems.filter(it => !f || it.type === f);
  $("#cmp-items").innerHTML = list.map(it => {
    const body = it.type === "modified"
      ? '<span class="old">' + esc(it.before || "") + '</span> → <span class="new">' + esc(it.after || "") + '</span>'
      : esc(it.type === "added" ? (it.after || "") : (it.before || ""));
    const loc = [it.location_before, it.location_after].filter(Boolean).join(" → ");
    return '<div class="diff-item ' + esc(it.type) + '"><span class="tag">' + esc(it.label || it.type) + '</span>' +
      (it.category ? '<span class="cat">' + esc(it.category) + '</span>' : '') + body +
      (loc ? '<span class="loc">' + esc(loc) + '</span>' : '') + '</div>';
  }).join("") || '<div class="empty">该筛选条件下没有变更</div>';
}

$("#cmp-ecn").addEventListener("click", () => {
  window.open("/api/compare/" + cmpJobId + "/ecn.md", "_blank");
});

/* ───────── 图纸检查 ───────── */
let insJobId = null;
let insPreviewImage = null, insSelectedBox = null, insDragStart = null, insPreviewPage = null;
let insRegionBox = null, insImageRequest = 0;
let insDragMode = 'text';
let insSourceSha = null;
function setInsMode(mode) {
  insDragMode = mode;
  insSelectedBox = null; insDragStart = null;
  $('#ins-reviewed').value = '';
  $('#ins-mode-view').setAttribute('aria-pressed', String(mode === 'view'));
  $('#ins-mode-text').setAttribute('aria-pressed', String(mode === 'text'));
  $('#ins-box-status').textContent = mode === 'view' ? '拖动调整蓝框，仅用于本次查看；不会用于修订文字。' : '拖动框选修订文字，红框内的内容会被替换。';
  drawInsPreview();
}
$('#ins-mode-view').addEventListener('click', () => setInsMode('view'));
$('#ins-mode-text').addEventListener('click', () => setInsMode('text'));
function clearInsSelection() {
  insSelectedBox = null; insRegionBox = null; insDragStart = null;
  $('#ins-reviewed').value = '';
  insDragMode = 'text';
  $('#ins-mode-view').setAttribute('aria-pressed','false');
  $('#ins-mode-text').setAttribute('aria-pressed','true');
  $('#ins-correct-download').classList.add('hidden');
}
function insCanvasPosition(event) {
  const rect = $("#ins-preview").getBoundingClientRect();
  return [Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),
          Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))];
}
function drawInsPreview() {
  if (!insPreviewImage) return;
  const canvas = $("#ins-preview"), context = canvas.getContext("2d");
  context.clearRect(0,0,canvas.width,canvas.height);
  context.drawImage(insPreviewImage,0,0);
  if (insRegionBox) {
    const [x0,y0,x1,y1] = insRegionBox;
    context.strokeStyle = '#195db7'; context.lineWidth = 3;
    context.strokeRect(x0*canvas.width,y0*canvas.height,(x1-x0)*canvas.width,(y1-y0)*canvas.height);
  }
  if (insSelectedBox) {
    const [x0,y0,x1,y1] = insSelectedBox;
    context.strokeStyle = "#b00020"; context.lineWidth = 3;
    context.strokeRect(x0*canvas.width,y0*canvas.height,(x1-x0)*canvas.width,(y1-y0)*canvas.height);
  }
}
$("#ins-preview-load").addEventListener("click", () => {
  if (!insJobId) return;
  const page = Number($("#ins-page").value);
  const request = ++insImageRequest;
  clearInsSelection(); insPreviewImage = null;
  const image = new Image();
  image.onload = () => {
    if (request !== insImageRequest) return;
    insPreviewImage = image; insSelectedBox = null; insPreviewPage = page;
    const canvas = $("#ins-preview"); canvas.width = image.width; canvas.height = image.height;
    $("#ins-box-status").textContent = "请拖动框选需要修改的文字"; applyInsZoom(); drawInsPreview();
  };
  image.onerror = () => { if (request === insImageRequest) showError("inspect","无法加载原图，请检查页码"); };
  image.src = "/api/pages/" + insJobId + "?page=" + page;
});
$("#ins-preview").addEventListener("pointerdown", (event) => {
  if (!insPreviewImage) return;
  insSelectedBox = null; insRegionBox = null;
  insDragStart = insCanvasPosition(event); event.currentTarget.setPointerCapture(event.pointerId);
});
$("#ins-preview").addEventListener("pointermove", (event) => {
  if (!insDragStart) return;
  const end = insCanvasPosition(event);
  const box = [Math.min(insDragStart[0],end[0]),Math.min(insDragStart[1],end[1]),
                    Math.max(insDragStart[0],end[0]),Math.max(insDragStart[1],end[1])];
  if (insDragMode === 'view') insRegionBox = box;
  else insSelectedBox = box;
  drawInsPreview();
});
$("#ins-preview").addEventListener("pointerup", () => {
  insDragStart = null;
  if (insDragMode === 'view') {
    if (insRegionBox && (insRegionBox[2] <= insRegionBox[0] || insRegionBox[3] <= insRegionBox[1])) insRegionBox = null;
    $('#ins-box-status').textContent = insRegionBox ? '蓝框已临时调整；仅用于查看，重新定位会恢复自动范围。' : '尚未选择查看范围';
    return;
  }
  if (insSelectedBox && (insSelectedBox[2] <= insSelectedBox[0] || insSelectedBox[3] <= insSelectedBox[1])) insSelectedBox = null;
  $("#ins-box-status").textContent = insSelectedBox ? "已框选，请确认范围和修正值" : "尚未框选";
});
$('#ins-preview').addEventListener('pointercancel', () => { clearInsSelection(); drawInsPreview(); $('#ins-box-status').textContent='框选已取消，请重新框选文字'; });
$("#ins-correct").addEventListener("click", async () => {
  try {
    if (insDragMode === 'view') throw new Error('当前为蓝框查看模式；请先切换“框选文字修订范围”并确认文字。');
    const file = $("#bom-file").files[0];
    if (!file) throw new Error("请先选择原图纸");
    const advanced = $("#ins-reviewed").value.trim();
    if (!advanced && !insSelectedBox) throw new Error("请先框选需要修改的文字");
    const reviewed = advanced ? JSON.parse(advanced) : {
      reviewer:$("#ins-reviewer").value.trim(), patches:[{approved:true,source_page:insPreviewPage,
        bbox:insSelectedBox,old_text:$("#ins-old-text").value,new_text:$("#ins-new-text").value,
        expected_source_sha256:insSourceSha}]
    };
    const fd = new FormData();
    fd.append("file", file); fd.append("reviewed", JSON.stringify(reviewed));
    hideError("inspect"); showProgress("inspect");
    const {job_id} = await api("/api/jobs/correct", {method:"POST",body:fd});
    pollJob(job_id, () => {
      hideProgress("inspect");
      const link = $("#ins-correct-download");
      link.href = "/api/corrections/" + job_id; link.classList.remove("hidden");
    }, "bom");
  } catch (e) { $('#ins-box-status').textContent = '修订未生成：' + e.message; $('#ins-box-status').scrollIntoView({block:'center'}); showError("inspect", e.message); hideProgress("inspect"); }
});

/* ───────── 复核与历史 ───────── */
async function loadReview() {
  try {
    const rl = await api("/api/reviewlog");
    fillTable("#review-table", ["时间", "动作", "对象", "操作人", "备注"],
      rl.records.map(r => [r.time, r.action, r.document_id || r.file_name || "-", r.editor || "-", r.comment || "-"]));
    const h = await api("/api/history");
    fillTable("#history-table", ["时间", "动作", "文件", "变更数", "新增/删除/修改"],
      h.records.map(r => [r.time, r.action, r.file_name || "-",
        (r.summary && r.summary.total) || "-", r.summary ? (r.summary.by_type.added + "/" + r.summary.by_type.removed + "/" + r.summary.by_type.modified) : "-"]));
  } catch (e) { /* 静默 */ }
}

/* ───────── 设置 ───────── */
async function loadStatus() {
  try {
    const s = await api("/api/status");
    $("#cfg-provider").value = s.provider;
    $("#cfg-base-url").value = s.base_url || "";
    $("#cfg-model").value = s.model || "";
    $("#cfg-api-key").value = "";
    $("#cfg-key-hint").textContent = s.api_key_set
      ? (s.api_key_source === "config"
        ? "✅ 已保存 API Key（网页配置）。输入新值可覆盖；点「清除已保存的 Key」可删除。"
        : "✅ 正在使用服务端环境变量 " + (s.api_key_env_name || "VISION_API_KEY") + " 中的 API Key。")
      : "⚠ 尚未设置 API Key，请在上方填写后保存，或设置服务端环境变量 " +
        (s.api_key_env_name || "VISION_API_KEY") + "。";
    renderKV("#cfg-status", {
      版本: "v" + s.version, Provider: s.provider, 模型: s.model || "(未配置)",
      BaseURL: s.base_url || "(未配置)",
      "API Key": s.api_key_set ? ("已设置（来源: " + (s.api_key_source === "config" ? "网页配置" : "环境变量") + "）") : "未设置",
      识别模式: s.recognition_mode || "-", 预处理: s.preprocess_available ? "可用" : "未装OpenCV",
    });
  } catch (e) { /* 静默 */ }
}

function cfgPayload() {
  return {
    provider: $("#cfg-provider").value,
    openai_compat: {
      base_url: $("#cfg-base-url").value,
      model: $("#cfg-model").value,
      api_key: $("#cfg-api-key").value,   // 留空则服务端保持原值
    },
  };
}

function showTestResult(ok, text) {
  const el = $("#cfg-test-result");
  el.className = "alert " + (ok ? "ok-box" : "error");
  el.textContent = (ok ? "✅ " : "❌ ") + text;
  el.classList.remove("hidden");
}

$("#cfg-save").addEventListener("click", async () => {
  try {
    const r = await api("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfgPayload()),
    });
    $("#cfg-msg").textContent = "已保存 ✓";
    $("#cfg-msg").classList.remove("hidden");
    setTimeout(() => $("#cfg-msg").classList.add("hidden"), 2500);
    refreshStatus();
    loadStatus();
  } catch (e) { showTestResult(false, "保存失败: " + e.message); }
});

$("#cfg-test").addEventListener("click", async () => {
  const btn = $("#cfg-test");
  btn.disabled = true;
  showTestResult(true, "连接测试中（真实模型需数秒）…");
  try {
    const r = await api("/api/test-connection", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfgPayload()),
    });
    if (r.ok) showTestResult(true, (r.message || "连接成功") + "（模型 " + (r.model || "-") + "，" + (r.latency_s || 0) + "s）");
    else showTestResult(false, r.error || "连接失败");
  } catch (e) { showTestResult(false, e.message); }
  finally { btn.disabled = false; }
});

$("#cfg-clear-key").addEventListener("click", async () => {
  if (!confirm("确定清除网页中保存的 API Key？（环境变量不受影响）")) return;
  try {
    await api("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clear_api_key: true }),
    });
    showTestResult(true, "已清除网页保存的 Key");
    loadStatus();
    refreshStatus();
  } catch (e) { showTestResult(false, e.message); }
});

/* ───────── 公共渲染 ───────── */
const KV_LABELS = { drawing_name: "图名", drawing_no: "图号", material: "材料", scale: "比例", weight: "重量",
  designer: "设计", checker: "校核", approver: "批准", date: "日期", revision: "版本", project: "项目" };
function renderKV(sel, obj) {
  const display = {...obj, ...(obj.extra || {})};
  const labels = {...KV_LABELS, drawing_type:'图纸类型', material_applicable:'材料栏适用', unit:'单位', page:'页码', source_page:'来源页'};
  const keys = Object.keys(display).filter(k => !['extra','field_evidence','extraction_status','extraction_warnings'].includes(k) && (display[k] || ['drawing_name','drawing_no','designer','date'].includes(k)));
  $(sel).innerHTML = keys.length
    ? keys.map(k => '<div class="kv"><b>' + esc(labels[k] || k) + "</b>" + esc(k === 'drawing_type' ? ({assembly:'装配图',part:'零件图',unknown:'待确认'}[display[k]] || display[k]) : (display[k] || '未填写')) + "</div>").join("")
    : '<div class="empty">未提取到内容</div>';
}

function renderIssues(sel, issues) {
  $(sel).innerHTML = issues.length
    ? issues.map(it => '<div class="issue ' + (it.severity === "高" ? "high" : it.severity === "中" ? "mid" : "low") + '">' +
        '<span class="sev">' + esc(it.severity || "中") + '</span><b>' + esc(it.err_id || "") + " " + esc(it.type || "") + "</b> " + esc(it.message) +
        '<span class="loc">' + esc(it.location || "") + "</span>" +
        (it.evidence ? '<span class="loc">证据（第' + esc(String(it.source_page)) + '页）: ' + esc(it.evidence) + '</span>' : '') +
        '<span class="loc">来源: ' + esc(({rule:'规则',vlm:'视觉模型',engineering_rule:'专项规则＋原图提取事实','engineering_rule+vlm':'专项规则＋视觉复核','rule+vlm':'规则＋视觉模型','vlm_geometry+rule':'视觉端点识别＋算术规则','vlm_geometry+rule+vlm':'尺寸链规则＋视觉复核',dimension_link_rule:'尺寸对应复核＋名义值规则'})[it.origin || 'rule'] || it.origin) + ' · 待工程师复核</span>' +
        ((it.sources || []).length > 1 ? '<details><summary>查看合并前的 ' + it.sources.length + ' 条证据</summary>' + it.sources.map(s => '<p>' + esc(s.message || '') + ' ' + esc(s.evidence || '') + '</p>').join('') + '</details>' : '') +
        (it.suggestion ? '<span class="sug">建议: ' + esc(it.suggestion) + "</span>" : "") + "</div>").join("")
    : '<div class="issue none">本次未返回问题候选，请结合原图复核。</div>';
}

function fillTable(sel, headers, rows) {
  const t = $(sel);
  t.innerHTML = "<tr>" + headers.map(h => "<th>" + esc(h) + "</th>").join("") + "</tr>" +
    (rows.length ? rows.map(r => "<tr>" + r.map(c => "<td>" + esc(String(c)) + "</td>").join("") + "</tr>").join("")
      : '<tr><td colspan="' + headers.length + '" class="empty">暂无记录</td></tr>');
}

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }

/* 下载按钮 */
document.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-dl]");
  if (b && b.dataset.dl.indexOf("__ID__") === -1) window.open(b.dataset.dl, "_blank");
});

/* ───────── 检测历史 ───────── */
const DETH_FIELD_LABELS = { part_number: "件号", name_zh: "名称", name_en: "英文名", category: "分类",
  specification: "规格", material: "材料", quantity: "数量", unit: "单位", weight: "重量",
  position: "位置", supplier: "供应商" };

document.querySelector("#deth-refresh").addEventListener("click", loadDetectionHistory);
document.querySelector("#deth-file").addEventListener("keydown", (e) => { if (e.key === "Enter") loadDetectionHistory(); });
document.querySelector("#deth-status").addEventListener("change", loadDetectionHistory);
document.querySelector("#deth-dialog-close").addEventListener("click", () => $("#deth-dialog").close());
document.querySelector("#deth-dialog-max").addEventListener("click", () => {
  const maxed = $("#deth-dialog").classList.toggle("dialog-max");
  document.querySelector("#deth-dialog-max").textContent = maxed ? "还原" : "放大";
});

/* ───────── 原图预览缩放与全屏 ───────── */
let insZoomState = { mode: "fit" };  // fit=适应宽度 | natural=1:1 | level=相对适应宽度的倍率
function applyInsZoom() {
  const canvas = $("#ins-preview"), wrap = $("#ins-preview-wrap"), status = $("#ins-zoom-status");
  if (!canvas || !wrap) return;
  if (!insPreviewImage) { status.textContent = "适应宽度"; return; }
  if (insZoomState.mode === "fit") {
    canvas.style.maxWidth = "100%"; canvas.style.width = "";
    status.textContent = "适应宽度";
  } else if (insZoomState.mode === "natural") {
    canvas.style.maxWidth = "none";
    canvas.style.width = insPreviewImage.width + "px";
    status.textContent = "1:1（" + insPreviewImage.width + "×" + insPreviewImage.height + " px）";
  } else {
    canvas.style.maxWidth = "none";
    canvas.style.width = Math.round(wrap.clientWidth * insZoomState.v) + "px";
    status.textContent = Math.round(insZoomState.v * 100) + "%（相对适应宽度）";
  }
}
function insZoomStep(delta) {
  const cur = insZoomState.mode === "level" ? insZoomState.v : 1;
  insZoomState = { mode: "level", v: Math.min(5, Math.max(0.2, Math.round((cur + delta) * 100) / 100)) };
  applyInsZoom();
}
window.setInsPreviewImage = (img) => { insPreviewImage = img; applyInsZoom(); };
document.querySelector("#ins-zoom-in").addEventListener("click", () => insZoomStep(0.25));
document.querySelector("#ins-zoom-out").addEventListener("click", () => insZoomStep(-0.25));
document.querySelector("#ins-zoom-fit").addEventListener("click", () => { insZoomState = { mode: "fit" }; applyInsZoom(); });
document.querySelector("#ins-zoom-natural").addEventListener("click", () => { insZoomState = { mode: "natural" }; applyInsZoom(); });
document.querySelector("#ins-zoom-full").addEventListener("click", () => {
  const wrap = $("#ins-preview-wrap");
  if (document.fullscreenElement) document.exitFullscreen();
  else if (wrap.requestFullscreen) wrap.requestFullscreen().catch(() => alert("当前浏览器不支持全屏"));
});
document.addEventListener("fullscreenchange", () => setTimeout(applyInsZoom, 80));
window.addEventListener("resize", () => { if (insZoomState.mode === "level") applyInsZoom(); });
document.querySelector("#deth-table").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-deth]");
  if (btn) showDetectionDetail(btn.dataset.deth);
});

async function loadDetectionHistory() {
  const params = new URLSearchParams();
  const file = $("#deth-file").value.trim();
  const status = $("#deth-status").value;
  if (file) params.set("file_name", file);
  if (status) params.set("status", status);
  try {
    const data = await api("/api/detection_history?" + params.toString());
    dethRenderSummary(data.summary || {});
    dethRenderRows(data.records || []);
  } catch (e) {
    $("#deth-summary").innerHTML = '<span class="alert error">历史加载失败: ' + esc(e.message) + "</span>";
  }
}

function dethChip(label, value) {
  return '<span class="chip"><b>' + esc(label) + "</b>" + esc(value) + "</span>";
}

function dethRenderSummary(s) {
  const el = $("#deth-summary");
  if (!s.total) { el.innerHTML = '<span class="hint">暂无历史记录——完成一次图纸识别后自动留痕（含失败任务）。</span>'; return; }
  el.innerHTML = [
    dethChip("检测次数", s.total), dethChip("成功", s.ok), dethChip("失败", s.failed),
    dethChip("成功率", s.success_rate == null ? "-" : Math.round(s.success_rate * 100) + "%"),
    dethChip("平均识别", s.avg_bom_time_s != null ? s.avg_bom_time_s + "s" : "-"),
    dethChip("平均审图", s.avg_inspection_time_s != null ? s.avg_inspection_time_s + "s" : "-"),
    dethChip("累计零部件行", s.total_components),
    dethChip("累计审图发现", s.total_findings),
    dethChip("涉及文件", s.distinct_files),
    dethChip("最近模型", s.latest_model || "-"),
  ].join("");
}

function dethRenderRows(records) {
  const tbody = $("#deth-table tbody");
  tbody.innerHTML = records.map((r) => {
    const bom = r.bom || {}, asm = r.assembly || {}, insp = r.inspection || {},
          tim = r.timings || {}, model = r.model || {};
    const ok = r.status === "ok";
    const status = ok ? '<span class="badge">成功</span>'
                      : '<span class="badge" style="color:#b00020;border-color:#b00020">失败</span>';
    const cells = [
      esc(r.finished_at || ""), esc(r.file_name || "-"), esc(model.model || "-"), status,
      ok ? (bom.n_components ?? "-") : "-",
      ok ? ((asm.n_nodes ?? 0) + " / " + (asm.max_depth ?? "-")) : "-",
      ok ? (((bom.needs_review || {}).count ?? 0) + "+" + (asm.n_unverified ?? 0) + "未核") : "-",
      ok ? (bom.n_validation_issues ?? 0) : "-",
      ok ? (insp.n_findings ?? 0) : "-",
      ok ? (tim.bom_process_time_s ?? "-") : "-",
      ok ? (tim.inspection_process_time_s ?? "-") : "-",
      '<button data-deth="' + esc(r.job_id) + '">详情</button>',
    ];
    return "<tr>" + cells.map((v) => "<td>" + v + "</td>").join("") + "</tr>";
  }).join("") || '<tr><td colspan="12" class="hint">没有匹配的记录</td></tr>';
}

function dethKV(label, value) {
  const shown = (value === null || value === undefined || value === "") ? "-" : value;
  return '<div class="kv"><b>' + esc(label) + "</b>" + esc(shown) + "</div>";
}

function dethBar(label, filled, total) {
  const rate = total ? Math.round((filled / total) * 100) : 0;
  return '<div class="kv"><b>' + esc(label) + '</b><span class="fill"><i style="width:' + rate +
    '%"></i></span>' + filled + "/" + total + "（" + rate + "%）</div>";
}

function dethCountPair(obj) {
  const entries = Object.entries(obj || {});
  return entries.length ? entries.map(([k, v]) => k + " " + v).join("；") : null;
}

function dethRenderBomTable(components) {
  // 与主页面 #bom-table 相同的列（只读快照，保留 ⚠ 待复核标记）。
  const cols = [...new Set([...Object.keys(BOM_LABELS), ...components.flatMap(c => Object.keys(c))])]
    .filter(c => !HIDDEN_COLS.has(c));
  let html = "<tr>" + cols.map(c => "<th>" + (BOM_LABELS[c] || c) + "</th>").join("") + "</tr>";
  components.forEach((comp) => {
    const reasons = (comp.review_reasons || []).join("\n");
    const flagged = comp.needs_review && reasons;
    html += "<tr" + (flagged ? ' class="row-review" title="' + esc(reasons) + '"' : "") + ">" + cols.map((c) => {
      const v = comp[c] === null || comp[c] === undefined ? "" : comp[c];
      const badge = flagged ? '<span class="review-flag" title="' + esc(reasons) + '">⚠</span> ' : "";
      return "<td>" + badge + esc(v) + "</td>";
    }).join("") + "</tr>";
  });
  return html;
}

async function showDetectionDetail(jobId) {
  let d;
  try { d = await api("/api/detection_history/" + encodeURIComponent(jobId)); }
  catch (e) { alert("详情加载失败: " + e.message); return; }
  const r = d.record || {}, res = d.result || {};
  const bom = r.bom || {}, asm = r.assembly || {}, insp = r.inspection || {},
        tim = r.timings || {}, model = r.model || {}, tb = r.title_block || {},
        ann = r.annotations || {};
  const components = (res.bom || {}).components || [];
  const tree = (res.bom || {}).assembly || {};
  const out = [];
  out.push('<div class="card"><h2>概览</h2><div class="kv-grid">' +
    dethKV("状态", r.status === "ok" ? "成功" : "失败" + (r.error ? "：" + r.error : "")) +
    dethKV("完成时间", r.finished_at) + dethKV("文件", r.file_name) +
    dethKV("文档号", r.document_id) +
    dethKV("SHA256", r.source_sha256 ? String(r.source_sha256).slice(0, 16) + "…" : null) +
    dethKV("页数", model.pages) + "</div></div>");
  if (r.status !== "ok") {
    $("#deth-detail").innerHTML = out.join("");
    $("#deth-dialog-title").textContent = "检测详情 · " + (r.file_name || r.job_id);
    $("#deth-dialog").showModal();
    return;
  }
  out.push('<div class="card"><h2>模型与配置</h2><div class="kv-grid">' +
    dethKV("Provider", model.provider) + dethKV("模型", model.model) +
    dethKV("提示词版本", model.prompt_version) + dethKV("识别模式", model.recognition_mode) +
    dethKV("保留原始行", model.preserve_printed_rows == null ? null : (model.preserve_printed_rows ? "是" : "否")) +
    dethKV("知识库条数", model.knowledge_base) + dethKV("AgentLoop", model.agent_loop_status) + "</div></div>");
  out.push('<div class="card"><h2>BOM 指标</h2><div class="kv-grid">' +
    dethKV("零部件行数", bom.n_components) + dethKV("数量合计", bom.total_quantity) +
    dethKV("置信度均值", (bom.confidence || {}).mean) +
    dethKV("置信度区间", (bom.confidence || {}).min != null ? bom.confidence.min + " ~ " + bom.confidence.max : null) +
    dethKV("待复核行", (bom.needs_review || {}).count) +
    dethKV("校验问题数", bom.n_validation_issues) + "</div>" +
    '<h2 style="margin-top:12px">字段填充率</h2><div class="kv-grid">' +
    Object.entries(bom.field_fill || {}).map(([k, v]) => dethBar(DETH_FIELD_LABELS[k] || k, v.filled, v.total)).join("") +
    "</div>" +
    (Object.keys(bom.categories || {}).length ? '<h2 style="margin-top:12px">分类分布</h2><div class="chips">' +
      Object.entries(bom.categories).map(([k, v]) => dethChip(k, v)).join("") + "</div>" : "") +
    "</div>");
  const conflicts = asm.quantity_conflicts || [];
  out.push('<div class="card"><h2>装配树指标</h2><div class="kv-grid">' +
    dethKV("推理状态", asm.inference_status) + dethKV("节点数", asm.n_nodes) +
    dethKV("待核节点", asm.n_unverified) +
    dethKV("未建关系行", (asm.unresolved_component_indices || []).length ? asm.unresolved_component_indices.join("、") : "无") +
    dethKV("最大深度", asm.max_depth) + dethKV("数量对账冲突", asm.n_quantity_conflicts) + "</div>" +
    (conflicts.length ? '<div class="table-wrap"><table><thead><tr><th>件号</th><th>明细栏数量</th><th>展开计算量</th></tr></thead><tbody>' +
      conflicts.map((c) => "<tr><td>" + esc(c.part_number || "?") + "</td><td>" + esc(c.printed_quantity ?? "-") + "</td><td>" + esc(c.exploded_quantity ?? "-") + "</td></tr>").join("") +
      "</tbody></table></div>" : "") + "</div>");
  // ── 与「BOM 与图纸纠错」结果页相同的完整面板（只读快照） ──
  const vissues = (res.bom || {}).validation_issues || [];
  out.push('<div class="card"><h2>零部件清单（历史快照 · ' + components.length + ' 行）</h2><p class="hint">与结果页同列的只读视图；后续编辑已同步进历史。</p>' +
    (vissues.length ? '<p class="alert warn">BOM 校验提示：' + esc(vissues.join("；")) + "</p>" : "") +
    '<div class="table-wrap"><table id="deth-bom-table">' + dethRenderBomTable(components) + "</table></div></div>");
  out.push('<div class="card"><h2>装配层级（父子关系）</h2><p id="deth-assembly-status" class="hint"></p>' +
    '<div class="table-wrap"><table id="deth-assembly-table"></table></div>' +
    '<details id="deth-assembly-pending" class="hint"></details>' +
    '<details><summary>装配层级 JSON</summary><pre style="white-space:pre-wrap">' +
    esc(JSON.stringify(tree.nodes || [], null, 2)) + "</pre></details></div>");
  out.push('<div class="card"><h2>标题栏信息</h2><div class="kv-grid" id="deth-titleblock"></div></div>');
  const issues = res.issues || [];
  out.push('<div class="card"><h2>图纸检查结果（<span id="deth-issues-count">0</span> 项）</h2><div id="deth-issues"></div></div>');
  out.push('<details class="card"><summary>审图覆盖、专项规则与计算证据</summary><div id="deth-coverage"></div></details>');
  out.push('<details class="card"><summary>尺寸标注抽取</summary><div class="table-wrap"><table id="deth-dims"></table></div></details>');
  const regionLabels = {frame:'图框', title_block:'标题栏', bom_table:'明细栏', technical_notes:'技术要求', view:'视图'};
  const regions = (res.layout || {}).regions || [];
  out.push('<div class="card"><h2>图纸区域定位</h2><p class="hint">' +
    (regions.length ? regions.map((rg) => '<span class="chip">' + esc(regionLabels[rg.kind] || rg.kind) +
      " · 第" + esc(rg.source_page) + "页 · " + esc(rg.bbox_status === 'refined' ? '已补边（待复核）' : '待复核') + "</span>").join(" ")
      : "区域尚未定位") + "</p></div>");
  out.push('<div class="card"><h2>耗时与输出</h2><div class="kv-grid">' +
    dethKV("BOM 识别", tim.bom_process_time_s != null ? tim.bom_process_time_s + "s" : null) +
    dethKV("审图阶段", tim.inspection_process_time_s != null ? tim.inspection_process_time_s + "s" : null) +
    dethKV("导出文件", (r.outputs || []).join("、") || null) + "</div>" +
    '<p class="hint"><a href="/api/detection_history/' + encodeURIComponent(r.job_id) +
    '" target="_blank">查看完整结果 JSON（含零部件全表）</a></p></div>');
  $("#deth-detail").innerHTML = out.join("");
  // innerHTML 就位后调用与主页面相同的渲染器
  renderKV("#deth-titleblock", res.title_block || {});
  $("#deth-issues-count").textContent = issues.length;
  renderIssues("#deth-issues", issues);
  $("#deth-coverage").innerHTML = renderInspectionCoverage(res);
  fillTable("#deth-dims", ["尺寸代号", "数值", "视图"], (res.dimensions || []).map(dd => [dd.tag || "", dd.value || "", dd.view || ""]));
  renderAssembly(tree, {components: components, tableSel: "#deth-assembly-table",
                        statusSel: "#deth-assembly-status", editorSel: null,
                        pendingSel: "#deth-assembly-pending"});
  $("#deth-dialog-title").textContent = "检测详情 · " + (r.file_name || r.job_id);
  $("#deth-dialog").showModal();
}

refreshStatus();
setInterval(refreshStatus, 10000);
