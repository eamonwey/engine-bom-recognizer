"""Known-answer dimensional development drawings; optional real vision test.

Expected answers are used ONLY after inference. This is not expert-certified GT.
Inputs and failed results are preserved with SHA256; no best-run accuracy claim.
"""
import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine_bom.corrections import sha256
from engine_bom.dimension_chains import inspect_chains
from engine_bom.hybrid_inspection import inspect
from engine_bom.ingestion import load_document
from engine_bom.providers import build_provider
from engine_bom.titleblock import extract_dims_and_balloons
from engine_bom.webapp import load_web_config

DIRECTORY = ROOT/'data'/'acceptance'/'tolerance_chains_20261011'
CASES = {
    'TC01_within':dict(requirement='10±0.3',expected='within_limits',minimum='9.8',maximum='10.2'),
    'TC02_risk':dict(requirement='10±0.1',expected='may_exceed_limits',minimum='9.8',maximum='10.2'),
    'TC03_outside':dict(requirement='8±0.1',expected='outside_limits',minimum='9.8',maximum='10.2'),
    'TC04_boundary':dict(requirement='10±0.2',expected='within_limits',minimum='9.8',maximum='10.2',boundary=True),
    'TC05_missing_tolerance':dict(requirement='10±0.3',component='90',expected='uncertain'),
    'TC06_vertical':dict(requirement='10±0.3',expected='within_limits',minimum='9.8',maximum='10.2',vertical=True),
    'TC07_unconnected':dict(requirement='10±0.3',expected='uncertain',unconnected=True),
    'TC08_asymmetric':dict(requirement='10±0.3',component='90 +0.15/-0.05',housing='100 +0.2/-0.1',
        expected='within_limits',minimum='9.75',maximum='10.25'),
}


def drawing(path, spec):
    image=Image.new('RGB',(1700,1250),'white')
    d=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',28)
    small=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',22)
    heading=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',34)
    d.rectangle((20,20,1680,1230),outline='black',width=3)
    d.text((55,40),'装配间隙公差分析测试图 · 非生产图纸',font=heading,fill='black')
    d.text((55,95),'图示为一维刚性装配，尺寸单位 mm；字母为界面标识，不是形位公差基准。',font=small,fill='black')
    d.text((55,135),'所有功能要求及尺寸以文字标注为准；不得从图形像素测量尺寸。',font=small,fill='black')
    x0,x1,x2=220,1300,1420
    d.line((x0-30,530,x2+30,530),fill='black',width=1)
    d.line((x0,440,x2,440,x2,620,x0,620,x0,440),fill='black',width=4)
    d.rectangle((x0,480,x1,580),outline='black',width=3)
    # The cavity and insert share the left assembly stop A.
    for x in range(x0+5,x1,23):d.line((x,580,min(x+30,x1),550),fill='black',width=1)
    d.text((550,494),'内件',font=font,fill='black')
    d.text((x0-25,400),'A',font=heading,fill='black')
    d.text((x1-25,400),'B',font=heading,fill='black')
    d.text((x2-15,400),'C',font=heading,fill='black')
    def dim(a,b,y,label,origin_y):
        d.line((a,origin_y,a,y+16),fill='black',width=1)
        d.line((b,origin_y,b,y+16),fill='black',width=1)
        d.line((a,y,b,y),fill='black',width=2)
        d.polygon([(a,y),(a+12,y-5),(a+12,y+5)],fill='black')
        d.polygon([(b,y),(b-12,y-5),(b-12,y+5)],fill='black')
        bounds=d.textbbox((0,0),label,font=font)
        width=bounds[2]-bounds[0]
        center=(a+b)//2
        d.rectangle((center-width//2-8,y-42,center+width//2+8,y-4),fill='white')
        d.text((center-width//2,y-42),label,font=font,fill='black')
    dim(x0,x2,310,'L：'+spec.get('housing','100±0.1'),440)
    dim(x0,x1,760,'B：'+spec.get('component','90±0.1'),580)
    if spec.get('unconnected'):
        # A separate feature, NOT the B-C closing gap. Similar arithmetic is
        # deliberately tempting; the tool must not build a chain from values.
        d.rectangle((80,660,205,720),outline='black',width=3)
        dim(80,205,825,'S：'+spec['requirement'],720)
    else:
        dim(x1,x2,670,'S：'+spec['requirement'],580)
    if spec.get('vertical'):
        # Rotate the graphical viewport only; labels remain legible when read
        # vertically, and the page/title block stay in the usual orientation.
        viewport=image.crop((55,210,1630,860)).rotate(90,expand=True)
        viewport.thumbnail((650,700))
        d.rectangle((55,210,1630,860),fill='white')
        image.paste(viewport,((1700-viewport.width)//2,185))
        d=ImageDraw.Draw(image)
    lines=[
        '技术要求：',
        '1. 内件左端必须贴合腔体左端止挡A，不进行选择装配或现场调整。',
        ('2. S为独立小件的功能长度，位于腔体之外，与内件/腔体不构成尺寸链。' if spec.get('unconnected') else
         '2. 装配后B界面至C界面的间隙S必须满足 '+spec['requirement']+' mm。'),
        '3. 未注明的组成尺寸公差为未知，不假定一般公差或零公差。',
        '4. 本图仅验证尺寸链读取与计算，不用于生产、工艺或标准合规验收。',
    ]
    for n,line in enumerate(lines):d.text((55,890+n*40),line,font=small,fill='black')
    d.rectangle((55,1110,1630,1210),outline='black',width=2)
    d.text((75,1120),'图名：轴向装配间隙测试    图号：'+path.stem+'    视图：主视图',font=small,fill='black')
    d.text((75,1160),'设计/校核：测试程序    日期：2026.10.11    单位：mm    图形示意比例',font=small,fill='black')
    image.save(path)
    image.save(path.with_suffix('.pdf'),'PDF',resolution=150)


def create_fixtures():
    DIRECTORY.mkdir(parents=True,exist_ok=True)
    for name,spec in CASES.items():drawing(DIRECTORY/(name+'.png'),spec)
    manifest={'provenance':'程序设计的已知答案开发样例；非独立工程师审定真值集',
        'scoring':'先推理，再按原文设计答案评分；禁止向模型提供expected或计算结果',
        'cases':CASES,'files':{p.name:sha256(str(p)) for p in sorted(DIRECTORY.glob('TC*.*')) if p.stem in CASES and p.suffix in ('.png','.pdf')}}
    (DIRECTORY/'expected.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')


def score(report,spec):
    calculations=report.get('tolerance_chains') or []
    issues=[i for i in report.get('issues',[]) if i.get('rule_id')=='tolerance-chain-worst-case']
    if spec['expected']=='uncertain':
        return not calculations and not issues and report.get('tolerance_status')=='uncertain'
    if report.get('tolerance_status')!='checked' or len(calculations)!=1:
        return False
    calc=calculations[0]
    correct=(calc['conformance']==spec['expected'] and Decimal(calc['minimum_mm'])==Decimal(spec['minimum'])
        and Decimal(calc['maximum_mm'])==Decimal(spec['maximum']) and calc['at_boundary']==spec.get('boundary',False))
    return correct and len(issues)==(0 if spec['expected']=='within_limits' else 1)


class CapturingProvider:
    def __init__(self,provider):
        self.provider,self.name,self.calls=provider,provider.name,[]
    def analyze(self,images,prompt):
        result=self.provider.analyze(images,prompt)
        self.calls.append({'task':prompt.splitlines()[0],'image_count':len(images),'raw_text':result.raw_text,
            'latency_s':result.latency_s,'model':result.model})
        return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--create',action='store_true')
    parser.add_argument('--cloud',action='store_true')
    parser.add_argument('--hybrid',action='store_true')
    parser.add_argument('--pdf',action='store_true')
    parser.add_argument('--cases',nargs='+',choices=list(CASES))
    args=parser.parse_args()
    if args.create or not (DIRECTORY/'expected.json').exists():create_fixtures()
    if not args.cloud:
        print('Fixtures: '+str(DIRECTORY));return
    config=load_web_config()
    config['provider']['openai_compat'].update(timeout=120,retries=0,max_tokens=12000)
    base=build_provider(config['provider'])
    if base.name=='mock':raise RuntimeError('请在系统设置中选择可用视觉API，不能用mock进行云端验收')
    timestamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S_%f')
    run=DIRECTORY/('results_'+timestamp)
    (run/'inputs').mkdir(parents=True)
    expected=json.loads((DIRECTORY/'expected.json').read_text(encoding='utf-8'))
    shutil.copyfile(DIRECTORY/'expected.json',run/'inputs'/'expected.json')
    records=[]
    for name in args.cases or CASES:
        ext='.pdf' if args.pdf else '.png'
        source=DIRECTORY/(name+ext)
        if sha256(str(source))!=expected['files'][source.name]:raise RuntimeError('输入文件哈希不符，请重新创建并审核设计答案')
        path=run/'inputs'/source.name
        shutil.copyfile(source,path)
        provider=CapturingProvider(base)
        started=time.monotonic()
        payload={}
        try:
            images=[p.image for p in load_document(str(path),config['ingestion'])]
            print(name+': reading dimensions',flush=True)
            dims=extract_dims_and_balloons(provider,images)
            print(name+': checking tolerance paths',flush=True)
            if args.hybrid:
                inspection=inspect(provider,images,{},[],dims['dimensions'],[],config.get('inspection'))
                report=inspection.get('dimension_chains',{})
                payload['hybrid_inspection']=inspection
            else:
                report=inspect_chains(provider,images,dims['dimensions'])
            payload.update(dimensions=dims,dimension_chains=report,calls=provider.calls)
            # No answer enters either extraction prompt above.
            passed=score(report,expected['cases'][name])
            record={'case':name,'format':ext,'passed':passed,'model':base.model,'source_sha256':sha256(str(path)),
                'seconds':round(time.monotonic()-started,2),'status':report.get('tolerance_status'),
                'calculated_ranges':[{k:c[k] for k in ('minimum_mm','maximum_mm','conformance')} for c in report.get('tolerance_chains',[])],
                'expected':expected['cases'][name]}
        except Exception as exc:
            record={'case':name,'passed':False,'model':getattr(base,'model','unknown'),'error':str(exc),
                'seconds':round(time.monotonic()-started,2),'source_sha256':sha256(str(path))}
            payload['calls']=provider.calls
        payload['summary']=record
        (run/(name+'.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        records.append(record)
        (run/'report.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(record,ensure_ascii=False),flush=True)
    print('Report: '+str(run))
    if not all(r['passed'] for r in records):sys.exit(1)


if __name__=='__main__':main()
