"""Additional checks against the isolated service created by comprehensive_test.py."""
import io, json, sys, time, urllib.request, urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import fitz
from PIL import Image
out=Path(sys.argv[1]); base='http://127.0.0.1:8790'; records=[]
def req(path,body=None,ctype=None):
    h={'X-API-Token':'isolated-test-session'}
    if ctype:h['Content-Type']=ctype
    try:r=urllib.request.urlopen(urllib.request.Request(base+path,body,h),timeout=20)
    except urllib.error.HTTPError as e:r=e
    return r.code,r.read()
def upload(kind,blob,name,options='{"provider":"mock"}'):
    boundary='extra-test'
    body=('--'+boundary+'\r\nContent-Disposition: form-data; name="options"\r\n\r\n'+options+'\r\n--'+boundary+'\r\nContent-Disposition: form-data; name="provider"\r\n\r\nmock\r\n--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+name+'"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()+blob+('\r\n--'+boundary+'--\r\n').encode()
    code,data=req('/api/jobs/'+kind,body,'multipart/form-data; boundary='+boundary)
    if code!=200:return code,json.loads(data)
    ident=json.loads(data)['job_id']
    for _ in range(200):
        state=json.loads(req('/api/jobs/'+ident)[1])
        if state['status']!='running':return code,state
        time.sleep(.1)
    return code,state
def check(name,fn):
    try:detail=fn(); records.append({'name':name,'status':'PASS','actual':detail})
    except Exception as e:records.append({'name':name,'status':'FAIL','actual':str(e)})
def done(args):
    code,state=args
    assert code==200 and state['status']=='done',state
    return state['id']
png=(out/'isolated/fixtures/drawing.png').read_bytes()
buf=io.BytesIO();Image.open(io.BytesIO(png)).convert('RGB').save(buf,format='JPEG')
check('JPEG上传与三项预处理',lambda:done(upload('bom',buf.getvalue(),'test.jpg','{"provider":"mock","preprocess":{"deskew":true,"denoise":true,"binarize":true}}')))
pdf=fitz.open(); pdf.new_page().insert_text((40,40),'PAGE ONE');pdf.new_page().insert_text((40,40),'PAGE TWO')
check('两页PDF处理',lambda:done(upload('bom',pdf.tobytes(),'two.pdf')))
check('独立图纸检查接口',lambda:done(upload('inspect',png,'test.png')))
def concurrent():
    with ThreadPoolExecutor(max_workers=3) as pool: ids=list(pool.map(lambda _:done(upload('bom',png,'concurrent.png')),range(3)))
    assert len(set(ids))==3
    return ids
check('三任务并发隔离',concurrent)
def malformed():
    code,state=upload('bom',png,'invalid-options.png','{invalid')
    assert code==400,(code,state)
    jobs=json.loads(req('/api/jobs')[1])['jobs']
    running=[j['id'] for j in jobs if j['status']=='running']
    assert not running,'HTTP400后残留running任务: '+str(running)
check('有效文件但非法options不遗留任务',malformed)
(out/'supplemental_results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(records,ensure_ascii=False,indent=2))
