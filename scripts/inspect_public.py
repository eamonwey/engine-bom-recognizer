"""Real hybrid inspection smoke test; never claims unlabeled errors as GT."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from engine_bom.webapp import load_web_config
from engine_bom.providers import build_provider
from engine_bom.hybrid_inspection import inspect

root = Path(__file__).resolve().parents[1]
cfg = load_web_config()
cfg["provider"]["name"] = "openai_compat"
provider = build_provider(cfg["provider"])
bom = json.loads((root / "data/reports/public/v2/predictions/mill_stop.json").read_text(encoding="utf-8"))
with Image.open(root / "data/public/libretexts/mill_stop.png") as image:
    result = inspect(provider, [image.convert("RGB")],
                     {"drawing_name":"Mill Work Stop","drawing_no":"RTC-30010",
                      "drawing_type":"assembly","material_applicable":False},
                     bom["components"], [], list(range(1,10)))
result["evaluation_scope"] = "pipeline smoke test; drawing defects not independently labeled"
out = root / "data/reports/public/hybrid_inspection.json"
out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps({"visual_status":result["visual_status"],"issues":result["issues"]},ensure_ascii=False,indent=2))
