"""Read-only consistency audit of four captured gearbox runs. No API calls."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
RUNS=['20261011203652-87494f','20261011223236-10deaf','20261011224735-08bb53']
MODIFIED='20261011221848-19b051'


def load(job):
    return json.loads((ROOT/'data/detection_history'/(job+'.json')).read_text(encoding='utf-8'))['result']


def summary(job):
    r=load(job);bom=r['bom'];tree=bom.get('assembly') or {}
    by_id={n['id']:n for n in tree.get('nodes',[])}
    def name(index):
        return bom['components'][index].get('name_zh') if type(index) is int and 0<=index<len(bom['components']) else str(index)
    pairs=[]
    for n in tree.get('nodes',[]):
        parent=by_id.get(n.get('parent_id'))
        pairs.append({'child':name(n.get('component_index')),'parent':name(parent['component_index']) if parent else None,
                      'quantity_per_parent':n.get('quantity_per_parent')})
    return {'job_id':job,'hash':r.get('source_sha256'),'model':bom.get('model_info',{}).get('model'),
        'dimension_count':len(r.get('dimensions',[])),'nodes':len(pairs),
        'assembly_status':tree.get('inference_status') or tree.get('status'),
        'unverified_nodes':len(tree.get('unverified_nodes',[])),
        'issues':[{'err_id':i.get('err_id'),'origin':i.get('origin'),'rule_id':i.get('rule_id'),
                   'message':i.get('message'),'evidence':i.get('evidence')} for i in r.get('issues',[])],
        'relations':pairs}


def stage_replay():
    """Replay real saved provider text and minimize dimension grouping failures."""
    import copy
    from engine_bom.assembly import infer_assembly
    from engine_bom.providers.base import ProviderResponse
    from engine_bom.inspect_rules import check_dimensions,check_bearing_fits

    broken=load(RUNS[1])
    captured=broken['bom']['assembly']['events']
    class RecordedProvider:
        name='recorded_no_network'
        def __init__(self):self.position=0
        def analyze(self,images,prompt):
            response=ProviderResponse(raw_text=captured[self.position]['raw_text'],model='GLM-5.3-Flash')
            self.position+=1
            return response
    replay=infer_assembly(RecordedProvider(),[object()],broken['bom']['components'],
                          {'enabled':True,'max_attempts':3,'method':'installation','verify_visual':False})
    cases={}
    for job in RUNS+[MODIFIED]:
        result=load(job)
        messages=[i['message'] for i in check_dimensions(result['dimensions'])]
        repeat=[i['message'] for i in check_dimensions(copy.deepcopy(result['dimensions']))]
        cases[job]={'dimension_rule_messages':messages,'same_input_replay_stable':messages==repeat,
                    'current_bearing_rule_messages':[i['message'] for i in check_bearing_fits(result['bom']['components'],result['dimensions'])],
                    'historical_dimension_messages':[i['message'] for i in result['issues'] if i.get('err_id')=='ERR-01'],
                    'visual_status':result['inspection']['visual_status'],
                    'focus_sweep':result['inspection'].get('focus_sweep')}
    minimal=[{'part_id':'gearbox','tag':'轴伸直径','value':'Φ18h7','view':'D-D'},
             {'part_id':'gearbox','tag':'轴伸直径','value':'Φ24h7','view':'C-C'}]
    distinct=copy.deepcopy(minimal)
    distinct[0]['feature_id']='input_shaft_extension'
    distinct[1]['feature_id']='output_shaft_extension'
    contrast={'two_distinct_shafts_with_only_shared_tag':[i['message'] for i in check_dimensions(minimal)],
              'same_values_with_distinct_feature_ids':[i['message'] for i in check_dimensions(distinct)]}
    stages={'empty_tree_real_loop_replay':{'nodes':len(replay['nodes']),
              'status':replay['inference_status'],'errors':[e['errors'] for e in replay['events']]},
            'cases':cases,'minimal_grouping_counterfactual':contrast,
            'source_mtime':{name:__import__('datetime').datetime.fromtimestamp((ROOT/name).stat().st_mtime).isoformat(timespec='seconds')
                           for name in ['engine_bom/inspect_rules.py','engine_bom/assembly.py','engine_bom/hybrid_inspection.py']}}
    assert len(replay['nodes'])==0 and len(replay['events'])==3, 'Captured empty-tree symptom did not reproduce'
    assert all(c['same_input_replay_stable'] for c in cases.values()), 'Unexpected rule nondeterminism'
    assert contrast['two_distinct_shafts_with_only_shared_tag']==[], 'Semantic labels must not establish feature identity'
    assert contrast['same_values_with_distinct_feature_ids']==[]
    return stages


def main():
    records=[summary(job) for job in RUNS]
    checks={'same_original_hash':len({r['hash'] for r in records})==1,
            'every_original_run_has_assembly':all(r['nodes']>0 for r in records),
            'stable_original_dimension_count':len({r['dimension_count'] for r in records})==1,
            'stable_original_relations':len({json.dumps(sorted(r['relations'],key=lambda p:(p['child'],p['parent'] or '')),sort_keys=True,ensure_ascii=False) for r in records})==1}
    # Preserve the captured pre-fix baseline rather than overwriting its evidence.
    output=ROOT/'data/acceptance/gearbox_postfix_replay_20261012'
    output.mkdir(parents=True,exist_ok=True)
    (output/'record_audit.json').write_text(json.dumps({'checks':checks,'original_runs':records,'modified_run':summary(MODIFIED)},ensure_ascii=False,indent=2),encoding='utf-8')
    stages=stage_replay()
    (output/'stage_replay.json').write_text(json.dumps(stages,ensure_ascii=False,indent=2),encoding='utf-8')
    for row in records:print(json.dumps({k:v for k,v in row.items() if k not in ('relations','issues')},ensure_ascii=False))
    for key,passed in checks.items():print(('PASS' if passed else 'FAIL')+': '+key)
    print('Saved: '+str(output/'record_audit.json'))
    print('Reproduced empty tree through actual infer_assembly: '+str(stages['empty_tree_real_loop_replay']['nodes']))
    print('Identical structured inputs give stable rule results: PASS')
    print('Shared semantic tags no longer create false dimension conflicts: PASS')
    print('Saved: '+str(output/'stage_replay.json'))
    if not all(checks.values()):sys.exit(1)


if __name__=='__main__':main()
