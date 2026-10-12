"""Isolated HTTP acceptance suite. Never loads production API keys or review users."""
import copy, hashlib, io, json, os, re, subprocess, sys, threading, time, unittest, urllib.request, urllib.error, zipfile
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine_bom import webapp as w
from engine_bom.config import DEFAULT_CONFIG, deep_merge
from PIL import Image
import fitz

OUT=ROOT/'data'/'test_runs'/datetime.now().strftime('%Y%m%d_%H%M%S')
OUT.mkdir(parents=True)
cases=[]
def check(name, expected, fn):
    start=time.monotonic()
    try:
        detail=fn()
        cases.append(dict(name=name,expected=expected,status='PASS',actual=str(detail or '符合预期'),seconds=round(time.monotonic()-start,3)))
    except Exception as exc:
        cases.append(dict(name=name,expected=expected,status='FAIL',actual='%s: %s'%(type(exc).__name__,exc),seconds=round(time.monotonic()-start,3)))
    print(cases[-1]['status'],name,flush=True)
    (OUT/'http_results.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
def require(condition,message='不符合预期'):
    if not condition: raise AssertionError(message)

class Results(unittest.TextTestResult):
    def addSuccess(self,test): super().addSuccess(test); unit_cases.append({'name':test.id(),'status':'PASS'})
    def addFailure(self,test,err): super().addFailure(test,err); unit_cases.append({'name':test.id(),'status':'FAIL'})
    def addError(self,test,err): super().addError(test,err); unit_cases.append({'name':test.id(),'status':'ERROR'})
    def addSkip(self,test,reason): super().addSkip(test,reason); unit_cases.append({'name':test.id(),'status':'SKIP','reason':reason})
unit_cases=[]
with (OUT/'unit.log').open('w',encoding='utf-8') as log:
    result=unittest.TextTestRunner(stream=log,resultclass=Results,verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT/'tests')))
(OUT/'unit_results.json').write_text(json.dumps(unit_cases,indent=2),encoding='utf-8')
for script in ['frontend_interactions.cjs','frontend_selection.cjs']:
    def run_js(script=script):
        p=subprocess.run(['node',str(ROOT/'tests'/script)],capture_output=True,text=True)
        require(p.returncode==0,p.stdout+p.stderr); return p.stdout.strip()
    check(script,'交互回归断言全部通过',run_js)
for name in ['app.js','extensions.js','workspace.js']:
    check(name+' syntax','JS语法正确',lambda name=name:require(subprocess.run(['node','--check',str(ROOT/'static'/name)],capture_output=True).returncode==0))

data=OUT/'isolated'; data.mkdir()
for attr,relative in [('DATA_DIR',''),('JOBS_DIR','web_jobs'),('SETTINGS_PATH','settings.json'),('HISTORY_PATH','history.json'),('REVIEWLOG_PATH','reviewlog.json')]:
    setattr(w,attr,str(data/relative))
Path(w.JOBS_DIR).mkdir()
w._jobs={}; w._API_TOKEN='isolated-test-session'
config=copy.deepcopy(DEFAULT_CONFIG)
config['provider']={'name':'mock'}
config['output']={'dir':str(data/'predictions'),'formats':['json','csv']}
config['impact']={'index_path':str(data/'associations.json')}
def isolated_config():
    return deep_merge(copy.deepcopy(config),json.loads(Path(w.SETTINGS_PATH).read_text(encoding='utf-8')) if Path(w.SETTINGS_PATH).exists() else {})
w.load_web_config=isolated_config
users=[{'id':role,'role':role,'token_sha256':hashlib.sha256(('test-'+role).encode()).hexdigest()} for role in ['editor','reviewer','approver']]
(data/'review_users.json').write_text(json.dumps(users),encoding='utf-8')
class Handler(w.Handler):
    def log_message(self,fmt,*args):
        with (OUT/'http.log').open('a',encoding='utf-8') as f:f.write(fmt%args+'\n')
server=w.ThreadingHTTPServer(('127.0.0.1',8790),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
BASE='http://127.0.0.1:8790'
def request(path,body=None,headers=None,code=200):
    h={'X-API-Token':w._API_TOKEN}; h.update(headers or {})
    if isinstance(body,dict): body=json.dumps(body,ensure_ascii=False).encode();h['Content-Type']='application/json'
    try:r=urllib.request.urlopen(urllib.request.Request(BASE+path,data=body,headers=h),timeout=15)
    except urllib.error.HTTPError as e:r=e
    content=r.read(); require(r.code==code,'HTTP %s expected %s: %s'%(r.code,code,content[:200]))
    return content
def get(path): return json.loads(request(path))
def post(path,body,**kw): return json.loads(request(path,body,**kw))
def upload(kind,files,fields=None):
    boundary='isolated-boundary'; body=bytearray()
    for key,value in (fields or {}).items(): body.extend(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode())
    for key,(name,blob) in files.items():
        body.extend(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"; filename="'+name+'"\r\nContent-Type: application/octet-stream\r\n\r\n').encode());body.extend(blob);body.extend(b'\r\n')
    body.extend(('--'+boundary+'--\r\n').encode())
    job=json.loads(request('/api/jobs/'+kind,bytes(body),{'Content-Type':'multipart/form-data; boundary='+boundary}))['job_id']
    for _ in range(150):
        state=get('/api/jobs/'+job)
        if state['status']!='running': return job,state
        time.sleep(.1)
    raise AssertionError('任务15秒内未结束')
def done(pair):
    job,state=pair; require(state['status']=='done',state.get('error'));return job,state['result']
fixture=data/'fixtures'; fixture.mkdir()
png=(ROOT/'data/acceptance/axis_support_01/TEST-100-A.png').read_bytes()
(fixture/'drawing.png').write_bytes(png)
pdf=fitz.open();p=pdf.new_page();p.insert_text((50,70),'Material TC4; speed 10000 rpm.');pdfbytes=pdf.tobytes();pdf.close()
(fixture/'document.pdf').write_bytes(pdfbytes)
scan=fitz.open();p=scan.new_page();p.insert_image(p.rect,stream=png);scanbytes=scan.tobytes();scan.close()
(fixture/'scan.pdf').write_bytes(scanbytes)
before='材料为 TC4\n转速范围 10000 r/min\n需要去毛刺\n'.encode()
after='材料为 TC11\n转速范围 12000 r/min\n需要去毛刺\n新增检验要求\n'.encode()
(fixture/'before.txt').write_bytes(before);(fixture/'after.txt').write_bytes(after)
with zipfile.ZipFile(str(fixture/'document.docx'),'w') as doc:
    doc.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    doc.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>材料 TC4</w:t></w:r></w:p><w:p><w:r><w:t>转速 10000 r/min</w:t></w:r></w:p></w:body></w:document>')
check('首页与资源版本','HTTP200，模板令牌替换，脚本版本正确',lambda:require(b'__ENGINE_BOM_API_TOKEN__' not in request('/') and b'20260923-3' in request('/')))
check('无效请求令牌','HTTP403',lambda:request('/api/config',{}, {'X-API-Token':'invalid'},403))
check('静态目录穿越','HTTP403',lambda:request('/static/../../config.yaml',code=403))
check('状态接口密钥保护','没有明文API Key',lambda:require('api_key' not in get('/api/status')))
cache={}
for name,blob in [('png',png),('pdf',pdfbytes),('scan.pdf',scanbytes)]:
    def bom(name=name,blob=blob):
        jid,r=done(upload('bom',{'file':('drawing.'+name,blob)},{'options':'{"provider":"mock"}'}));cache[name]=(jid,r)
        require(len(r['bom']['components'])==11,'Mock应返回11行固定示例'); require(r['inspection']['visual_status']=='not_run');return '11行固定Mock示例；不评价原图准确率'
    check('BOM上传 '+name,'解码、管线、异步任务正常',bom)
jid,r=cache['png']
check('图像预览','PNG且页码越界400',lambda:(require(request('/api/pages/'+jid+'?page=1').startswith(b'\x89PNG')),request('/api/pages/'+jid+'?page=9',code=400)))
def export(fmt,profile=''):
    content=request('/api/export/bom/'+jid+'?fmt='+fmt+profile)
    if fmt=='xlsx':
        import openpyxl
        book=openpyxl.load_workbook(io.BytesIO(content)); require(book.active.max_row==12)
    elif fmt=='json':require(len(json.loads(content).get('components',json.loads(content).get('rows',[])))==11)
    else:require(len(content.decode('utf-8-sig').splitlines())==12)
    return '11条数据；格式可解析'
for fmt in ['json','csv','xlsx']:check('BOM导出 '+fmt,'11行且文件可读取',lambda fmt=fmt:export(fmt))
def save_assembly():
    tree={'nodes':[{'id':'n1','parent_id':None,'component_index':0,'source_page':1,'quantity_per_parent':None,'evidence':'测试总成'}]}
    post('/api/assembly/save',{'job_id':jid,'reviewer':'test','assembly':tree})
    require(get('/api/jobs/'+jid)['result']['bom']['assembly']['status']=='reviewed_partial')
check('装配人工确认与持久化','部分确认状态且持久化',save_assembly)
def save_bom():
    components=copy.deepcopy(r['bom']['components']);components[0]['quantity']=7
    post('/api/bom/save',{'job_id':jid,'document_id':'test-edit','components':components})
    result=get('/api/jobs/'+jid)['result']['bom']; require(result['components'][0]['quantity']==7);require(result['assembly']['inference_status']=='invalidated_by_bom_edit')
check('BOM修改后旧层级失效','数量更新、旧层级清除',save_bom)
check('企业配置非法字段','HTTP400',lambda:post('/api/enterprise/profile',{'export_fields':{'invented':'未知列'}},code=400))
check('企业配置导入','HTTP200',lambda:post('/api/enterprise/profile',{'export_fields':{'part_number':'物料编码','quantity':'用量'}}))
for fmt in ['json','csv','xlsx']:check('企业格式导出 '+fmt,'11行且文件可读取',lambda fmt=fmt:export(fmt,'&profile=enterprise'))
for name,blob in [('txt',before),('md',before),('pdf',pdfbytes),('docx',(fixture/'document.docx').read_bytes()),('png',png),('scan.pdf',scanbytes)]:
    def doc_test(name=name,blob=blob):
        ident,res=done(upload('doc',{'file':('doc.'+name,blob)},{'provider':'mock'}));cache['doc-'+name]=(ident,res)
        require(all(key in res['extraction'] for key in ['tech_params','materials','process_requirements','inspection']),str(res['extraction'].keys()))
    check('文档提取 '+name,'四类结构化要素（Mock）',doc_test)
dj,dr=cache['doc-txt']
for fmt in ['json','xlsx']:
    def doc_export(fmt=fmt):
        content=request('/api/export/doc/'+dj+'?fmt='+fmt)
        if fmt=='json':require(json.loads(content)==dr['extraction'])
        else:require(zipfile.is_zipfile(io.BytesIO(content)))
    check('文档导出 '+fmt,'与当前任务一致，可读取',doc_export)
check('文档编辑保存','修改反映到任务结果',lambda:(post('/api/doc/save',{'job_id':dj,'file_name':'test','extraction':{'tech_params':[{'name':'edited','value':'42'}]}}),require(get('/api/jobs/'+dj)['result']['extraction']['tech_params'][0]['value']=='42')))
index={'objects':[{'id':'spec','name':'材料规范','kind':'document','keywords':['TC4'],'depends_on':[]},{'id':'bom','name':'关联BOM','kind':'bom','depends_on':['spec']},{'id':'process','name':'加工工序','kind':'process','depends_on':['bom']},{'id':'inspection','name':'检验项','kind':'inspection','depends_on':['process']}]}
check('关联索引导入','四个对象',lambda:require(post('/api/impact/index',index)['objects']==4))
check('错误关联引用','HTTP400',lambda:post('/api/impact/index',{'objects':[{'id':'bad','kind':'bom','depends_on':['none']}]},code=400))
def compare():
    ident,res=done(upload('compare',{'before':('same.txt',before),'after':('same.txt',after)}));cache['compare']=(ident,res)
    require(res['summary']['total']>=2);require({o['id'] for o in res['impact']['objects']}=={'spec','bom','process','inspection'})
    require(max(len(reason['dependency_path']) for o in res['impact']['objects'] for reason in o['reasons'])==4)
    return '同名文件保持独立；变更传播到4个对象'
check('同名版本对比与四级影响传播','检出材料/转速变化与新增项，传播依赖',compare)
check('相同版本对比','零变更',lambda:require(done(upload('compare',{'before':('a.txt',before),'after':('b.txt',before)}))[1]['summary']['total']==0))
check('ECN下载','包含影响项且写入历史',lambda:require('检验项' in request('/api/compare/'+cache['compare'][0]+'/ecn.md').decode()))
check('历史与复核日志','包含此前对比、保存记录',lambda:require(len(get('/api/history')['records'])>=2 and len(get('/api/reviewlog')['records'])>=2))
def correction(ext,blob):
    patch={'reviewer':'automated-test','patches':[{'approved':True,'source_page':1,'bbox':[.1,.1,.3,.2],'old_text':'test','new_text':'42','expected_source_sha256':hashlib.sha256(blob).hexdigest()}]}
    ident,res=done(upload('correct',{'file':('test.'+ext,blob)},{'reviewed':json.dumps(patch)}))
    require(res['source_sha256']!=res['output_sha256']);require(Path(res['source']).read_bytes()==blob)
    require(request('/api/corrections/'+ident).startswith(b'%PDF' if ext=='pdf' else b'\x89PNG'));require(Path(res['output']+'.audit.json').exists())
for ext,blob in [('png',png),('pdf',pdfbytes)]:check('文字修订 '+ext,'副本变化、原图不变、审计与下载存在',lambda ext=ext,blob=blob:correction(ext,blob))
def bad_correction():
    ident,state=upload('correct',{'file':('bad.png',png)},{'reviewed':json.dumps({'reviewer':'test','patches':[{'approved':True,'source_page':1,'bbox':[.1,.1,.3,.2],'new_text':'42','expected_source_sha256':'wrong'}]})})
    require(state['status']=='failed');return state['error']
check('原图哈希不匹配拒绝修订','任务失败，不生成有效修订',bad_correction)
review_payload={'components':[{'part_number':'T','quantity':1}]}
def transition(action,role,revision,payload=review_payload,code=200):
    return post('/api/reviews/transition',{'document_id':'test-workflow','action':action,'revision':revision,'payload':payload},headers={'X-Review-Token':'test-'+role},code=code)
check('编制提交','submitted/rev1',lambda:require(transition('submit','editor',0)['state']=='submitted'))
check('越权批准拦截','HTTP403',lambda:transition('approve','editor',1,code=403))
check('篡改快照复核拦截','HTTP400',lambda:transition('review','reviewer',1,{'changed':True},400))
check('独立复核','reviewed/rev2',lambda:require(transition('review','reviewer',1)['state']=='reviewed'))
check('独立批准','approved/rev3且三条审计',lambda:require(len(transition('approve','approver',2)['audit'])==3))
check('过期版本冲突','HTTP400',lambda:transition('submit','editor',0,code=400))
check('退回流程','重新提交后可退回',lambda:(transition('submit','editor',3),require(transition('reject','reviewer',4)['state']=='rejected')))
check('模型配置保存','Mock配置生效',lambda:require(post('/api/config',{'provider':'mock'})['status']['provider']=='mock'))
check('模型连接测试Mock','固定示例连通，不代表真实模型',lambda:require(post('/api/test-connection',{'provider':'mock'}).get('ok') is True))
def secret_settings():
    post('/api/config',{'openai_compat':{'api_key':'test-placeholder'}})
    require(get('/api/status')['api_key_set']); require(b'test-placeholder' not in request('/api/status'))
    post('/api/config',{'openai_compat':{'api_key':''}});require(get('/api/status')['api_key_set'])
    post('/api/config',{'clear_api_key':True});require(not get('/api/status')['api_key_set'])
check('密钥留空保留、清除与脱敏','仅测试占位值，不接触生产密钥',secret_settings)
check('任务不存在','HTTP404',lambda:request('/api/jobs/does-not-exist',code=404))
def bad_upload():
    _,state=upload('bom',{'file':('corrupt.png',b'not an image')},{'options':'{"provider":"mock"}'})
    require(state['status']=='failed');return state['error']
check('损坏图片','任务明确失败',bad_upload)
check('缺失上传文件','HTTP400',lambda:request('/api/jobs/bom',b'--empty--\r\n',{'Content-Type':'multipart/form-data; boundary=empty'},400))
check('输入失败无孤立运行任务','任务均为终态',lambda:require(all(j['status']!='running' for j in get('/api/jobs')['jobs'])))
(OUT/'summary.json').write_text(json.dumps({'unit_total':result.testsRun,'unit_failed':len(result.failures)+len(result.errors),'cases':len(cases),'failed':[c['name'] for c in cases if c['status']=='FAIL'],'server':BASE,'fixtures':str(fixture)},ensure_ascii=False,indent=2),encoding='utf-8')
print('REPORT_DIR='+str(OUT),flush=True)
if '--serve' in sys.argv:
    print('Isolated browser test service ready on '+BASE,flush=True)
    threading.Event().wait()
else: server.shutdown()
