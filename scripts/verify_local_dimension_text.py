"""Check local OCR on exact historical sources; this is not a geometry verdict."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine_bom.dimension_text import read_fit_text
from engine_bom.ingestion import load_document
from engine_bom.webapp import load_web_config
from scripts.diagnose_gearbox_records import RUNS,MODIFIED

def main():
    folder=ROOT/'data/acceptance/gearbox_fix_20261011';checks={}
    cfg=load_web_config()
    for name,job in [('original',RUNS[0]),('modified',MODIFIED)]:
        source=next((ROOT/'data/web_jobs'/job/'file').glob('*.png'))
        pages=load_document(str(source),cfg['ingestion'])
        result=read_fit_text([p.original_image or p.image for p in pages])
        target=[o for o in result['observations'] if o['fit_body']==('60H9/h9' if name=='modified' else '62H9/h9')
                and .18<(o['bbox'][0]+o['bbox'][2])/2<.35 and .83<(o['bbox'][1]+o['bbox'][3])/2<.94]
        checks[name+'_lower_end_fit_text_located']=bool(target)
        result['target_readings']=target;result['note']='Only text rereading and localization; geometry equivalence not certified.'
        (folder/(name+'_local_text.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(name,result['status'],json.dumps(target,ensure_ascii=False),flush=True)
    (folder/'local_text_acceptance.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
    assert all(checks.values()),checks

if __name__=='__main__':main()
