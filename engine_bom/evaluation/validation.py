"""Immutable corpus checks, independent review gate, and defect metrics."""
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_manifest(root, manifest):
    errors=[]
    ids=set()
    groups={}
    for c in manifest["cases"]:
        if c["id"] in ids:
            errors.append("duplicate case: "+c["id"])
        ids.add(c["id"])
        previous=groups.setdefault(c["group_id"],c["split"])
        if previous != c["split"]:
            errors.append("group split leakage: "+c["group_id"])
        for key in ("input","annotation"):
            target=(Path(root)/c[key]).resolve()
            if Path(root).resolve() not in target.parents:
                errors.append("path escapes root: "+c[key]); continue
            if not target.exists() or digest(target)!=c[key+"_sha256"]:
                errors.append("missing or changed "+key+": "+c["id"])
    return errors


def review_consensus(case, reviews):
    accepted=[]
    for r in reviews:
        if (r.get("case_id")==case["id"] and r.get("input_sha256")==case["input_sha256"]
            and r.get("reviewer","").strip() and r.get("independent") is True
            and r.get("reviewer_kind")=="human" and r.get("status")=="approved"
            and valid_review_rows(r) and r.get("reviewed_at")):
            accepted.append(r)
    names={r["reviewer"].strip().casefold() for r in accepted}
    if len(names)<2:
        return {"status":"pending","reason":"two distinct independent human approvals required"}
    payloads={json.dumps(r["components"],sort_keys=True,ensure_ascii=False) for r in accepted}
    if len(payloads)>1:
        return {"status":"disagreement","reason":"resolve differences and re-submit signed independent records; do not average labels"}
    return {"status":"approved","components":accepted[0]["components"],"reviewers":sorted(names)}


def valid_review_rows(record):
    from ..schema import COMPONENT_FIELDS, TEXT_FIELDS
    rows=record.get("components")
    if not isinstance(rows,list):return False
    if not rows:return record.get("empty_confirmed") is True
    for c in rows:
        if not isinstance(c,dict) or any(k not in COMPONENT_FIELDS for k in c):return False
        if not (c.get("part_number") or c.get("name_en") or c.get("name_zh")):return False
        if "quantity" not in c or "source_page" not in c:return False
        for key in ("item_no","quantity"):
            value=c.get(key)
            if value is not None and (not isinstance(value,int) or isinstance(value,bool)):return False
        page=c["source_page"]
        if not isinstance(page,int) or isinstance(page,bool) or page<1:return False
        if any(c.get(key) is not None and not isinstance(c[key],str) for key in TEXT_FIELDS if key in c):return False
    return True


def score_defects(predictions, expected):
    """Fully labeled synthetic page only. Match type and case, each finding once.

    Localization is reported separately; repeated predictions count as FP.
    Real pages with unknown errors must not use this full-page metric.
    """
    remaining=list(expected)
    tp=0
    localized=0
    for p in predictions:
        match=next((i for i,g in enumerate(remaining) if p.get("err_id")==g["err_id"]),None)
        if match is not None:
            g=remaining.pop(match);tp+=1
            if p.get("source_page")==g.get("source_page") and box_iou(p.get("bbox"),g.get("bbox"))>=0.1:
                localized+=1
    fp=len(predictions)-tp;fn=len(remaining)
    return {"tp":tp,"fp":fp,"fn":fn,"localized_tp":localized,"n_expected":len(expected),
            "negative_false_alarm":not expected and bool(predictions)}


def box_iou(a,b):
    if not (isinstance(a,list) and isinstance(b,list) and len(a)==len(b)==4): return 0
    area=lambda x:max(0,x[2]-x[0])*max(0,x[3]-x[1])
    overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=area(a)+area(b)-overlap
    return overlap/union if union else 0
