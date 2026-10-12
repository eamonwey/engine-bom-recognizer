"""Check every published source asset and static path containment; no model call."""
import json
import urllib.error
import urllib.request
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine_bom.evaluation.validation import check_manifest

ROOT = Path(__file__).resolve().parents[1]
BASE = (sys.argv[1].rstrip('/') if len(sys.argv) > 1 else "http://127.0.0.1:8788") + "/static/validation/"
for name in ["data/validation/manifest.json", "data/validation/synthetic/manifest.json"]:
    assert not check_manifest(ROOT, json.loads((ROOT/name).read_text(encoding="utf-8")))
collection = json.load(urllib.request.urlopen(BASE+"collection.json"))
assert len(collection["cases"]) == 70
for case in collection["cases"]:
    with urllib.request.urlopen(BASE+case["pdf"]) as response:
        assert response.read(5) == b"%PDF-"
        assert response.headers.get_content_type() == "application/pdf"
    for image in case["images"]:
        with urllib.request.urlopen(BASE+image) as response:
            assert response.read(8) == b"\x89PNG\r\n\x1a\n"
for path in ["../../config.yaml", "../../../data/web_settings.json"]:
    try:
        urllib.request.urlopen(BASE+path)
        raise AssertionError("static traversal allowed")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403
print("PASS: both manifests; all 70 PDFs and source images; static traversal blocked")
