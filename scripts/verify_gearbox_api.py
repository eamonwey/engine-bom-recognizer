"""Fresh-server integration check using explicit mock data, no cloud calls."""
import argparse,csv,io,json,re,time,urllib.request
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'data/acceptance/gearbox_fix_20261011'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8792)
    args=parser.parse_args()
    base='http://127.0.0.1:'+str(args.port);opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    html=opener.open(base+'/',timeout=5).read().decode('utf8')
    initial_model=json.load(opener.open(base+'/api/status',timeout=5)).get('model')
    token=re.search(r'<meta name="api-token" content="([^"]+)"',html).group(1)
    png=io.BytesIO();Image.new('RGB',(120,80),'white').save(png,format='PNG')
    boundary='GearboxFixRegressionBoundary'
    prefix=('--'+boundary+'\r\nContent-Disposition: form-data; name="options"\r\n\r\n'+json.dumps({'provider':'mock'})+
            '\r\n--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="gearbox_fix_mock_regression.png"\r\nContent-Type: image/png\r\n\r\n').encode('utf8')
    data=prefix+png.getvalue()+('\r\n--'+boundary+'--\r\n').encode('ascii')
    request=urllib.request.Request(base+'/api/jobs/bom',data=data,headers={
        'Content-Type':'multipart/form-data; boundary='+boundary,'X-API-Token':token},method='POST')
    job_id=json.load(opener.open(request,timeout=5))['job_id']
    result=None;started=time.monotonic()
    while time.monotonic()-started<30:
        job=json.load(opener.open(base+'/api/jobs/'+job_id,timeout=5))
        if job['status']=='done':result=job['result'];break
        if job['status']=='failed':raise AssertionError('Mock job failed: '+str(job.get('error')))
        time.sleep(.25)
    assert result is not None
    checks={'job_complete':True,'explicit_mock_provider':result['model_info']['provider']=='mock',
            'run_consistency_saved':isinstance(result.get('run_consistency'),dict),'source_hash_saved':len(result.get('source_sha256',''))==64}
    exported=json.load(opener.open(base+'/api/export/bom/'+job_id+'?fmt=json',timeout=5))
    checks['json_export_keeps_bom']=bool(exported.get('components')) and exported['components']==result['bom']['components']
    csv_bytes=opener.open(base+'/api/export/bom/'+job_id+'?fmt=csv',timeout=5).read()
    rows=list(csv.reader(io.StringIO(csv_bytes.decode('utf-8-sig'))))
    checks['csv_export_available']=len(rows)==len(result['bom']['components'])+1 and '图号/件号' in rows[0] and '置信度' not in rows[0]
    checks['source_preview_available']=opener.open(base+'/api/pages/'+job_id+'?page=1',timeout=5).headers.get_content_type().startswith('image/')
    status=json.load(opener.open(base+'/api/status',timeout=5))
    checks['global_qwen_configuration_not_overwritten_by_mock_job']=status.get('model')==initial_model
    report={'job_id':job_id,'checks':checks,'note':'Explicit mock integration only; no image/BOM accuracy claim.'}
    (OUTPUT/'api_regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False));assert all(checks.values())

if __name__=='__main__':main()
