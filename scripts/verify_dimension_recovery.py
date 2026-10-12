"""Stage-only real test using the newly read high-resolution source BOM.

This is a controlled pair of the same drawing. It is not a claim that the
low-resolution modified drawing's full BOM extraction has passed.
"""
import argparse,json,re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine_bom.webapp import load_web_config
from engine_bom.providers import build_provider
from engine_bom.ingestion import load_document
from engine_bom.dimension_links import inspect_dimension_links


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--label',choices=['original','modified'],default='modified')
    parser.add_argument('--prefix',default='iteration7_microtext');args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.prefix):parser.error('simple prefix required')
    folder=ROOT/'data/acceptance/gearbox_fix_20261011'
    original=json.loads((folder/'qwen37plus_full_1_original_result.json').read_text(encoding='utf8'))
    own=json.loads((folder/('qwen37plus_full_1_'+args.label+'_result.json')).read_text(encoding='utf8'))
    job='20261011203652-87494f' if args.label=='original' else '20261011221848-19b051'
    source=next((ROOT/'data/web_jobs'/job/'file').glob('*.png'));cfg=load_web_config()
    p=build_provider(cfg['provider']);analyze=p.analyze;started=time.monotonic()
    def trace(images,prompt):
        task=re.search(r'TASK:([A-Z_]+)',prompt)
        print('Calling '+(task.group(1) if task else 'vision')+' at %.1fs'%(time.monotonic()-started),flush=True)
        return analyze(images,prompt)
    p.analyze=trace
    pages=load_document(str(source),cfg['ingestion']);images=[page.original_image or page.image for page in pages]
    r=inspect_dimension_links(p,images,own.get('dimensions') or [],original['bom']['components'],2,local_text=True)
    issues=r.get('issues') or []
    def target_conflict(issue):
        calc=issue.get('calculation',{})
        if {calc.get('left_nominal_mm'),calc.get('right_nominal_mm')}!={'60','62'}:return False
        def located(number,y0,y1):
            return any(d.get('bbox') and .18<(d['bbox'][0]+d['bbox'][2])/2<.35
                and y0<(d['bbox'][1]+d['bbox'][3])/2<y1 and number in d.get('value','')
                for d in issue.get('linked_dimensions',[]))
        return located('60',.83,.93) and located('62',.75,.84)
    passed=(r.get('status')=='checked' and bool(r.get('observations')) and not issues) if args.label=='original' else any(target_conflict(i) for i in issues)
    r.update(acceptance_passed=passed,model=p.model,elapsed_s=round(time.monotonic()-started,2),
             context_note='Fresh original BOM used for a controlled same-drawing pair; stage-only, not full modified BOM acceptance.')
    (folder/(args.prefix+'_'+args.label+'.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'status':r['status'],'acceptance_passed':passed,'issues':[i['message'] for i in issues]},ensure_ascii=False))
    sys.exit(0 if passed else 1)


if __name__=='__main__':main()
