"""Offline regressions and optional live spatial/installation-stage checks.

Uses historical BOM rows as context, not as an independently verified full BOM.
Never rewrites the historical jobs and never exports credentials.
"""
import argparse
import copy
import hashlib
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.diagnose_gearbox_records import load,RUNS,MODIFIED
from engine_bom.assembly import infer_assembly,validate_tree
from engine_bom.providers.base import ProviderResponse
from engine_bom.inspect_rules import check_dimensions,check_bearing_fits,check_titleblock
from engine_bom.hybrid_inspection import gate_visual_chains

OUTPUT=ROOT/'data/acceptance/gearbox_fix_20261011'


def save(name,value):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def offline():
    replayed=[]
    for job in RUNS+[MODIFIED]:
        r=load(job)
        replayed.append({'job':job,'dimension_issues':check_dimensions(r['dimensions']),
                         'bearing_issues':check_bearing_fits(r['bom']['components'],r['dimensions']),
                         'material_issues':[i for i in check_titleblock(r['title_block']) if i['err_id']=='ERR-06']})
    broken=load(RUNS[1]);events=broken['bom']['assembly']['events']
    class Saved:
        name='recorded_no_network'
        def __init__(self):self.i=0
        def analyze(self,*args):
            raw=events[self.i]['raw_text'];self.i+=1
            return ProviderResponse(raw,'GLM-5.3-Flash')
    tree=infer_assembly(Saved(),[object()],broken['bom']['components'],dict(method='installation',max_attempts=3,verify_visual=False))
    third=load(RUNS[2]);old=third['bom']['assembly']
    safe=validate_tree({'nodes':copy.deepcopy(old['nodes'])},third['bom']['components'],True)
    seal_index=next(i for i,c in enumerate(third['bom']['components']) if c.get('item_no')==21)
    historical_cross=[s for i in broken['issues'] if i['err_id']=='ERR-01' for s in i.get('sources',[]) if s.get('origin')=='vlm']
    allowed,unknown=gate_visual_chains(historical_cross,[])
    checks={'historical_semantic_dimension_groups_removed':all(not r['dimension_issues'] for r in replayed),
            'unbound_bearing_proximity_does_not_bless_a_defect':all(not r['bearing_issues'] for r in replayed),
            'assembly_material_boolean_does_not_create_false_defect':all(not r['material_issues'] for r in replayed),
            'failed_tree_retains_candidates':bool(tree['unverified_nodes']) and not tree['nodes'],
            'contradictory_oil_seal_parent_not_accepted':not any(n['component_index']==seal_index for n in safe['nodes']),
            'contradictory_oil_seal_evidence_preserved':any(n['component_index']==seal_index for n in safe['unverified_nodes']),
            'old_cross_view_false_height_report_is_unknown':not allowed and bool(unknown)}
    save('offline_replay',{'checks':checks,'rule_replays':replayed,'failed_tree':tree,'safe_tree':safe,'old_visual_unverified':unknown})
    for key,value in checks.items():print(('PASS' if value else 'FAIL')+': '+key,flush=True)
    return all(checks.values())


def live_one(label,job,stage):
    from engine_bom.webapp import load_web_config
    from engine_bom.providers import build_provider
    from engine_bom.ingestion import load_document
    from engine_bom.dimension_links import inspect_dimension_links
    cfg=load_web_config();provider=build_provider(cfg['provider']);r=load(job)
    source=next((ROOT/'data/web_jobs'/job/'file').glob('*.png'))
    pages=load_document(str(source),cfg['ingestion']);images=[p.original_image or p.image for p in pages]
    started=time.time()
    if stage=='links':
        result=inspect_dimension_links(provider,images,r['dimensions'],r['bom']['components'],cfg['inspection'].get('dimension_link_attempts',2),
                                       local_text=cfg['inspection'].get('local_dimension_text',False))
    elif stage=='assembly':result=infer_assembly(provider,images,r['bom']['components'],cfg['assembly'])
    else:raise ValueError(stage)
    result.update(elapsed_s=round(time.time()-started,2),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  model=provider.model,context_note='Historical BOM context; fresh model stage, not full extraction pipeline')
    if stage=='links':
        issues=result.get('issues') or []
        if job==MODIFIED:
            checks={'modified_60_62_conflict_located':any(
                {i.get('calculation',{}).get('left_nominal_mm'),i.get('calculation',{}).get('right_nominal_mm')}=={'60','62'}
                and any(d.get('bbox') and .18<sum(d['bbox'][::2])/2<.35 and .83<sum(d['bbox'][1::2])/2<.93
                    and '60' in d.get('value','') for d in i.get('linked_dimensions',[])) for i in issues)}
        else:checks={'original_no_dimension_conflict':not issues and bool(result.get('observations'))}
    else:
        indexed={n['id']:n for n in result.get('nodes',[])}
        seals=[n for n in indexed.values() if r['bom']['components'][n['component_index']].get('item_no')==21]
        checks={'usable_installation_graph_retained':bool(indexed),
                'accepted_oil_seal_parent_not_shaft':all(n.get('parent_id') in indexed and
                   r['bom']['components'][indexed[n['parent_id']]['component_index']].get('item_no')==20 for n in seals)}
    result['acceptance_checks']=checks
    save(label,result)
    summary={'label':label,'status':result.get('status') or result.get('inference_status'),'issues':[i['message'] for i in result.get('issues',[])],
             'nodes':len(result.get('nodes',[])),'unverified':len(result.get('unverified_nodes',[])), 'elapsed_s':result['elapsed_s'],'checks':checks}
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--repeats',type=int,default=1)
    parser.add_argument('--assembly',action='store_true');parser.add_argument('--prefix',default='');args=parser.parse_args()
    if args.prefix and not __import__('re').fullmatch('[A-Za-z0-9_-]+',args.prefix):parser.error('prefix must be a simple label')
    passed=offline()
    if args.live:
        tasks=[('original_links_%d'%i,RUNS[0],'links') for i in range(1,args.repeats+1)]
        tasks+=[('modified_links_%d'%i,MODIFIED,'links') for i in range(1,args.repeats+1)]
        if args.assembly:tasks+=[('original_assembly_%d'%i,RUNS[0],'assembly') for i in range(1,args.repeats+1)]
        tasks=[(args.prefix+'_'+label if args.prefix else label,job,stage) for label,job,stage in tasks]
        summaries=[]
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending={pool.submit(live_one,*task):task[0] for task in tasks}
            for future in as_completed(pending):
                try:summaries.append(future.result())
                except Exception as exc:
                    summaries.append({'label':pending[future],'status':'exception','error_type':type(exc).__name__})
                    print(pending[future]+': failed '+type(exc).__name__,flush=True)
        save((args.prefix+'_' if args.prefix else '')+'live_summary',summaries)
        passed=passed and all(s.get('checks') and all(s['checks'].values()) for s in summaries)
    sys.exit(0 if passed else 1)


if __name__=='__main__':main()
