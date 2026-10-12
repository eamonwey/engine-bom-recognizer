# -*- coding: utf-8 -*-
"""命令行入口。

常用命令（在项目根目录执行）:
  python -m engine_bom.cli process data/raw/demo_engine_bom.pdf
  python -m engine_bom.cli batch data/raw
  python -m engine_bom.cli evaluate data/predictions data/annotations
  python -m engine_bom.cli experiment configs/experiment_demo.yaml
  python -m engine_bom.cli init-dataset
  python -m engine_bom.cli info
"""
import argparse
import copy
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .config import cfg_get, load_config
from .evaluation.dataset import discover_documents, load_bom_json
from .evaluation.metrics import evaluate_corpus, evaluate_document, render_markdown_report
from .experiment import run_experiment
from .ingestion import is_supported
from .pipeline import BomPipeline, print_result_summary
from .providers import PROVIDERS, ProviderConfigError
from .schema import BomDocument

# Windows 控制台中文输出保护
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engine-bom",
        description="发动机元器件识别与 BOM 生成系统（输入 PDF/图片，输出结构化 BOM）",
        formatter_class=argparse.RawDescriptionHelpFormatter)

    # 公共覆盖参数：挂在子命令上（写法: engine-bom process 文件 --provider xxx）
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", default=None, help="配置文件路径（YAML/JSON，默认用内置配置）")
    common.add_argument("--provider", default=None, choices=sorted(PROVIDERS),
                        help="覆盖配置中的视觉模型 provider")
    common.add_argument("--mode", default=None, choices=["per_page", "whole_doc"], help="覆盖识别模式")
    common.add_argument("--prompt-version", default=None, help="覆盖提示词版本")
    common.add_argument("--formats", default=None, help="覆盖导出格式，逗号分隔：json,csv,xlsx")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("process", parents=[common], help="识别单个 PDF/图片并导出 BOM")
    p.add_argument("input", help="输入文件（PDF 或图片）")
    p.add_argument("-o", "--output-prefix", default=None, help="输出前缀（不含扩展名），默认 data/predictions/<文档名>")

    p = sub.add_parser("batch", parents=[common], help="批量识别目录下全部 PDF/图片")
    p.add_argument("dir", nargs="?", default="data/raw", help="输入目录（默认 data/raw）")
    p.add_argument("--out", default=None, help="输出目录覆盖")

    p = sub.add_parser("evaluate", parents=[common], help="评测：预测目录 vs 标注目录")
    p.add_argument("pred_dir", help="预测 JSON 所在目录")
    p.add_argument("anno_dir", help="人工标注 JSON 所在目录")
    p.add_argument("-o", "--output-prefix", default=None, help="报告输出前缀（默认 data/reports/eval）")

    p = sub.add_parser("experiment", parents=[common], help="按 YAML 规格批量做实验（多 run + 评测 + 对比）")
    p.add_argument("spec", help="实验规格文件（见 configs/experiment_demo.yaml）")

    sub.add_parser("init-dataset", parents=[common], help="初始化数据集目录结构与示例标注")
    sub.add_parser("info", parents=[common], help="查看当前配置与依赖状态")
    p = sub.add_parser("correct", help="根据已复核 patches JSON 生成图纸修订副本")
    p.add_argument("input")
    p.add_argument("patches", help="含 reviewer 与 patches 的 JSON")
    p.add_argument("output")
    return parser


def _apply_overrides(config: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    config = copy.deepcopy(config)
    if getattr(args, "provider", None):
        config.setdefault("provider", {})["name"] = args.provider
    if getattr(args, "mode", None):
        config.setdefault("recognition", {})["mode"] = args.mode
    if getattr(args, "prompt_version", None):
        config.setdefault("recognition", {})["prompt_version"] = args.prompt_version
    if getattr(args, "formats", None):
        config.setdefault("output", {})["formats"] = [x.strip() for x in args.formats.split(",") if x.strip()]
    if getattr(args, "out", None):
        config.setdefault("output", {})["dir"] = args.out
    return config


def _cmd_process(args: argparse.Namespace) -> int:
    config = _apply_overrides(load_config(args.config), args)
    try:
        pipeline = BomPipeline(config)
    except ProviderConfigError as exc:
        print("[错误] %s" % exc)
        return 2
    result = pipeline.process_file(args.input)
    if args.output_prefix and result.bom is not None:
        from .export import export_bom
        formats = [str(x) for x in cfg_get(config, "output.formats", ["json"]) or []]
        result.outputs = export_bom(result.bom, args.output_prefix, formats)
    print_result_summary(result)
    return 0 if result.status == "ok" else 1


def _cmd_batch(args: argparse.Namespace) -> int:
    config = _apply_overrides(load_config(args.config), args)
    try:
        pipeline = BomPipeline(config)
    except ProviderConfigError as exc:
        print("[错误] %s" % exc)
        return 2
    if not os.path.isdir(args.dir):
        print("[错误] 目录不存在: %s" % args.dir)
        return 2
    paths = [os.path.join(args.dir, n) for n in sorted(os.listdir(args.dir))
             if is_supported(os.path.join(args.dir, n), config.get("ingestion") or {})]
    if not paths:
        print("目录中没有受支持的输入文件: %s" % args.dir)
        return 0
    print("批量识别 %d 个文件（provider=%s, mode=%s）" % (
        len(paths), cfg_get(config, "provider.name"), cfg_get(config, "recognition.mode")))
    results = pipeline.process_many(paths, on_result=print_result_summary)
    ok = sum(1 for r in results if r.status == "ok")
    print("\n完成: %d 成功 / %d 失败" % (ok, len(results) - ok))
    return 0 if ok == len(results) else 1


def _cmd_evaluate(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.pred_dir):
        print("[错误] 预测目录不存在: %s" % args.pred_dir)
        return 2
    if not os.path.isdir(args.anno_dir):
        print("[错误] 标注目录不存在: %s" % args.anno_dir)
        return 2
    doc_results = []
    strict_results, missing_predictions = [], []
    from .evaluation.strict import evaluate_strict, summarize_strict
    for name in sorted(os.listdir(args.anno_dir)):
        if not name.endswith(".json"):
            continue
        doc_id = os.path.splitext(name)[0]
        pred_json = os.path.join(args.pred_dir, doc_id + ".json")
        if not os.path.isfile(pred_json):
            print("[warn] %s 无对应预测 %s" % (doc_id, pred_json))
            missing_predictions.append(doc_id)
            pred = BomDocument(document_id=doc_id)
        else:
            pred = load_bom_json(pred_json)
        gt = load_bom_json(os.path.join(args.anno_dir, name))
        doc_results.append(evaluate_document(pred, gt))
        strict_results.append(dict(evaluate_strict(pred, gt), document_id=doc_id))
    if not doc_results:
        print("没有可评测的文档对（标注目录: %s）" % args.anno_dir)
        return 1
    agg = evaluate_corpus(doc_results, meta={"experiment": "cli-evaluate", "run": "-",
                                             "model": "-", "prompt_version": "-"})
    agg["strict"] = summarize_strict(strict_results)
    agg["missing_predictions"] = missing_predictions
    prefix = args.output_prefix or os.path.join("data", "reports", "eval")
    parent = os.path.dirname(os.path.abspath(prefix))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(prefix + ".report.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(agg, f, ensure_ascii=False, indent=2)
    with open(prefix + ".report.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(render_markdown_report(agg))
    print(render_markdown_report(agg))
    print("严格 P/R/F1: %.4f / %.4f / %.4f" % (agg["strict"]["precision"],agg["strict"]["recall"],agg["strict"]["f1"]))
    print("报告已写入: %s.report.md / .json" % prefix)
    return 0


def _cmd_experiment(args: argparse.Namespace) -> int:
    try:
        run_experiment(args.spec, base_config_path=args.config)
    except (ValueError, FileNotFoundError) as exc:
        print("[错误] %s" % exc)
        return 2
    return 0


def _cmd_init_dataset(args: argparse.Namespace) -> int:
    from .config import DEFAULT_CONFIG
    base = os.getcwd()
    for sub in ("data/raw", "data/annotations", "data/predictions", "data/reports", "data/knowledge"):
        path = os.path.join(base, sub.replace("/", os.sep))
        os.makedirs(path, exist_ok=True)
        print("目录就绪: %s" % path)
    kb_path = os.path.join(base, "data", "knowledge", "engine_rules.txt")
    if not os.path.isfile(kb_path):
        with open(kb_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(_EXAMPLE_KNOWLEDGE)
        print("已写入示例知识库: %s" % kb_path)
    example = os.path.join(base, "data", "annotations", "_annotation_example.json")
    if not os.path.isfile(example):
        with open(example, "w", encoding="utf-8", newline="\n") as f:
            json.dump(_EXAMPLE_ANNOTATION, f, ensure_ascii=False, indent=2)
        print("已写入标注示例: %s（复制为 <文档名>.json 并填写真实标注）" % example)
    print("支持格式: PDF + %s" % DEFAULT_CONFIG["ingestion"]["image_formats"])
    return 0


_EXAMPLE_KNOWLEDGE = """# 企业元器件命名/分类规则（每行一条，识别时自动检索注入提示词；把本文件换成你们企业的规范即可）
# 在 config.yaml 中开启: knowledge.enabled: true
图号统一大写，前缀 ENG- 表示发动机自制件，STD- 表示标准件
数量字段只填整数，单位默认为“件”，成套供货时单位填“套”
活塞、活塞环、连杆、曲轴归类为曲柄连杆机构
机油泵、机油滤清器、油底壳归类为润滑系统
"""

_EXAMPLE_ANNOTATION = {
    "document_id": "_annotation_example",
    "source_file": "把本文件复制为与输入文档同名的 .json，例如 demo_engine_bom.pdf 对应 demo_engine_bom.json",
    "components": [
        {"item_no": 1, "part_number": "ENG-PST-003", "name_zh": "活塞", "name_en": "Piston",
         "category": "曲柄连杆机构", "specification": "Φ86×60mm", "material": "铝合金 4032",
         "quantity": 4, "unit": "件", "position": "气缸体内", "supplier": "", "remark": ""}
    ],
}


def _cmd_info(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print("engine-bom v%s" % __import__("engine_bom").__version__)
    print("配置来源: %s" % (args.config or "内置默认"))
    print("provider: %s (可选: %s)" % (cfg_get(config, "provider.name"), sorted(PROVIDERS)))
    print("识别模式: %s | 提示词版本: %s" % (cfg_get(config, "recognition.mode"),
                                           cfg_get(config, "recognition.prompt_version")))
    print("输出目录: %s | 导出格式: %s" % (cfg_get(config, "output.dir"), cfg_get(config, "output.formats")))
    deps = {}
    for mod, name in (("fitz", "PyMuPDF"), ("PIL", "Pillow"), ("yaml", "PyYAML"), ("openpyxl", "openpyxl")):
        try:
            m = __import__(mod)
            deps[name] = getattr(m, "__version__", "ok")
        except ImportError:
            deps[name] = "未安装"
    print("依赖: %s" % json.dumps(deps, ensure_ascii=False))
    oc = cfg_get(config, "provider.openai_compat") or {}
    env = {k: os.environ.get(v) for k, v in
           (("VISION_BASE_URL", "VISION_BASE_URL"), ("VISION_MODEL", "VISION_MODEL"), ("VISION_API_KEY", "VISION_API_KEY"))}
    print("openai_compat 配置: base_url=%s model=%s" % (oc.get("base_url") or env["VISION_BASE_URL"] or "(空)",
                                                        oc.get("model") or env["VISION_MODEL"] or "(空)"))
    print("VISION_API_KEY: %s" % ("已设置" if env["VISION_API_KEY"] else "未设置"))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "correct":
        from .corrections import apply_corrections
        with open(args.patches, encoding="utf-8") as f:
            reviewed = json.load(f)
        journal = apply_corrections(args.input, args.output, reviewed["patches"], reviewed["reviewer"])
        print("修订副本: " + journal["output"])
        return 0
    handlers = {
        "process": _cmd_process,
        "batch": _cmd_batch,
        "evaluate": _cmd_evaluate,
        "experiment": _cmd_experiment,
        "init-dataset": _cmd_init_dataset,
        "info": _cmd_info,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
