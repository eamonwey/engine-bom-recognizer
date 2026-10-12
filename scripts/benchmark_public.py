"""One real-model held-out example. GT is never passed to the recognition model."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine_bom.webapp import load_web_config
from engine_bom.pipeline import BomPipeline
from engine_bom.evaluation.dataset import load_bom_json
from engine_bom.evaluation.metrics import evaluate_document
from engine_bom.evaluation.strict import evaluate_strict


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="openai_compat", choices=["mock", "openai_compat"])
    parser.add_argument("--prompt-version", default="v1", choices=["v1", "v2"])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cfg = load_web_config()
    cfg["provider"]["name"] = args.provider
    cfg["recognition"]["prompt_version"] = args.prompt_version
    cfg["output"] = {"dir": str(root / ("data/reports/public/" + args.prompt_version + "/predictions")), "formats": ["json", "csv"]}
    cfg["provider"]["openai_compat"]["retries"] = 1
    prediction = BomPipeline(cfg, str(root)).process_file(str(root / "data/public/libretexts/mill_stop.png"))
    if prediction.status != "ok":
        raise RuntimeError("; ".join(prediction.errors))
    gt = load_bom_json(str(root / "data/public/libretexts/annotations/mill_stop.json"))
    report = {"scope": "one public drawing, independent visual transcription; not factory acceptance",
              "prompt_version": args.prompt_version,
              "evaluation_use": "development after first baseline; never claim a blind test after tuning",
              "legacy": evaluate_document(prediction.bom, gt),
              "strict": evaluate_strict(prediction.bom, gt)}
    out = root / ("data/reports/public/" + args.prompt_version + "/mill_stop.report.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
