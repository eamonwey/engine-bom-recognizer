"""Exact identity and end-to-end field accuracy including missed GT rows."""
from collections import defaultdict
from ..schema import normalize_part_number, normalize_text
from .metrics import EVAL_FIELDS, field_equal, gt_provides


def evaluate_strict(pred, gt):
    # Only use the GT's identity type; a wrong nonempty part number cannot be rescued
    # by fuzzy names. If GT has no part number, exact printed name is used.
    used = set()
    pairs = []
    for j, g in enumerate(gt.components):
        candidates = []
        for i, p in enumerate(pred.components):
            if i in used:
                continue
            same = (normalize_part_number(p.part_number) == normalize_part_number(g.part_number)) if g.part_number else (
                bool(g.name_en or g.name_zh) and normalize_text(p.name_en or p.name_zh) == normalize_text(g.name_en or g.name_zh))
            if same:
                candidates.append(i)
        if candidates:
            i = candidates[0]
            used.add(i)
            pairs.append((i, j))
    matched = {j: i for i, j in pairs}
    fields = {}
    for name in EVAL_FIELDS:
        total = sum(gt_provides(name, g) for g in gt.components)
        correct = sum(gt_provides(name, gt.components[j]) and field_equal(name, pred.components[i], gt.components[j])
                      for i, j in pairs)
        fields[name] = {"correct": correct, "total": total, "accuracy": correct / total if total else None}
    tp, ng, np = len(pairs), len(gt.components), len(pred.components)
    p, r = (tp / np if np else 0), (tp / ng if ng else 0)
    total = sum(x["total"] for x in fields.values())
    correct = sum(x["correct"] for x in fields.values())
    return {"identity": "exact GT part number, else exact name; no fuzzy fallback",
            "n_gt": ng, "n_pred": np, "tp": tp, "fp": np - tp, "fn": ng - tp,
            "precision": p, "recall": r, "f1": 2*p*r/(p+r) if p+r else 0,
            "end_to_end_field_accuracy": correct / total if total else None,
            "fields": fields, "exact_bom": ng == np == tp and correct == total}


def summarize_strict(results):
    tp = sum(r["tp"] for r in results)
    fp = sum(r["fp"] for r in results)
    fn = sum(r["fn"] for r in results)
    p = tp / (tp + fp) if tp + fp else 0
    r = tp / (tp + fn) if tp + fn else 0
    fields = {}
    for name in EVAL_FIELDS:
        total = sum(x["fields"][name]["total"] for x in results)
        correct = sum(x["fields"][name]["correct"] for x in results)
        fields[name] = {"correct":correct,"total":total,"accuracy":correct/total if total else None}
    total = sum(x["total"] for x in fields.values())
    return {"n_documents":len(results),"tp":tp,"fp":fp,"fn":fn,"precision":p,"recall":r,
            "f1":2*p*r/(p+r) if p+r else 0,"fields":fields,
            "end_to_end_field_accuracy":sum(x["correct"] for x in fields.values())/total if total else None,
            "exact_bom_rate":sum(x["exact_bom"] for x in results)/len(results) if results else None,
            "documents":results}
