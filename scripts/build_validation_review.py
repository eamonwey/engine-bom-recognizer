"""Publish local review pack with source images, labels, outputs and blind entry."""
import json
import shutil
from pathlib import Path
import fitz

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"static/validation"


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    cases=[]
    for manifest_path in [ROOT/"data/validation/manifest.json",ROOT/"data/validation/synthetic/manifest.json"]:
        manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
        for c in manifest["cases"]:
            record=dict(c)
            annotation=json.loads((ROOT/c["annotation"]).read_text(encoding="utf-8"))
            record["reference"]=annotation
            notes_path=ROOT/"data/validation/label_correction_proposals.json"
            record["label_audit_notes"]=[n for n in json.loads(notes_path.read_text(encoding="utf-8")) if n["case_id"]==c["id"]] if notes_path.exists() else []
            directory=OUT/c["id"];directory.mkdir(exist_ok=True)
            shutil.copy2(str(ROOT/c["input"]),str(directory/"source.pdf"))
            record["pdf"]=c["id"]+"/source.pdf"
            record["images"]=[]
            if c.get("synthetic"):
                doc=fitz.open(str(ROOT/c["input"]))
                doc[0].get_pixmap(matrix=fitz.Matrix(1.7,1.7),alpha=False).save(str(directory/"page_1.png"))
                record["images"]=[c["id"]+"/page_1.png"]
                doc.close()
            else:
                for i,path in enumerate([c["figure_image"]]+c["table_images"],1):
                    name="page_%d.png"%i;shutil.copy2(str(ROOT/path),str(directory/name))
                    record["images"].append(c["id"]+"/"+name)
            for run in ["external_reference_v1","synthetic_cloud_v1","synthetic_rules_v1","synthetic_cloud_v3","external_reference_v3_direct","synthetic_cloud_v3_direct","synthetic_cloud_v4_scoped","case23_itemlabel_diagnostic","case14_compact_diagnostic","external_reference_v4_direct","qwen37_max_reference_v1","qwen37_max_defects_v1"]:
                path=ROOT/"data/reports/validation"/run/(c["id"]+".result.json")
                if path.exists():
                    record.setdefault("runs",{})[run]=json.loads(path.read_text(encoding="utf-8"))
                    pred=path.parent/"predictions"/(c["id"]+".json")
                    if pred.exists():record["runs"][run]["predicted_bom"]=json.loads(pred.read_text(encoding="utf-8"))
            cases.append(record)
    (OUT/"collection.json").write_text(json.dumps({"cases":cases},ensure_ascii=False,indent=2),encoding="utf-8")
    print("review pack",len(cases),"cases")


if __name__=="__main__":main()
