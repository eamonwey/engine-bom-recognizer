# -*- coding: utf-8 -*-
"""评测指标（对齐论文 Table 2 的报告方式：均值 ± 标准差 + 处理时长）。

指标体系：
  * 元器件级检测：以（件号精确匹配 + 名称模糊匹配）配对，报告 Precision / Recall / F1；
  * 字段级提取：对配对成功的元器件，逐字段比对（part_number/名称/规格/材料/数量/...），
    报告字段准确率（仅在人工标注提供该字段时才计入分母）；
  * 完全正确率（exact_bom）：预测与标注的元器件一一对应且全部字段一致的比例；
  * 汇总：宏平均（各文档平均）+ 微平均（全部元器件池化），含标准差与平均处理时长。
"""
import statistics
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from ..schema import BomComponent, BomDocument, normalize_part_number, normalize_text

EVAL_FIELDS = [
    "part_number", "name_zh", "name_en", "category", "specification",
    "material", "quantity", "unit", "position", "supplier",
]

DEFAULT_NAME_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# 配对
# ---------------------------------------------------------------------------

def name_similarity(pred: BomComponent, gt: BomComponent) -> float:
    combos = [
        (pred.name_zh, gt.name_zh), (pred.name_en, gt.name_en),
        (pred.name_zh, gt.name_en), (pred.name_en, gt.name_zh),
    ]
    best = 0.0
    for a, b in combos:
        if a and b:
            best = max(best, SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio())
    return best


def match_components(preds: List[BomComponent], gts: List[BomComponent],
                     name_threshold: float = DEFAULT_NAME_THRESHOLD) -> List[Tuple[int, int]]:
    """返回配对 (pred_index, gt_index)。先按件号精确匹配，再对剩余项按名称相似度贪心配对。"""
    pairs: List[Tuple[int, int]] = []
    used_pred = set()
    used_gt = set()

    gt_by_pn: Dict[str, int] = {}
    for j, g in enumerate(gts):
        key = normalize_part_number(g.part_number)
        if key and key not in gt_by_pn:
            gt_by_pn[key] = j
    for i, p in enumerate(preds):
        key = normalize_part_number(p.part_number)
        j = gt_by_pn.get(key) if key else None
        if j is not None and j not in used_gt:
            pairs.append((i, j))
            used_pred.add(i)
            used_gt.add(j)

    candidates: List[Tuple[float, int, int]] = []
    for i, p in enumerate(preds):
        if i in used_pred:
            continue
        for j, g in enumerate(gts):
            if j in used_gt:
                continue
            sim = name_similarity(p, g)
            if sim >= name_threshold:
                candidates.append((sim, i, j))
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
    for sim, i, j in candidates:
        if i in used_pred or j in used_gt:
            continue
        pairs.append((i, j))
        used_pred.add(i)
        used_gt.add(j)
    return pairs


# ---------------------------------------------------------------------------
# 字段比对
# ---------------------------------------------------------------------------

def field_equal(field: str, pred: BomComponent, gt: BomComponent) -> bool:
    pv = getattr(pred, field, None)
    gv = getattr(gt, field, None)
    if field == "quantity":
        return pv is not None and gv is not None and int(pv) == int(gv)
    if field == "part_number":
        return bool(normalize_part_number(pv)) and \
            normalize_part_number(pv) == normalize_part_number(gv)
    return bool(normalize_text(gv)) and normalize_text(pv) == normalize_text(gv)


def gt_provides(field: str, gt: BomComponent) -> bool:
    gv = getattr(gt, field, None)
    return gv is not None and str(gv).strip() != ""


# ---------------------------------------------------------------------------
# 单文档评测
# ---------------------------------------------------------------------------

def evaluate_document(pred: BomDocument, gt: BomDocument,
                      name_threshold: float = DEFAULT_NAME_THRESHOLD) -> Dict[str, Any]:
    pairs = match_components(pred.components, gt.components, name_threshold)
    n_gt, n_pred, n_matched = len(gt.components), len(pred.components), len(pairs)
    precision = n_matched / n_pred if n_pred else 0.0
    recall = n_matched / n_gt if n_gt else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    fields: Dict[str, Dict[str, Any]] = {}
    mistake_details: List[str] = []
    for field in EVAL_FIELDS:
        correct = total = 0
        for i, j in pairs:
            p, g = pred.components[i], gt.components[j]
            if not gt_provides(field, g):
                continue
            total += 1
            ok = field_equal(field, p, g)
            correct += int(ok)
            if not ok:
                mistake_details.append("%s.%s: 预测=%r 标注=%r" % (g.display_name(), field,
                                                                  getattr(p, field, None), getattr(g, field, None)))
        fields[field] = {"correct": correct, "total": total,
                         "accuracy": (correct / total) if total else None}

    total_correct = sum(f["correct"] for f in fields.values())
    total_fields = sum(f["total"] for f in fields.values())
    field_accuracy = (total_correct / total_fields) if total_fields else None
    exact_bom = (n_matched == n_gt == n_pred) and all(f["correct"] == f["total"] for f in fields.values())

    matched_gt = {j for _, j in pairs}
    matched_pred = {i for i, _ in pairs}
    return {
        "document_id": gt.document_id or pred.document_id,
        "n_gt": n_gt, "n_pred": n_pred, "n_matched": n_matched,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "field_accuracy": None if field_accuracy is None else round(field_accuracy, 4),
        "exact_bom": exact_bom,
        "fields": fields,
        "missed_gt": [g.display_name() for j, g in enumerate(gt.components) if j not in matched_gt],
        "false_positives": [p.display_name() for i, p in enumerate(pred.components) if i not in matched_pred],
        "field_mistakes": mistake_details,
        "process_time_s": pred.process_time_s,
    }


# ---------------------------------------------------------------------------
# 语料级汇总
# ---------------------------------------------------------------------------

def evaluate_corpus(doc_results: List[Dict[str, Any]], meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """对多文档结果做宏/微平均汇总（论文式报告：均值 ± 标准差）。"""
    n = len(doc_results)
    if n == 0:
        return {"n_documents": 0, "meta": meta or {}}

    def _mean_std(key: str) -> Dict[str, Any]:
        values = [d[key] for d in doc_results if d.get(key) is not None]
        if not values:
            return {"mean": None, "std": None}
        return {"mean": round(statistics.mean(values), 4),
                "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0}

    total_gt = sum(d["n_gt"] for d in doc_results)
    total_pred = sum(d["n_pred"] for d in doc_results)
    total_matched = sum(d["n_matched"] for d in doc_results)
    micro_p = total_matched / total_pred if total_pred else 0.0
    micro_r = total_matched / total_gt if total_gt else 0.0

    field_totals: Dict[str, Dict[str, int]] = {f: {"correct": 0, "total": 0} for f in EVAL_FIELDS}
    for d in doc_results:
        for f in EVAL_FIELDS:
            field_totals[f]["correct"] += d["fields"][f]["correct"]
            field_totals[f]["total"] += d["fields"][f]["total"]

    times = [d["process_time_s"] for d in doc_results if d.get("process_time_s")]
    return {
        "n_documents": n,
        "meta": meta or {},
        "component_detection": {
            "total_gt": total_gt, "total_pred": total_pred, "total_matched": total_matched,
            "micro_precision": round(micro_p, 4), "micro_recall": round(micro_r, 4),
            "micro_f1": round(2 * micro_p * micro_r / (micro_p + micro_r), 4) if (micro_p + micro_r) else 0.0,
            "macro_precision": _mean_std("precision"),
            "macro_recall": _mean_std("recall"),
            "macro_f1": _mean_std("f1"),
        },
        "field_accuracy_macro": _mean_std("field_accuracy"),
        "field_accuracy_micro": {
            f: {"correct": v["correct"], "total": v["total"],
                "accuracy": round(v["correct"] / v["total"], 4) if v["total"] else None}
            for f, v in field_totals.items()
        },
        "exact_bom_rate": _mean_std("exact_bom"),
        "avg_process_time_s": round(statistics.mean(times), 3) if times else None,
        "documents": doc_results,
    }


# ---------------------------------------------------------------------------
# Markdown 报告
# ---------------------------------------------------------------------------

def _fmt(x: Any, pct: bool = False) -> str:
    if x is None:
        return "-"
    if isinstance(x, bool):
        return "是" if x else "否"
    if pct:
        return "%.2f%%" % (x * 100)
    return "%.4f" % x if isinstance(x, float) else str(x)


def render_markdown_report(agg: Dict[str, Any]) -> str:
    lines: List[str] = []
    meta = agg.get("meta") or {}
    lines.append("# BOM 识别评测报告")
    lines.append("")
    lines.append("- 实验: %s" % meta.get("experiment", "-"))
    lines.append("- 运行: %s" % meta.get("run", "-"))
    lines.append("- 模型: %s" % meta.get("model", "-"))
    lines.append("- 提示词版本: %s" % meta.get("prompt_version", "-"))
    lines.append("- 文档数: %d" % agg["n_documents"])
    lines.append("")
    if agg.get("strict"):
        strict = agg["strict"]
        lines.extend(["## 严格评测（件号精确匹配，漏检字段计入分母）", "",
                      "P=%s，R=%s，F1=%s；端到端字段准确率=%s；BOM完全正确率=%s。" % (
                          _fmt(strict["precision"]), _fmt(strict["recall"]), _fmt(strict["f1"]),
                          _fmt(strict["end_to_end_field_accuracy"],pct=True), _fmt(strict["exact_bom_rate"],pct=True)), "",
                      "| 字段 | 正确/全部标注字段 | 准确率 |", "|---|---|---|"])
        for name, value in strict["fields"].items():
            lines.append("| %s | %d/%d | %s |" % (name,value["correct"],value["total"],_fmt(value["accuracy"],pct=True)))
        lines.append("")
        lines.extend(["以下为兼容旧版口径，允许名称模糊配对，字段准确率只统计已配对的行。", ""])

    det = agg["component_detection"]
    lines.append("## 元器件检测（宏平均 = 各文档平均，报告方式对齐参考论文）")
    lines.append("")
    lines.append("| 指标 | 均值 | 标准差 |")
    lines.append("|---|---|---|")
    lines.append("| Precision | %s | %s |" % (_fmt(det["macro_precision"]["mean"]), _fmt(det["macro_precision"]["std"])))
    lines.append("| Recall | %s | %s |" % (_fmt(det["macro_recall"]["mean"]), _fmt(det["macro_recall"]["std"])))
    lines.append("| F1 | %s | %s |" % (_fmt(det["macro_f1"]["mean"]), _fmt(det["macro_f1"]["std"])))
    lines.append("| 字段准确率 | %s | %s |" % (_fmt(agg["field_accuracy_macro"]["mean"]),
                                             _fmt(agg["field_accuracy_macro"]["std"])))
    lines.append("| 完全正确率 | %s | %s |" % (_fmt(agg["exact_bom_rate"]["mean"]), _fmt(agg["exact_bom_rate"]["std"])))
    lines.append("")
    lines.append("微平均（全部元器件池化）: P=%s R=%s F1=%s；平均处理时长 %s s"
                 % (_fmt(det["micro_precision"]), _fmt(det["micro_recall"]),
                    _fmt(det["micro_f1"]), _fmt(agg.get("avg_process_time_s"))))
    lines.append("")

    lines.append("## 各字段准确率（微平均，仅统计标注提供的字段）")
    lines.append("")
    lines.append("| 字段 | 正确/总数 | 准确率 |")
    lines.append("|---|---|---|")
    for f in EVAL_FIELDS:
        v = agg["field_accuracy_micro"][f]
        lines.append("| %s | %d/%d | %s |" % (f, v["correct"], v["total"], _fmt(v["accuracy"], pct=True)))
    lines.append("")

    lines.append("## 分文档明细")
    lines.append("")
    lines.append("| 文档 | 标注数 | 预测数 | 配对 | P | R | F1 | 字段准确率 | 完全正确 | 耗时(s) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for d in agg["documents"]:
        lines.append("| %s | %d | %d | %d | %s | %s | %s | %s | %s | %s |" % (
            d["document_id"], d["n_gt"], d["n_pred"], d["n_matched"],
            _fmt(d["precision"]), _fmt(d["recall"]), _fmt(d["f1"]),
            _fmt(d["field_accuracy"]), _fmt(d["exact_bom"]), _fmt(d.get("process_time_s"))))
    lines.append("")

    missed = [(d["document_id"], m) for d in agg["documents"] for m in d["missed_gt"]]
    fps = [(d["document_id"], m) for d in agg["documents"] for m in d["false_positives"]]
    if missed:
        lines.append("## 漏检元器件（召回缺口）")
        lines.append("")
        for doc_id, name in missed:
            lines.append("- %s: %s" % (doc_id, name))
        lines.append("")
    if fps:
        lines.append("## 误报元器件（多检）")
        lines.append("")
        for doc_id, name in fps:
            lines.append("- %s: %s" % (doc_id, name))
        lines.append("")
    return "\n".join(lines)
