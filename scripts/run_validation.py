"""Run frozen reference/acceptance BOM or synthetic end-to-end defect evaluation."""
import argparse
import concurrent.futures
import copy
import datetime
import hashlib
import json
import sys
import time
import threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine_bom.evaluation.validation import check_manifest, digest, review_consensus, score_defects
from engine_bom.evaluation.strict import evaluate_strict, summarize_strict
from engine_bom.evaluation.dataset import load_bom_json
from engine_bom.schema import BomDocument
from engine_bom.pipeline import BomPipeline
from engine_bom.webapp import load_web_config

ROOT=Path(__file__).resolve().parents[1]
INFERENCE_FILES=["engine_bom/prompts.py","engine_bom/pipeline.py","engine_bom/agent_loop.py",
    "engine_bom/ingestion.py","engine_bom/inspect_rules.py","engine_bom/hybrid_inspection.py",
    "engine_bom/titleblock.py","engine_bom/providers/openai_compat.py"]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--manifest",default="data/validation/manifest.json")
    ap.add_argument("--out",required=True)
    ap.add_argument("--provider",choices=["mock","openai_compat"],default="openai_compat")
    ap.add_argument("--reference-only",action="store_true")
    ap.add_argument("--reviews",nargs="*",default=[])
    ap.add_argument("--defects",action="store_true")
    ap.add_argument("--rule-oracle",action="store_true")
    ap.add_argument("--limit",type=int)
    ap.add_argument("--workers",type=int,default=2)
    ap.add_argument("--prompt-version",choices=["v1","v2","v3"],default="v3")
    ap.add_argument("--direct",action="store_true",help="Explicitly disable Qwen thinking; separate frozen profile")
    ap.add_argument("--targeted-defects",action="store_true",help="Only three generator-specified defect classes; no full-page completeness claim")
    ap.add_argument("--case-id",nargs="*",help="Explicit diagnostic subset, recorded in freeze")
    args=ap.parse_args()
    manifest_path=ROOT/args.manifest
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    errors=check_manifest(ROOT,manifest)
    if errors: raise RuntimeError("; ".join(errors))
    cases=manifest["cases"][:args.limit] if args.limit else manifest["cases"]
    if args.case_id:
        unknown=set(args.case_id)-{c["id"] for c in manifest["cases"]}
        if unknown: raise ValueError("Unknown cases: "+str(unknown))
        cases=[c for c in cases if c["id"] in args.case_id]
    reviews=[]
    for path in args.reviews:
        submission=json.loads((ROOT/path).read_text(encoding="utf-8"))
        reviews.extend(submission["reviews"])
    approved={c["id"]:review_consensus(c,reviews) for c in cases}
    if not args.defects and not args.reference_only and any(r["status"]!="approved" for r in approved.values()):
        raise RuntimeError("Acceptance blocked: missing two independent human approvals or unresolved disagreement. Use --reference-only for provisional reference matching.")
    if args.rule_oracle and not args.defects: raise ValueError("rule oracle is synthetic defects only")
    if args.defects and any(not c.get("synthetic") for c in cases): raise ValueError("full-page defect metrics require fully labeled synthetic pages")
    cfg=load_web_config();cfg["provider"]["name"]=args.provider
    cfg["recognition"]["prompt_version"]=args.prompt_version;cfg["recognition"]["mode"]="whole_doc"
    cfg["ingestion"]["preprocess"]={"enabled":False}
    # This corpus has at most 5 images per PDF; document contents only, never TSV/GT.
    cfg["provider"].setdefault("openai_compat",{})["timeout"]=180
    cfg["provider"]["openai_compat"]["max_tokens"]=12000
    cfg["provider"]["openai_compat"]["retries"]=1
    if args.direct:
        profile = cfg["provider"]["openai_compat"]
        if str(profile.get("model", "")).lower().startswith("qwen3"):
            profile["enable_thinking"] = False
        else:
            profile.pop("enable_thinking", None)
    if args.targeted_defects:
        if not args.defects: raise ValueError("targeted scope requires --defects")
        cfg.setdefault("inspection",{})["scope_description"]="仅检查同一D1尺寸数值矛盾、BOM序号与零件引出序号不对应、装配零件数量非正。不检查尺寸完整性、图示风格、材料或排版规范"
    out=ROOT/args.out
    if out.exists(): raise RuntimeError("Use a new output directory; baseline results are immutable")
    out.mkdir(parents=True)
    profile=cfg["provider"].get("openai_compat",{})
    freeze={"created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"manifest_sha256":digest(manifest_path),
        "cases":[c["id"] for c in cases],"inference_sha256":{p:digest(ROOT/p) for p in INFERENCE_FILES},
        "configuration":{"provider":args.provider,"model":profile.get("model"),"base_url":profile.get("base_url"),
                         "recognition":cfg["recognition"],"ingestion":cfg["ingestion"],"agent_loop":cfg.get("agent_loop"),
                         "enable_thinking":profile.get("enable_thinking"),"timeout":180,"max_tokens":12000,"retries":1,"inspection":cfg.get("inspection")},
        "label_status":"generator_exact_synthetic" if args.defects else ("author_machine_generated_unverified" if args.reference_only else "two_human_consensus"),
        "scope":"rule oracle only; excludes visual extraction" if args.rule_oracle else ("synthetic end-to-end" if args.defects else "external provisional reference matching" if args.reference_only else "human-reviewed acceptance"),
        "reviews_sha256":{p:digest(ROOT/p) for p in args.reviews}}
    (out/"freeze.json").write_text(json.dumps(freeze,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"manifest.snapshot.json").write_bytes(manifest_path.read_bytes())
    import shutil
    for path in (ROOT/"engine_bom").rglob("*.py"):
        dest=out/"source_snapshot"/path.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(str(path),str(dest))
    (out/"source_snapshot_hashes.json").write_text(json.dumps({str(p.relative_to(out/"source_snapshot")).replace("\\","/"):digest(p)
        for p in (out/"source_snapshot").rglob("*.py")},indent=2),encoding="utf-8")

    quota_stop = threading.Event()
    def run(case):
        started=time.time();status="failed";error=None;issues=[];bom=BomDocument(document_id=case["id"])
        annotation=json.loads((ROOT/case["annotation"]).read_text(encoding="utf-8"))
        try:
            if quota_stop.is_set():
                raise RuntimeError("AllocationQuota.FreeTierOnly: batch blocked after quota exhaustion; no new API call")
            if args.rule_oracle:
                from engine_bom.inspect_rules import run_all_checks
                oracle=annotation["oracle_extraction"]
                issues=run_all_checks(oracle["title_block"],annotation["components"],oracle["dimensions"],oracle["balloons"])
                status="ok"
            else:
                local=copy.deepcopy(cfg);local["output"]={"dir":str(out/"predictions"),"formats":["json"]}
                pipeline=BomPipeline(local,str(ROOT))
                result=pipeline.process_file(str(ROOT/case["input"]))
                status=result.status;error="; ".join(result.errors) or None
                if result.bom is not None: bom=result.bom
                if args.defects and status=="ok":
                    from engine_bom.ingestion import load_document
                    from engine_bom.titleblock import extract_titleblock,extract_dims_and_balloons
                    from engine_bom.hybrid_inspection import inspect
                    images=[p.image for p in load_document(str(ROOT/case["input"]),local["ingestion"])]
                    title=extract_titleblock(pipeline.provider,images[-1:],len(images))
                    dims=extract_dims_and_balloons(pipeline.provider,images)
                    inspection=inspect(pipeline.provider,images,title["fields"],bom.to_dict()["components"],dims["dimensions"],dims["balloons"],local.get("inspection"))
                    issues=inspection["issues"]
                    (out/(case["id"]+".inspection.json")).write_text(json.dumps({"title_block":title,"dimensions":dims,"inspection":inspection},ensure_ascii=False,indent=2),encoding="utf-8")
                    if inspection["visual_status"]!="validated": status="incomplete_inspection"
        except Exception as exc:
            error=type(exc).__name__+": "+str(exc);status="failed"
        if error and "AllocationQuota.FreeTierOnly" in error:
            quota_stop.set()
            status="blocked_quota"
        if args.defects:
            scores=score_defects(issues,annotation["defects"])
        else:
            if args.reference_only: gt=load_bom_json(str(ROOT/case["annotation"]))
            else:
                from engine_bom.schema import BomComponent
                gt=BomDocument(document_id=case["id"],components=[BomComponent(**c) for c in approved[case["id"]]["components"]])
            scores=evaluate_strict(bom,gt)
            # A failed call is never counted as a correct empty BOM.
            if status!="ok":scores["exact_bom"]=False
        rec={"case_id":case["id"],"status":status,"error":error,"elapsed_s":round(time.time()-started,3),"scores":scores,"issues":issues}
        (out/(case["id"]+".result.json")).write_text(json.dumps(rec,ensure_ascii=False,indent=2),encoding="utf-8")
        return rec

    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(args.workers,3))) as pool:
        futures=[pool.submit(run,c) for c in cases]
        for future in concurrent.futures.as_completed(futures):
            r=future.result();results.append(r);print(r["case_id"],r["status"],r["elapsed_s"],r["scores"],flush=True)
            (out/"progress.json").write_text(json.dumps({"completed":len(results),"total":len(cases)},indent=2),encoding="utf-8")
    if args.defects:
        tp=sum(r["scores"]["tp"] for r in results);fp=sum(r["scores"]["fp"] for r in results);fn=sum(r["scores"]["fn"] for r in results)
        negatives=[r for r in results if r["scores"]["n_expected"]==0]
        summary={"tp":tp,"fp":fp,"fn":fn,"precision":tp/(tp+fp) if tp+fp else 0,"recall":tp/(tp+fn) if tp+fn else 0,
                 "negative_false_alarm_rate":sum(r["scores"]["negative_false_alarm"] for r in negatives)/len(negatives) if negatives else None,
                 "localized_tp":sum(r["scores"]["localized_tp"] for r in results),"negative_cases":len(negatives)}
    else:summary=summarize_strict([r["scores"] for r in results])
    report={"scope":freeze["scope"],"label_status":freeze["label_status"],"factory_acceptance":False,"human_reviewed_corpus":not args.reference_only and not args.defects and args.provider != "mock",
            "n_cases":len(cases),"failures":sum(r["status"]!="ok" for r in results),"summary":summary,"results":sorted(results,key=lambda r:r["case_id"])}
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"scope":report["scope"],"n_cases":len(cases),"failures":report["failures"],"summary":summary},ensure_ascii=False),flush=True)


if __name__=="__main__":main()
