"""Explicitly synthetic parametric drawing fixtures. Never factory ground truth."""
import hashlib
import json
from pathlib import Path
import fitz

ROOT=Path(__file__).resolve().parents[1]


def build(product,variant):
    doc=fitz.open();page=doc.new_page(width=840,height=594)
    text=lambda x,y,s,size=12:page.insert_text((x,y),s,fontsize=size,fontname="helv")
    text(28,28,"SYNTHETIC BENCHMARK DRAWING - NOT FOR MANUFACTURE",15)
    length=80+product*4
    page.draw_rect(fitz.Rect(45,85,45+length*2,165),color=(0,0,0),width=1)
    for x in [65,25+length*2]:
        for y in [105,145]:page.draw_circle((x,y),5,color=(0,0,0))
    text(50,65,"FRONT VIEW")
    text(55,192,"D1 = %d mm"%length)
    page.draw_rect(fitz.Rect(420,85,420+length*2,165),color=(0,0,0),width=1)
    text(425,65,"TOP VIEW: same plate length D1")
    shown_length=length+5 if variant=="dimension_conflict" else length
    text(425,192,"D1 = %d mm"%shown_length)
    text(55,222,"Assembly callouts (unique part types): 1, 2, 3")
    page.draw_line((45,260),(795,260),color=(0,0,0))
    text(45,279,"ITEM       PART NUMBER             DESCRIPTION                      MATERIAL           QTY")
    components=[]
    correct=[]
    for i,(name,mat,q) in enumerate([("BASE PLATE","Q235",1),("COVER PLATE","Q235",1),("M6 BOLT","Q235",4)],1):
        no=9 if variant=="item_mismatch" and i==2 else i
        qty=0 if variant=="quantity_zero" and i==3 else q
        c={"item_no":no,"part_number":"SYN-%02d-%02d"%(product,i),"name_en":name,"material":mat,"quantity":qty,"source_page":1}
        components.append(c);correct.append(dict(c,item_no=i,quantity=q))
        y=305+(i-1)*30
        text(46,y,str(no));text(115,y,c["part_number"]);text(300,y,name);text(535,y,mat);text(735,y,str(qty))
    text(45,419,"Units: mm. D1 identifies the SAME plate length in both views.")
    text(45,439,"Parts list counts assembled components. Quantities must be positive.")
    text(45,469,"Drawing name: SYNTHETIC PLATE ASSEMBLY %02d"%product)
    text(45,489,"Drawing no: SYN-ASM-%02d       Material: Q235       Scale: 2:1"%product)
    text(45,509,"Designer: BENCHMARK GENERATOR       Date: 2026-09-17       Revision: A")
    text(45,549,"Generated test fixture; intentionally changed annotations may be present.",10)
    case_id="synthetic_%02d_%s"%(product,variant)
    out=ROOT/"data/validation/synthetic/inputs"/(case_id+".pdf");out.parent.mkdir(parents=True,exist_ok=True)
    doc.save(str(out));doc.close()
    defects=[]
    if variant!="clean":
        box={"quantity_zero":[.85,.58,.91,.63],"item_mismatch":[.048,.525,.09,.57],"dimension_conflict":[.5,.30,.71,.335]}[variant]
        defects=[{"err_id":"ERR-01" if variant=="dimension_conflict" else "ERR-08","category":variant,
                  "source_page":1,"bbox":box,"evidence":{
                      "quantity_zero":"M6 BOLT quantity printed as 0",
                      "item_mismatch":"BOM item 9 conflicts with callout 2",
                      "dimension_conflict":"Same D1 length printed as %d and %d mm"%(length,shown_length)}[variant],
                  "correct_value":str({"quantity_zero":4,"item_mismatch":2,"dimension_conflict":length}[variant]),
                  "basis":"deterministic generator design specification; fully labeled synthetic fixture only"}]
    gt={"document_id":case_id,"components":components,"correct_components":correct,"defects":defects,
        "ground_truth":{"status":"generator_exact_synthetic","expert_approved":False,"synthetic":True},
        "oracle_extraction":{"title_block":{"drawing_name":"SYNTHETIC PLATE ASSEMBLY %02d"%product,"drawing_no":"SYN-ASM-%02d"%product,"material":"Q235","designer":"BENCHMARK GENERATOR","date":"2026-09-17"},
             "dimensions":[{"tag":"D1","value":str(length),"unit":"mm","view":"FRONT"},{"tag":"D1","value":str(shown_length),"unit":"mm","view":"TOP"}],"balloons":[1,2,3]}}
    ann=ROOT/"data/validation/synthetic/annotations"/(case_id+".json");ann.parent.mkdir(parents=True,exist_ok=True);ann.write_text(json.dumps(gt,indent=2),encoding="utf-8")
    return {"id":case_id,"group_id":"synthetic_plate_template_all","split":"synthetic_regression","synthetic":True,"variant":variant,
            "input":str(out.relative_to(ROOT)).replace("\\","/"),"input_sha256":hashlib.sha256(out.read_bytes()).hexdigest(),
            "annotation":str(ann.relative_to(ROOT)).replace("\\","/"),"annotation_sha256":hashlib.sha256(ann.read_bytes()).hexdigest()}


if __name__=="__main__":
    cases=[build(p,v) for p in range(1,11) for v in ["clean","item_mismatch","quantity_zero","dimension_conflict"]]
    (ROOT/"data/validation/synthetic/manifest.json").write_text(json.dumps({"version":"synthetic-defects-1","scope":"40 fully labeled synthetic fixtures; 10 clean and 10 positives per error category; not real defect accuracy","cases":cases},indent=2),encoding="utf-8")
    print("created",len(cases),"synthetic drawings")
