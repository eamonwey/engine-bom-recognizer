"""Reuse recorded extraction; make new real geometry and text verification calls.

This isolates candidate generation. It is NOT a fresh end-to-end model test.
"""
import json,re,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine_bom.webapp import load_web_config
from engine_bom.providers import build_provider
from engine_bom.providers.base import ProviderResponse
from engine_bom.ingestion import load_document
from engine_bom.dimension_links import inspect_dimension_links
from engine_bom.corrections import sha256

folder=ROOT/'data/acceptance/gearbox_fix_20261011'
prior=folder/'iteration10_cross_stage_veto_modified.json'
recorded=json.loads(prior.read_text(encoding='utf8'))
bom=json.loads((folder/'qwen37plus_full_1_original_result.json').read_text(encoding='utf8'))
source=next((ROOT/'data/web_jobs/20261011221848-19b051/file').glob('*.png'))
cfg=load_web_config();provider=build_provider(cfg['provider']);real=provider.analyze
started=time.monotonic();reused=[False]
def analyze(images,prompt):
    task=re.search(r'TASK:([A-Z_]+)',prompt)
    if task and task[1]=='DIMENSION_LINKS' and not reused[0]:
        reused[0]=True
        print('Reusing prior extraction, not a new global model call',flush=True)
        return ProviderResponse(json.dumps({'observations':recorded['observations'],
            'links':[l for l in recorded['links'] if not l.get('proposal')]},ensure_ascii=False))
    print('Real '+(task[1] if task else 'vision')+' at %.1fs'%(time.monotonic()-started),flush=True)
    return real(images,prompt)
provider.analyze=analyze
pages=load_document(str(source),cfg['ingestion'])
result=inspect_dimension_links(provider,[p.original_image or p.image for p in pages],[],bom['bom']['components'],2)
def target(issue):
    if {issue.get('calculation',{}).get(k) for k in ['left_nominal_mm','right_nominal_mm']}!={'60','62'}:return False
    def located(number,y0,y1):
        return any(d.get('bbox') and .18<(d['bbox'][0]+d['bbox'][2])/2<.35
            and y0<(d['bbox'][1]+d['bbox'][3])/2<y1 and number in d.get('value','')
            for d in issue.get('linked_dimensions',[]))
    return located('60',.83,.93) and located('62',.75,.84)
result.update(acceptance_passed=any(target(i) for i in result['issues']),model=provider.model,
    elapsed_s=round(time.monotonic()-started,2),source_sha256=sha256(str(source)),
    extraction_provenance=prior.name,
    context_note='Recorded prior extraction and original same-drawing BOM; only geometry and text verification are new real API calls. Not fresh full modified BOM acceptance.')
(folder/'iteration11_neighbor_geometry_replay.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:result[k] for k in ['status','acceptance_passed','elapsed_s']},ensure_ascii=False))
sys.exit(0 if result['acceptance_passed'] else 1)
