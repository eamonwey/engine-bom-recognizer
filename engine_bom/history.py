# -*- coding: utf-8 -*-
"""检测历史：每次 BOM 识别任务（成功或失败）的完整留痕。

存储于 data/detection_history/：
  * history.jsonl —— 轻量索引，每行一条记录摘要（新记录追加在末尾）；
  * <job_id>.json —— 该次任务的完整结果快照。任务目录会被过期清理，
    历史快照自包含，旧结果仍然可查。

记录覆盖的指标（"所有指标都有"）：
  文件与溯源（文件名/SHA256/文档号/页数）、模型与配置（provider/模型/提示词版本/
  识别模式/知识库条数）、BOM 全字段填充率、置信度统计、分类分布、待复核行数与
  原因、校验问题、装配树（节点/待核/未建关系行/深度/数量对账冲突）、标题栏及
  必填缺失、球标与尺寸标注、审图发现（按严重度/类型/来源统计＋全量）、分段耗时、
  导出文件。
"""
import json
import os
import threading
from collections import Counter
from datetime import datetime

_LOCK = threading.Lock()

# 计算 BOM 字段填充率时关注的列（与 BomComponent 字段对齐）
_TRACKED_FIELDS = ["part_number", "name_zh", "name_en", "category", "specification",
                   "material", "quantity", "unit", "weight", "position", "supplier"]

_REVIEW_FIELDS = ["part_number", "name_zh", "name_en", "category", "specification",
                  "material", "quantity", "unit", "weight", "position", "supplier",
                  "item_no", "confidence"]


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _round_or_none(value, nd=2):
    return None if value is None else round(value, nd)


def build_record(job_id, kind, source_file, result=None, error=None,
                 finished_at=None, model_info=None):
    """从任务结果构建历史记录摘要。失败任务只含文件与错误信息。"""
    record = {
        "job_id": job_id,
        "kind": kind,
        "finished_at": finished_at or datetime.now().isoformat(timespec="seconds"),
        "file_name": os.path.basename(source_file) if source_file else None,
        "status": "failed" if error else "ok",
    }
    if error:
        record["error"] = str(error)[:500]
        return record
    if not isinstance(result, dict):
        result = {}

    bom = result.get("bom") or {}
    components = bom.get("components") or []
    model = dict(result.get("model_info") or {})
    if model_info:
        model = dict(model_info, **{k: v for k, v in model.items() if v is not None})
    record["document_id"] = result.get("document_id")
    record["source_sha256"] = result.get("source_sha256")

    # ── 模型与配置 ──
    record["model"] = {
        "provider": model.get("provider") or model.get("name"),
        "model": model.get("model"),
        "prompt_version": model.get("prompt_version"),
        "recognition_mode": model.get("recognition_mode"),
        "preserve_printed_rows": model.get("preserve_printed_rows"),
        "knowledge_base": (model.get("knowledge_base") or {}).get("entries")
        if isinstance(model.get("knowledge_base"), dict) else None,
        "pages": _num(model.get("pages")),
        "agent_loop_status": (model.get("agent_loop") or {}).get("status")
        if isinstance(model.get("agent_loop"), dict) else None,
    }

    # ── BOM 行级指标 ──
    fill = {}
    for field in _TRACKED_FIELDS:
        filled = sum(1 for c in components
                     if isinstance(c, dict) and str(c.get(field) or "").strip() != "")
        fill[field] = {"filled": filled, "total": len(components),
                       "rate": _round_or_none(filled / len(components), 3) if components else None}
    confidences = [_num(c.get("confidence")) for c in components if isinstance(c, dict)]
    confidences = [v for v in confidences if v is not None]
    review_rows = [c for c in components if isinstance(c, dict) and c.get("needs_review")]
    review_reasons = Counter()
    for c in review_rows:
        for reason in (c.get("review_reasons") or []):
            review_reasons[str(reason)[:60]] += 1
    record["bom"] = {
        "n_components": len(components),
        "total_quantity": sum(_num(c.get("quantity")) or 0 for c in components
                              if isinstance(c, dict)),
        "field_fill": fill,
        "confidence": {
            "mean": _round_or_none(sum(confidences) / len(confidences), 3) if confidences else None,
            "min": min(confidences) if confidences else None,
            "max": max(confidences) if confidences else None,
        },
        "categories": dict(Counter(str(c.get("category")) for c in components
                                   if isinstance(c, dict) and c.get("category"))),
        "needs_review": {"count": len(review_rows),
                         "reasons": dict(review_reasons.most_common(10))},
        "n_validation_issues": len(bom.get("validation_issues") or []),
        "validation_issues": list((bom.get("validation_issues") or [])[:50]),
    }

    # ── 装配树指标 ──
    tree = bom.get("assembly") or {}
    nodes = tree.get("nodes") or []
    conflicts = tree.get("quantity_conflicts") or []
    record["assembly"] = {
        "inference_status": tree.get("inference_status"),
        "n_nodes": len(nodes),
        "n_unverified": len(tree.get("unverified_nodes") or []),
        "unresolved_component_indices": tree.get("unresolved_component_indices") or [],
        "max_depth": tree.get("max_depth"),
        "n_quantity_conflicts": len(conflicts),
        "quantity_conflicts": [{"part_number": c.get("part_number"),
                                "printed_quantity": c.get("printed_quantity"),
                                "exploded_quantity": c.get("exploded_quantity")}
                               for c in conflicts],
    }

    # ── 标题栏 / 球标 / 尺寸 ──
    record["title_block"] = {
        "fields": result.get("title_block") or {},
        "missing_required": result.get("missing_required") or [],
    }
    balloons = result.get("balloons") or []
    dims = result.get("dimensions") or []
    record["annotations"] = {
        "balloon_count": len(balloons),
        "dimension_count": len(dims),
        "dimension_status": ((result.get("inspection") or {}).get("dimension_extraction") or {}).get("status"),
    }

    # ── 审图发现 ──
    issues = result.get("issues") or []
    by_severity = Counter(str(i.get("severity") or "未分级") for i in issues)
    by_err = Counter(str(i.get("err_id") or "?") for i in issues)
    by_source = Counter(str(i.get("source") or i.get("origin") or "未标注") for i in issues)
    inspection = result.get("inspection") or {}
    record["inspection"] = {
        "n_findings": len(issues),
        "by_severity": dict(by_severity),
        "by_err_id": dict(by_err),
        "by_source": dict(by_source),
        "findings": [{"err_id": i.get("err_id"), "severity": i.get("severity"),
                      "message": str(i.get("message") or "")[:200]} for i in issues[:100]],
        "dimension_extraction_status": (inspection.get("dimension_extraction") or {}).get("status"),
    }

    # ── 耗时与输出 ──
    record["timings"] = {
        "bom_process_time_s": _round_or_none(_num(bom.get("process_time_s")), 1),
        "inspection_process_time_s": _round_or_none(_num(inspection.get("process_time_s")), 1),
    }
    record["outputs"] = [os.path.basename(p) for p in (result.get("outputs") or [])
                         if isinstance(p, str)]
    return record


def append_record(history_dir, record, full_result=None):
    """写入一条记录（同 job_id 覆盖，用于编辑后同步），并落完整结果快照。

    线程安全；写入故障只打日志、绝不抛出。
    """
    try:
        os.makedirs(history_dir, exist_ok=True)
        job_id = record.get("job_id")
        with _LOCK:
            path = os.path.join(history_dir, "history.jsonl")
            lines = []
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    lines = [l for l in f.read().splitlines() if l.strip()]

            def _line_job_id(line):
                try:
                    return json.loads(line).get("job_id")
                except ValueError:
                    return None

            kept = [l for l in lines if _line_job_id(l) != job_id]
            kept.append(json.dumps(record, ensure_ascii=False))
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(kept) + "\n")
            os.replace(tmp, path)
            if full_result is not None:
                spath = os.path.join(history_dir, "%s.json" % job_id)
                tmp2 = spath + ".tmp"
                with open(tmp2, "w", encoding="utf-8", newline="\n") as f:
                    json.dump({"record": record, "result": full_result},
                              f, ensure_ascii=False)
                os.replace(tmp2, spath)
    except OSError as exc:  # 历史写入失败不影响任务本身
        print("[warn] 检测历史写入失败: %s" % exc)


def load_records(history_dir, limit=200, file_name=None, status=None):
    """读取索引（最新在前），返回 (records, summary)。summary 覆盖全部过滤后的记录。"""
    records = []
    path = os.path.join(history_dir, "history.jsonl")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
    if file_name:
        needle = file_name.lower()
        records = [r for r in records if needle in str(r.get("file_name") or "").lower()]
    if status:
        records = [r for r in records if r.get("status") == status]
    ordered = list(reversed(records))
    summary = summarize(records)
    return ordered[: max(0, int(limit))], summary


def summarize(records):
    """跨记录汇总：成功率、平均耗时、行数、文件与模型分布。"""
    ok = [r for r in records if r.get("status") == "ok"]
    failed = [r for r in records if r.get("status") == "failed"]
    bom_times = [r["timings"]["bom_process_time_s"] for r in ok
                 if (r.get("timings") or {}).get("bom_process_time_s") is not None]
    insp_times = [r["timings"]["inspection_process_time_s"] for r in ok
                  if (r.get("timings") or {}).get("inspection_process_time_s") is not None]

    def avg(values):
        return _round_or_none(sum(values) / len(values), 1) if values else None

    models = Counter(str((r.get("model") or {}).get("model") or "?") for r in ok)
    return {
        "total": len(records),
        "ok": len(ok),
        "failed": len(failed),
        "success_rate": _round_or_none(len(ok) / len(records), 3) if records else None,
        "avg_bom_time_s": avg(bom_times),
        "avg_inspection_time_s": avg(insp_times),
        "total_components": sum((r.get("bom") or {}).get("n_components") or 0 for r in ok),
        "total_findings": sum((r.get("inspection") or {}).get("n_findings") or 0 for r in ok),
        "distinct_files": len({r.get("file_name") for r in records if r.get("file_name")}),
        "models": dict(models.most_common(5)),
        "latest_model": (ok[-1].get("model") or {}).get("model") if ok else None,
    }


def load_detail(history_dir, job_id):
    """读取某次任务的完整快照（含完整 result）；不存在返回 None。"""
    if not job_id or any(ch in job_id for ch in ("/\\.")):
        return None
    path = os.path.join(history_dir, "%s.json" % job_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None
