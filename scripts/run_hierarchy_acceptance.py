# -*- coding: utf-8 -*-
"""实测装配父子关系验收包 H01–H04（data/acceptance/assembly_hierarchy_20260926）。

对每张验收图运行完整流水线（BOM 识别 + infer_assembly 装配树推理），
用 engine_bom.evaluation.tree_metrics 对照 expected.json 打分，
输出每用例得分、原始输出与 Markdown 报告。

用法（项目根目录）:
  python scripts/run_hierarchy_acceptance.py                  # 全部用例，真实模型
  python scripts/run_hierarchy_acceptance.py --cases H01 H03  # 指定用例
  python scripts/run_hierarchy_acceptance.py --dry-run        # 只核对夹具与预期，不调用模型

模型与密钥沿用 data/web_settings.json（与 webapp 同一合并逻辑：config.yaml +
deep_merge(web_settings)）。输出写入 data/acceptance/assembly_hierarchy_20260926/results_<时间戳>/。
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine_bom.config import load_config, deep_merge  # noqa: E402
from engine_bom.pipeline import BomPipeline  # noqa: E402
from engine_bom.evaluation.tree_metrics import (evaluate_assembly_case,  # noqa: E402
                                                render_hierarchy_report)

PACK_DIR = os.path.join(ROOT, "data", "acceptance", "assembly_hierarchy_20260926")
ALL_CASES = ["H01", "H02", "H03", "H04"]


def build_config():
    cfg = load_config(os.path.join(ROOT, "config.yaml"))
    settings_path = os.path.join(ROOT, "data", "web_settings.json")
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            cfg = deep_merge(cfg, json.load(f))
    cfg.setdefault("assembly", {})["enabled"] = True
    return cfg


def load_expected(case_id):
    path = os.path.join(PACK_DIR, "%s.expected.json" % case_id)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_image(case_id):
    for ext in (".png", ".pdf"):
        path = os.path.join(PACK_DIR, case_id + ext)
        if os.path.exists(path):
            return path
    raise FileNotFoundError("%s 图纸不存在" % case_id)


def dry_run(cases):
    """不调用模型：核对夹具一致性（BOM 数量守恒、expected 引用合法）。"""
    from engine_bom.assembly import validate_tree
    ok = True
    for case_id in cases:
        expected = load_expected(case_id)
        comps = expected["components"]
        # exploded_quantities 与 components.quantity 守恒（H04 故意不一致，跳过）
        if not expected.get("expected_findings"):
            for comp in comps:
                exp = expected["exploded_quantities"].get(comp["part_number"])
                if exp is not None and exp != comp["quantity"]:
                    print("[FAIL] %s: %s 数量 %s ≠ 展开量 %s" % (case_id, comp["part_number"],
                                                                comp["quantity"], exp))
                    ok = False
        try:
            validate_tree(expected["assembly"], comps)
            note = "validate_tree 通过"
        except (ValueError, TypeError) as exc:
            print("[FAIL] %s: validate_tree: %s" % (case_id, exc))
            ok = False
            continue
        print("[OK] %s: %d 行 BOM / %d 节点 / 深度 %s — %s" % (
            case_id, len(comps), len(expected["assembly"]["nodes"]),
            expected.get("max_depth"), note))
    print("夹具核对: %s" % ("全部一致" if ok else "存在问题"))
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", nargs="*", default=ALL_CASES)
    parser.add_argument("--dry-run", action="store_true", help="只核对夹具，不调用模型")
    args = parser.parse_args()

    if args.dry_run:
        sys.exit(dry_run(args.cases))

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(PACK_DIR, "results_" + stamp)
    os.makedirs(out_dir, exist_ok=True)

    cfg = build_config()
    cfg["output"] = {"dir": out_dir, "formats": ["json"]}
    pipeline = BomPipeline(cfg, base_dir=ROOT)
    model = pipeline.provider.describe()
    print("模型: %s %s" % (model.get("provider", model.get("name", "?")),
                           model.get("model", "")))
    print("输出目录: %s" % out_dir)

    results = []
    for case_id in args.cases:
        expected = load_expected(case_id)
        image = find_image(case_id)
        print("\n== %s (%s) ==" % (case_id, os.path.basename(image)))
        started = time.time()
        result = pipeline.process_file(image)
        if result.status != "ok" or result.bom is None:
            print("[FAIL] 流水线失败: %s" % (result.errors or "未知错误"))
            results.append({"case_id": case_id, "relations": {}, "pipeline_error": result.errors,
                            "unresolved_component_indices": [], "bom_missing": [], "bom_extra": [],
                            "expected_node_count": expected.get("expected_node_count"),
                            "node_count_confirmed": 0, "node_count_unverified": 0,
                            "node_count_total": 0, "expected_max_depth": expected.get("max_depth"),
                            "max_depth": None, "bom_rows_expected": len(expected["components"]),
                            "bom_rows_predicted": 0, "expected_findings":
                                expected.get("expected_findings") or [], "findings_hit": None,
                            "inference_status": "pipeline_failed"})
            continue
        bom = result.bom
        pred_components = [c.to_dict() for c in bom.components]
        tree = bom.assembly or {}
        # 把 BOM 校验问题带给报告（H04 数量冲突检出情况）
        tree["_validation_issues"] = list(bom.validation_issues or [])
        score = evaluate_assembly_case(tree, pred_components, expected)
        score["process_time_s"] = round(time.time() - started, 1)
        rel = score["relations"]
        print("关系 P/R/F1 = %s / %s / %s   用量准确率 = %s   节点 %d(+%d待核) 深度 %s   耗时 %.1fs" % (
            rel.get("precision"), rel.get("recall"), rel.get("f1"),
            rel.get("qty_accuracy"), score["node_count_confirmed"],
            score["node_count_unverified"], score["max_depth"], score["process_time_s"]))
        for issue in [i for i in (tree.get("_validation_issues") or [])][:6]:
            print("  校验: %s" % issue)

        with open(os.path.join(out_dir, "%s.output.json" % case_id), "w",
                  encoding="utf-8") as f:
            json.dump({"components": pred_components, "assembly": {
                k: v for k, v in tree.items() if k != "_validation_issues"},
                "validation_issues": tree.get("_validation_issues") or []},
                f, ensure_ascii=False, indent=2)
        with open(os.path.join(out_dir, "%s.score.json" % case_id), "w",
                  encoding="utf-8") as f:
            json.dump(score, f, ensure_ascii=False, indent=2)
        results.append(score)

    meta = {"模型": "%s %s" % (model.get("provider", model.get("name", "?")),
                              model.get("model", "")),
            "运行时间": stamp, "验收包": os.path.basename(PACK_DIR)}
    report = render_hierarchy_report(results, meta)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + "=" * 60)
    print(report)


if __name__ == "__main__":
    main()
