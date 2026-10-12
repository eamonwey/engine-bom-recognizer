# -*- coding: utf-8 -*-
"""批量实验运行器：一份 YAML 描述多个 run（不同模型/提示词/模式），

自动完成 批量推理 -> 逐档评测 -> 报告落盘 -> 跨 run 对比。
得到数据集后，只需准备 data/raw + data/annotations，然后：
    python -m engine_bom.cli experiment configs/experiment_demo.yaml
"""
import copy
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .config import deep_merge, load_config
from .evaluation.dataset import discover_documents, load_bom_json
from .evaluation.metrics import evaluate_corpus, evaluate_document, render_markdown_report
from .pipeline import BomPipeline


def _load_spec(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.endswith((".yaml", ".yml")):
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    return json.loads(text) if text.strip() else {}


def _resolve(path: str, spec_dir: str) -> str:
    """相对路径优先相对 spec 文件目录，其次相对当前目录。"""
    if os.path.isabs(path):
        return path
    for base in (spec_dir, os.getcwd()):
        candidate = os.path.normpath(os.path.join(base, path))
        if os.path.exists(candidate):
            return candidate
    return os.path.normpath(os.path.join(os.getcwd(), path))


def _apply_run_overrides(config: Dict[str, Any], run: Dict[str, Any]) -> Dict[str, Any]:
    config = copy.deepcopy(config)
    provider_name = run.get("provider")
    if provider_name:
        config.setdefault("provider", {})["name"] = str(provider_name)
    opts = run.get("provider_options") or {}
    if opts and provider_name:
        section = config["provider"].setdefault(str(provider_name), {})
        config["provider"][str(provider_name)] = deep_merge(section, opts)
    if run.get("prompt_version"):
        config.setdefault("recognition", {})["prompt_version"] = str(run["prompt_version"])
    if run.get("mode"):
        config.setdefault("recognition", {})["mode"] = str(run["mode"])
    return config


def run_experiment(spec_path: str, base_config_path: Optional[str] = None) -> List[Dict[str, Any]]:
    spec_path = os.path.abspath(spec_path)
    spec_dir = os.path.dirname(spec_path)
    spec = _load_spec(spec_path)
    experiment = str(spec.get("experiment") or os.path.splitext(os.path.basename(spec_path))[0])
    runs = spec.get("runs") or []
    if not runs:
        raise ValueError("实验规格 %s 中没有定义 runs" % spec_path)

    base_config = load_config(base_config_path)
    ds = spec.get("dataset") or {}
    raw_dir = _resolve(str(ds.get("raw_dir") or "data/raw"), spec_dir)
    anno_dir = _resolve(str(ds.get("annotation_dir") or "data/annotations"), spec_dir)
    out = spec.get("output") or {}
    pred_root = _resolve(str(out.get("pred_root") or "data/predictions"), spec_dir)
    report_root = _resolve(str(out.get("report_root") or "data/reports"), spec_dir)

    docs = discover_documents(raw_dir, anno_dir)
    annotated = [d for d in docs if d["annotation_path"]]
    print("实验 %s: %d 个输入文档, %d 个带标注" % (experiment, len(docs), len(annotated)))

    summaries: List[Dict[str, Any]] = []
    for run in runs:
        run_name = str(run.get("name") or "run")
        print("\n===== run: %s =====" % run_name)
        config = _apply_run_overrides(base_config, run)
        pred_dir = os.path.join(pred_root, experiment, run_name)
        config.setdefault("output", {})["dir"] = pred_dir

        pipeline = BomPipeline(config, base_dir=spec_dir)
        results = pipeline.process_many([d["raw_path"] for d in docs])
        ok = sum(1 for r in results if r.status == "ok")
        print("推理完成: %d/%d 成功" % (ok, len(results)))

        doc_results = []
        from .schema import BomDocument
        from .evaluation.strict import evaluate_strict, summarize_strict
        strict_results = []
        fresh_results = {r.document_id:r for r in results}
        for doc in annotated:
            fresh = fresh_results.get(doc["doc_id"])
            pred = fresh.bom if fresh and fresh.status == "ok" and fresh.bom is not None else BomDocument(document_id=doc["doc_id"])
            gt = load_bom_json(doc["annotation_path"] or "")
            doc_results.append(evaluate_document(pred, gt))
            strict_results.append(dict(evaluate_strict(pred, gt),document_id=doc["doc_id"]))

        model_info = next((r.bom.model_info for r in results if r.bom is not None), {})
        meta = {
            "experiment": experiment,
            "run": run_name,
            "model": model_info.get("model", "-"),
            "prompt_version": model_info.get("prompt_version", "-"),
            "recognition_mode": model_info.get("recognition_mode", "-"),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        agg = evaluate_corpus(doc_results, meta=meta)
        agg["strict"] = summarize_strict(strict_results)

        run_report_dir = os.path.join(report_root, experiment)
        if not os.path.isdir(run_report_dir):
            os.makedirs(run_report_dir, exist_ok=True)
        report_json = os.path.join(run_report_dir, "%s.report.json" % run_name)
        report_md = os.path.join(run_report_dir, "%s.report.md" % run_name)
        with open(report_json, "w", encoding="utf-8", newline="\n") as f:
            json.dump(agg, f, ensure_ascii=False, indent=2)
        with open(report_md, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_markdown_report(agg))
        print("评测报告: %s" % report_md)

        det = agg.get("component_detection", {})
        summaries.append({
            "run": run_name,
            "model": meta["model"],
            "n_documents": agg.get("n_documents", 0),
            "macro_f1": (det.get("macro_f1") or {}).get("mean"),
            "macro_precision": (det.get("macro_precision") or {}).get("mean"),
            "macro_recall": (det.get("macro_recall") or {}).get("mean"),
            "field_accuracy": (agg.get("field_accuracy_macro") or {}).get("mean"),
            "exact_bom_rate": (agg.get("exact_bom_rate") or {}).get("mean"),
            "avg_process_time_s": agg.get("avg_process_time_s"),
            "report_md": report_md,
        })

    _write_comparison(report_root, experiment, summaries)
    return summaries


def _write_comparison(report_root: str, experiment: str, summaries: List[Dict[str, Any]]) -> None:
    if not summaries:
        return
    lines = ["# 实验对比: %s" % experiment, "",
             "| run | 模型 | 文档数 | P | R | F1 | 字段准确率 | 完全正确率 | 平均耗时(s) |",
             "|---|---|---|---|---|---|---|---|---|"]

    def _f(x):
        return "-" if x is None else ("%.4f" % x if isinstance(x, (int, float)) else str(x))

    for s in summaries:
        lines.append("| %s | %s | %d | %s | %s | %s | %s | %s | %s |" % (
            s["run"], s["model"], s["n_documents"],
            _f(s["macro_precision"]), _f(s["macro_recall"]), _f(s["macro_f1"]),
            _f(s["field_accuracy"]), _f(s["exact_bom_rate"]), _f(s["avg_process_time_s"])))
    path = os.path.join(report_root, experiment, "comparison.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("\n跨 run 对比: %s" % path)
