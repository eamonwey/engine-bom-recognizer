"""Pinned 30-case external reference set; upstream TSVs are machine generated."""
import concurrent.futures
import csv
import hashlib
import io
import json
import urllib.request
from pathlib import Path
from PIL import Image
import fitz

ROOT = Path(__file__).resolve().parents[1]
REV = "c079c44f602c227109793cf2fdb3919ea8a99331"
REPO = "enginuity2025/enginuity-bench"
BASE = "https://huggingface.co/datasets/" + REPO + "/resolve/" + REV + "/"
PREFIX = "task-1-component-identification/human-validation-set/"


def fetch(path):
    relative = path[len(PREFIX):]
    dest = ROOT / "data/public/enginuity/samples" / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    blob = dest.read_bytes() if dest.exists() else urllib.request.urlopen(BASE+path,timeout=90).read()
    if dest.suffix == ".png":
        Image.open(io.BytesIO(blob)).verify()
    dest.write_bytes(blob)
    return {"path":str(dest.relative_to(ROOT)).replace("\\","/"),"url":BASE+path,
            "sha256":hashlib.sha256(blob).hexdigest()}


def main():
    inventory = json.loads((ROOT / "data/public/enginuity/repository_inventory.json").read_text(encoding="utf-8"))
    if inventory["sha"] != REV:
        raise RuntimeError("inventory is not pinned revision")
    selected = [x["rfilename"] for x in inventory["siblings"]
                if x["rfilename"].startswith(PREFIX) and len(x["rfilename"].split("/")) == 4
                and x["rfilename"].split("/")[2].startswith("figure_")
                and int(x["rfilename"].split("/")[2].split("_")[1]) <= 30
                and x["rfilename"].endswith((".png",".tsv"))]
    records = []
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch,p):p for p in selected}
        for f in concurrent.futures.as_completed(futures):
            try:
                rec=f.result(); records.append(rec); print(rec["path"],flush=True)
            except Exception as e:
                failures.append({"path":futures[f],"error":str(e)})
    if failures:
        (ROOT / "data/public/enginuity/download_failures.json").write_text(json.dumps(failures,indent=2),encoding="utf-8")
        raise RuntimeError("download failures: %d" % len(failures))
    cases=[]
    for i in range(1,31):
        source=ROOT / "data/public/enginuity/samples" / ("figure_%d"%i)
        case_id="enginuity_%02d"%i
        doc=fitz.open()
        images=[source/"figure.png"]+sorted(source.glob("table_*.png"),key=lambda p:int(p.stem.split("_")[1]))
        for image in images:
            with Image.open(str(image)) as im: w,h=im.size
            page=doc.new_page(width=w*72/200,height=h*72/200)
            page.insert_image(page.rect,filename=str(image))
        output=ROOT/"data/validation/inputs"/(case_id+".pdf");output.parent.mkdir(parents=True,exist_ok=True)
        doc.save(str(output));doc.close()
        components=[]
        raw_rows=[]
        for tsv in sorted(source.glob("table_*.tsv"),key=lambda p:int(p.stem.split("_")[1])):
            table_index=int(tsv.stem.split("_")[1])
            for row in csv.DictReader(io.StringIO(tsv.read_text(encoding="utf-8-sig")),delimiter="\t"):
                raw_rows.append(row)
                q=str(row.get("quantity","")).strip()
                components.append({"item_no":int(row["item_no"]) if str(row.get("item_no","")).isdigit() else None,
                    "part_number":row.get("part_no","").strip(),"name_en":row.get("description","").strip(),
                    "quantity":int(q) if q.isdigit() else None,"source_page":table_index+1})
        gt={"document_id":case_id,"source_file":output.name,"components":components,"raw_rows":raw_rows,
            "ground_truth":{"status":"author_machine_generated_unverified","upstream_generator":"Claude Sonnet 4.5 according to upstream README",
                            "expert_approved":False,"group_id":"enginuity_entire_source","split":"heldout_reference",
                            "scope":"printed repair-parts rows, not manufacturing BOM; unknown quantities are not inferred"}}
        annotation=ROOT/"data/validation/annotations"/(case_id+".json");annotation.parent.mkdir(parents=True,exist_ok=True)
        annotation.write_text(json.dumps(gt,ensure_ascii=False,indent=2),encoding="utf-8")
        cases.append({"id":case_id,"group_id":"enginuity_entire_source","split":"heldout_reference","synthetic":False,
            "input":str(output.relative_to(ROOT)).replace("\\","/"),"input_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
            "annotation":str(annotation.relative_to(ROOT)).replace("\\","/"),"annotation_sha256":hashlib.sha256(annotation.read_bytes()).hexdigest(),
            "figure_image":str(images[0].relative_to(ROOT)).replace("\\","/"),"table_images":[str(p.relative_to(ROOT)).replace("\\","/") for p in images[1:]],
            "row_count":len(components),"review_status":"pending_two_independent_humans","drawing_type":"pending_visual_classification"})
    manifest={"version":"external-reference-1","source":"https://huggingface.co/datasets/"+REPO,"revision":REV,
        "selection":"first 30 upstream audit figures by numeric ID, selected before recognition; every associated table included",
        "license_note":"HF pinned card says Apache-2.0; paper search excerpt says CC BY 4.0. Retain attribution; do not assume resolved licensing for redistribution/training.",
        "limitations":["Upstream labels explicitly generated by Claude; audit-set name does not prove human approval",
                       "Upstream README and audit README disagree about counts, UOC and part-number semantics",
                       "Repair-parts manuals differ from dimensioned manufacturing assembly drawings",
                       "Conservative grouping keeps entire source in heldout; do not tune on these cases and claim future blindness"],
        "cases":cases,"downloaded_files":sorted(records,key=lambda r:r["path"])}
    target=ROOT/"data/validation/manifest.json"
    target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print("cases",len(cases),"rows",sum(c["row_count"] for c in cases),flush=True)


if __name__ == "__main__":
    main()
