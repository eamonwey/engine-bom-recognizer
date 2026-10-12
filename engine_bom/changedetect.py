# -*- coding: utf-8 -*-
"""文件变更智能控制（REQ-03）：版本对齐 -> 变更识别高亮 -> 类型分类 -> ECN 草稿 -> 历史追溯。

MVP 实现路线（对齐需求表备注）:
  * 段落级对齐: difflib.SequenceMatcher（纯文本层；句向量对齐作为内网升级项）
  * 变更识别: 新增/删除/修改三类，宁可多报不漏报（格式变化可开关忽略）
  * 类型分类: 关键词规则优先，接入 LLM 后可替换 classify_change()
  * ECN 草稿: Markdown 模板填充（Word 模板对接留接口）
  * 历史追溯: data/change_history.json 追加式记录
"""
import difflib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

# 变更类型分类（ERR 表之外的 REQ-03-3 六类预定义）
CHANGE_CATEGORIES = [
    ("技术参数修改", ["参数", "温度", "压力", "转速", "电压", "电流", "功率", "频率", "尺寸", "公差", "mm", "℃", "r/min"]),
    ("材料替换", ["材料", "牌号", "更换为", "代用", "材质", "合金", "钢", "铝", "钛"]),
    ("工艺调整", ["工艺", "焊接", "热处理", "装配", "加工", "工序", "表面处理", "喷涂"]),
    ("标准更新", ["GB", "GJB", "JB", "ISO", "标准", "规范"]),
    ("格式/排版修改", ["格式", "排版", "字体", "编号调整", "页码"]),
    ("错别字/措辞修改", ["错别字", "笔误", "措辞", "表述"]),
]

ADDED, REMOVED, MODIFIED = "added", "removed", "modified"

_TYPE_LABEL = {ADDED: "新增", REMOVED: "删除", MODIFIED: "修改"}


# ---------------------------------------------------------------------------
# 文本提取（复用 docextract 的解析器）
# ---------------------------------------------------------------------------

def extract_text(path: str) -> Dict[str, Any]:
    from .docextract import parse_document
    if os.path.splitext(path)[1].lower() == '.pdf':
        import fitz
        with fitz.open(path) as doc:
            incomplete = [i + 1 for i, page in enumerate(doc)
                          if page.get_image_info() or page.get_drawings()]
        if incomplete:
            raise ValueError('比较不完整：PDF 第 %s 页包含图片或矢量图形，当前文字比较不能验证这些区域的变化，请进行图面复核；不能判定无变更'
                             % ', '.join(map(str, incomplete)))
    parsed = parse_document(path)
    blocks = parsed.get('blocks') or []
    paragraphs = [b['text'] for b in blocks] or [ln.strip() for ln in (parsed.get('text') or '').splitlines() if ln.strip()]
    if not paragraphs:
        raise ValueError('版本对比需要可提取的文字；扫描文件请先完成OCR，不能把空文本视为无变更')
    return {"paragraphs": paragraphs, 'blocks': blocks, "format": parsed.get("format"), "n_pages": parsed.get("n_pages")}


# ---------------------------------------------------------------------------
# 对齐与差异识别
# ---------------------------------------------------------------------------

def align_and_diff(before: List[str], after: List[str],
                   ignore_format: bool = True,
                   similarity_threshold: float = 0.6) -> List[Dict[str, Any]]:
    """段落级对齐 + 变更项识别（修改 = 相似度达阈值的删除/新增配对）。"""
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    removed: List[tuple] = []   # (idx, text)
    added: List[tuple] = []
    items: List[Dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("delete", "replace"):
            removed.extend((i, before[i]) for i in range(i1, i2))
        if tag in ("insert", "replace"):
            added.extend((j, after[j]) for j in range(j1, j2))

    added_text = {j: text for j, text in added}  # 段落序号 -> 文本
    used_after = set()
    used_before = set()
    # Match moved occurrences before fuzzy modifications, preserving multiplicity.
    for i, old in removed:
        exact = next((j for j, new in added if j not in used_after and
                      (_norm_for_compare(old) == _norm_for_compare(new) if ignore_format else old == new)), None)
        if exact is not None:
            used_before.add(i)
            used_after.add(exact)
    for i, old in removed:
        if i in used_before:
            continue
        best_j, best_sim = None, 0.0
        for j, new in added:
            if j in used_after:
                continue
            sim = difflib.SequenceMatcher(None, old, new).ratio()
            if sim > best_sim:
                best_sim, best_j = sim, j
        if best_j is not None and best_sim >= similarity_threshold:
            used_before.add(i)
            used_after.add(best_j)
            items.append({
                "type": MODIFIED, "label": _TYPE_LABEL[MODIFIED],
                "before": old, "after": added_text[best_j],
                "similarity": round(best_sim, 3),
                "location_before": "第%d段" % (i + 1), "location_after": "第%d段" % (best_j + 1),
                "category": classify_change(old, added_text[best_j]),
            })
    for i, old in removed:
        if i not in used_before:
            items.append({"type": REMOVED, "label": _TYPE_LABEL[REMOVED], "before": old, "after": "",
                          "location_before": "第%d段" % (i + 1), "location_after": "",
                          "category": classify_change(old, "")})
    for j, new in added:
        if j not in used_after:
            items.append({"type": ADDED, "label": _TYPE_LABEL[ADDED], "before": "", "after": new,
                          "location_before": "", "location_after": "第%d段" % (j + 1),
                          "category": classify_change("", new)})

    if ignore_format:
        kept = [it for it in items if not _is_format_only(it)]
        dropped = len(items) - len(kept)
        items = kept
    else:
        dropped = 0
    items.sort(key=lambda it: (it.get("location_after") or it.get("location_before") or "").zfill(8))
    for it in items:
        it["summary"] = _summarize(it)
    return items


def _norm_for_compare(text: str) -> str:
    # Minus signs, decimal points and tolerances are engineering data.
    return re.sub(r"\s+", "", str(text))


def _is_format_only(item: Dict[str, Any]) -> bool:
    """忽略格式变化：去空白/标点后内容一致视为纯格式修改。"""
    return _norm_for_compare(item.get("before", "")) == _norm_for_compare(item.get("after", ""))


def classify_change(before: str, after: str) -> str:
    """规则分类：按命中关键词打分取最高（需求表 P1，LLM 分类可替换此函数）。"""
    text = "%s %s" % (before, after)
    best_cat, best_score = "其他", 0
    for cat, keywords in CHANGE_CATEGORIES:
        score = sum(1 for kw in keywords if kw.lower() in text.lower())
        if score > best_score:
            best_cat, best_score = cat, score
    return best_cat


def _summarize(item: Dict[str, Any]) -> str:
    if item["type"] == MODIFIED:
        return "「%s」改为「%s」" % (item["before"][:40], item["after"][:40])
    if item["type"] == ADDED:
        return "新增「%s」" % item["after"][:40]
    return "删除「%s」" % item["before"][:40]


# ---------------------------------------------------------------------------
# 汇总与 ECN 草稿
# ---------------------------------------------------------------------------

def summarize_changes(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_type = {t: sum(1 for it in items if it["type"] == t) for t in (ADDED, REMOVED, MODIFIED)}
    by_cat: Dict[str, int] = {}
    for it in items:
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
    return {"total": len(items), "by_type": by_type, "by_category": by_cat}


def generate_ecn_md(meta: Dict[str, Any], items: List[Dict[str, Any]],
                    summary: Dict[str, Any]) -> str:
    """变更申请单（ECN/ECR）Markdown 草稿。企业模板可替换此函数。"""
    lines = [
        "# 变更申请单（草稿）",
        "",
        "| 字段 | 内容 |",
        "|---|---|",
        "| 单据编号 | ECN-%s |" % time.strftime("%Y%m%d-%H%M%S"),
        "| 文件名称 | %s |" % meta.get("file_name", "-"),
        "| 变更前版本 | %s |" % meta.get("before_name", "-"),
        "| 变更后版本 | %s |" % meta.get("after_name", "-"),
        "| 提出人 | （自动生成，请补填） |",
        "| 日期 | %s |" % time.strftime("%Y-%m-%d"),
        "",
        "## 一、变更内容摘要",
        "",
        "共识别变更 %d 处：新增 %d、删除 %d、修改 %d。" % (
            summary["total"], summary["by_type"][ADDED],
            summary["by_type"][REMOVED], summary["by_type"][MODIFIED]),
        "",
        "| # | 类型 | 分类 | 变更内容 | 位置 |",
        "|---|---|---|---|---|",
    ]
    for i, it in enumerate(items, start=1):
        lines.append("| %d | %s | %s | %s | %s |" % (
            i, it["label"], it["category"],
            it["summary"].replace("|", "\\|"),
            (it.get("location_after") or it.get("location_before") or "-")))
    lines += ["", "## 二、影响范围（初评）", "",
              "- 受影响关联文档/BOM/工序：待关联知识库后自动检索（第二阶段功能）",
              "- 建议核查：%s 相关的工艺文件与检验规程" % "、".join(
                  sorted({it["category"] for it in items})[:4]),
              "", "## 三、建议措施", "",
              "1. 请工艺/设计确认上述变更内容与分类。",
              "2. 确认后按企业流程流转审批。", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 历史追溯
# ---------------------------------------------------------------------------

def append_history(history_path: str, record: Dict[str, Any]) -> None:
    records: List[Dict[str, Any]] = []
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                records = json.load(f)
        except (ValueError, OSError):
            records = []
    record["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    records.append(record)
    parent = os.path.dirname(os.path.abspath(history_path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(history_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def load_history(history_path: str,
                 file_name: Optional[str] = None,
                 category: Optional[str] = None) -> List[Dict[str, Any]]:
    if not os.path.exists(history_path):
        return []
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            records = json.load(f)
    except (ValueError, OSError):
        return []
    def match(r):
        return ((not file_name or file_name in str(r.get("file_name", ""))) and
                (not category or category in json.dumps(r.get("summary", {}), ensure_ascii=False)))
    return [r for r in records if match(r)]
