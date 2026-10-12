"""Compare real human submissions; do not silently edit frozen reference labels."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine_bom.evaluation.validation import check_manifest,review_consensus,digest

ROOT=Path(__file__).resolve().parents[1]
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("submissions",nargs="+");p.add_argument("--out",default="data/validation/review_consensus.json");a=p.parse_args()
    manifest=json.loads((ROOT/"data/validation/manifest.json").read_text(encoding="utf-8"));errors=check_manifest(ROOT,manifest)
    if errors:raise RuntimeError("; ".join(errors))
    reviews=[]
    for path in a.submissions:reviews.extend(json.loads((ROOT/path).read_text(encoding="utf-8"))["reviews"])
    results={c["id"]:review_consensus(c,reviews) for c in manifest["cases"]}
    report={"approved":sum(r["status"]=="approved" for r in results.values()),"total":len(results),"acceptance_ready":all(r["status"]=="approved" for r in results.values()),
            "submission_hashes":{path:digest(ROOT/path) for path in a.submissions},"results":results,
            "limit":"Names and independence are reviewer declarations, not authenticated identities. Engineering competence must be checked by the project owner."}
    target=ROOT/a.out
    if target.exists():raise RuntimeError("Use a new --out path to preserve earlier review records")
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ["approved","total","acceptance_ready"]}))
