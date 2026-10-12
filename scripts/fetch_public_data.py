"""Pinned small engineering-drawing OCR dataset. Does not manufacture BOM labels."""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

COMMIT = "f6f96517a531021ac946f6fc45063bdb77440085"
BASE = "https://raw.githubusercontent.com/javvi51/edocr2/" + COMMIT + "/"
SAMPLES = ["Adapterplatte", "BM_part", "Candle_holder", "Gripper", "LIU0010", "example_dwg", "halter"]


def main():
    root = Path(__file__).resolve().parents[1] / "data/public/edocr2"
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"repository": "https://github.com/javvi51/edocr2", "commit": COMMIT,
                "license": "repository MIT; original image ownership should be checked before training",
                "task": "dimension OCR; not BOM or drawing-error ground truth", "samples": []}
    for name in SAMPLES:
        files = []
        for ext in ["json", "png" if name == "example_dwg" else "jpg"]:
            url = BASE + "tests/test_samples/" + name + "." + ext
            blob = urllib.request.urlopen(url, timeout=30).read()
            (root / (name + "." + ext)).write_bytes(blob)
            files.append({"url": url, "file": name + "." + ext,
                          "sha256": hashlib.sha256(blob).hexdigest()})
        original = json.loads((root / (name + ".json")).read_text(encoding="utf-8"))
        w, h = original["imageWidth"], original["imageHeight"]
        dims = []
        for shape in original["shapes"]:
            if shape.get("shape_type") not in ("rectangle", "polygon") or shape["label"] == "other_info":
                continue
            points = shape["points"]
            dims.append({"text": shape["label"], "source_page": 1,
                         "bbox": [min(p[0] for p in points)/w, min(p[1] for p in points)/h,
                                  max(p[0] for p in points)/w, max(p[1] for p in points)/h]})
        (root / (name + ".dimensions.json")).write_text(json.dumps({"document_id": name,
            "task": "dimension_ocr", "status": "author_supplied_labels", "group_id": name,
            "expert_approved_by_customer": False, "dimensions": dims}, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["samples"].append({"id": name, "dimension_count": len(dims), "files": files})
        (root / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(name, len(dims), flush=True)
    (root / "LICENSE").write_bytes(urllib.request.urlopen(BASE + "LICENSE", timeout=30).read())


if __name__ == "__main__":
    main()
