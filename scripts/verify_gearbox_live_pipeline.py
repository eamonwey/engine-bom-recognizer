"""Fresh real HTTP jobs; reference fields read from the native source table.

No stored prediction is used as a BOM or assembly ground truth. The selected
table cells were visually transcribed for this regression, not certified by
an independent engineer. The full assembly truth is still unverified.
"""
import argparse,json,re,time,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/acceptance/gearbox_fix_20261011'
SOURCES={'original':'20261011203652-87494f','modified':'20261011221848-19b051'}
QUANTITIES={i:1 for i in range(1,33)}
QUANTITIES.update({7:4,8:5,9:5,10:2,13:2,15:2,17:2,19:2,27:2,32:4})
NAMES={4:'输出轴透盖',5:'油封28×47×7',11:'输入轴端盖',12:'齿轮轴',20:'输入轴透盖'}


def summarize(result,label):
    components=result['bom']['components'];by_item={c.get('item_no'):c for c in components}
    graph=result['bom'].get('assembly') or {};indexed={n['id']:n for n in graph.get('nodes',[])}
    seals=[n for n in indexed.values() if components[n['component_index']].get('item_no')==21]
    normalize=lambda text:re.sub(r'\s+','',str(text or '')).replace('x','×').replace('X','×')
    differences=[dict(item_no=i,expected=q,actual=by_item.get(i,{}).get('quantity'))
                 for i,q in QUANTITIES.items() if by_item.get(i,{}).get('quantity')!=q]
    names=[dict(item_no=i,expected=n,actual=by_item.get(i,{}).get('name_zh'))
           for i,n in NAMES.items() if normalize(by_item.get(i,{}).get('name_zh'))!=normalize(n)]
    checks={'real_qwen_provider':result.get('model_info',{}).get('provider')=='openai_compat',
            'printed_32_rows_and_item_numbers':len(components)==32 and set(by_item)==set(range(1,33)),
            'each_printed_quantity_matches_source':not differences,'selected_names_match_source':not names,
            'installation_graph_present':bool(indexed),
            'oil_seal_21_direct_parent_20':bool(seals) and all(
                n.get('parent_id') in indexed and components[indexed[n['parent_id']]['component_index']].get('item_no')==20 for n in seals)}
    links=(result.get('inspection') or {}).get('dimension_links') or {}
    if label=='modified':
        checks['modified_60_62_conflict_located']=any(
            {i.get('calculation',{}).get('left_nominal_mm'),i.get('calculation',{}).get('right_nominal_mm')}=={'60','62'}
            and any(d.get('bbox') and .18<(d['bbox'][0]+d['bbox'][2])/2<.35 and .83<(d['bbox'][1]+d['bbox'][3])/2<.93
                    and '60' in d.get('value','') for d in i.get('linked_dimensions',[])) for i in links.get('issues',[]))
    else:
        checks['original_no_definite_dimension_errors']=not any(i.get('err_id')=='ERR-01' for i in result.get('issues',[]))
    return {'checks':checks,'quantity_differences':differences,'selected_name_differences':names,
            'model':result.get('model_info',{}).get('model'),'nodes':len(indexed),
            'unverified_nodes':len(graph.get('unverified_nodes',[])),
            'inspection_stages':result.get('inspection',{}).get('stages'),
            'issue_types':[i.get('err_id') for i in result.get('issues',[])],
            'dimension_link_status':links.get('status'),
            'note':'Selected printed fields, not a full independently certified assembly ground truth.'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8793)
    parser.add_argument('--prefix',default='qwen37plus_full_1');args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.prefix):parser.error('simple prefix required')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));base='http://127.0.0.1:'+str(args.port)
    html=opener.open(base+'/',timeout=5).read().decode('utf8');token=re.search(r'<meta name="api-token" content="([^"]+)"',html).group(1)
    pending={};reports={}
    def save():
        (OUT/(args.prefix+'_summary.json')).write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    for label,source_id in SOURCES.items():
        source=next((ROOT/'data/web_jobs'/source_id/'file').glob('*.png'));boundary='GearboxRealValidationBoundary'
        fields=('--'+boundary+'\r\nContent-Disposition: form-data; name="options"\r\n\r\n'+json.dumps({'provider':'openai_compat'})+
                '\r\n--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+args.prefix+'_'+label+'.png"\r\nContent-Type: image/png\r\n\r\n').encode('utf8')
        req=urllib.request.Request(base+'/api/jobs/bom',data=fields+source.read_bytes()+('\r\n--'+boundary+'--\r\n').encode(),
            headers={'Content-Type':'multipart/form-data; boundary='+boundary,'X-API-Token':token},method='POST')
        job=json.load(opener.open(req,timeout=10))['job_id'];pending[label]=job
        reports[label]={'job_id':job,'status':'submitted','reference_source_job':source_id};save()
        print(label+' submitted '+job,flush=True)
    started=time.monotonic();last=started
    while pending and time.monotonic()-started<2400:
        for label,job_id in list(pending.items()):
            job=json.load(opener.open(base+'/api/jobs/'+job_id,timeout=10))
            if job['status'] not in ('done','failed'):continue
            reports[label]['status']=job['status']
            if job['status']=='done':
                result=job['result'];reports[label].update(summarize(result,label))
                (OUT/(args.prefix+'_'+label+'_result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            else:reports[label]['job_error']=job.get('error')
            del pending[label];save();print(label+' '+json.dumps(reports[label],ensure_ascii=False),flush=True)
        if time.monotonic()-last>30:
            print('Waiting for real jobs: '+', '.join(pending),flush=True);last=time.monotonic()
        if pending:time.sleep(2)
    if pending:raise TimeoutError('Real jobs still running; submitted IDs saved in summary')
    assert all(r['status']=='done' and all(r['checks'].values()) for r in reports.values()),'Real acceptance incomplete; inspect saved summary'


if __name__=='__main__':main()
