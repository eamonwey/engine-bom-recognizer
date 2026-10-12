"""Create known-answer development fixtures and optionally test the real VLM.

No expected defects or fixture observations are supplied to the provider. The
test is developmental, not an independent engineering accuracy benchmark.
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine_bom.engineering_checks import inspection_config
from engine_bom.hybrid_inspection import inspect
from engine_bom.providers import build_provider
from engine_bom.titleblock import extract_titleblock, extract_dims_and_balloons
from engine_bom.agent_loop import AgentLoop, validate_bom_response
from engine_bom.prompts import get_prompt_builder
from engine_bom.webapp import load_web_config
from engine_bom.corrections import sha256


def fixture(path, bad):
    image=Image.new('RGB',(2000,1600),'white')
    draw=ImageDraw.Draw(image)
    regular='C:/Windows/Fonts/msyh.ttc'
    font=ImageFont.truetype(regular,28)
    small=ImageFont.truetype(regular,23)
    heading=ImageFont.truetype(regular,35)
    draw.rectangle((20,20,1980,1580),outline='black',width=4)
    draw.text((45,35),'专项规则开发测试图 / 非生产图纸',font=heading,fill='black')
    draw.text((45,88),'独立零件分区；各区P编号不同。尺寸单位 mm。图示仅用于功能验证。',font=font,fill='black')
    panels=[(40,145,970,525),(1010,145,1960,525),(40,550,970,980),(1010,550,1960,980)]
    for box in panels: draw.rectangle(box,outline='black',width=2)
    draw.text((65,165),'P001 孔轴配合',font=heading,fill='black')
    draw.text((65,220),'孔：Φ20 +0.02/0',font=font,fill='black')
    draw.text((65,265),'轴：Φ20 -0.01/-0.03',font=font,fill='black')
    draw.text((65,310),'设计明确要求：'+('过盈配合' if bad else '间隙配合'),font=font,fill='black')
    draw.rectangle((140,390,450,460),outline='black',width=3)
    draw.rectangle((170,410,420,440),outline='black',width=3)
    draw.line((100,425,500,425),fill='black',width=1)
    draw.text((1030,165),'P002 平板 / 形位公差',font=heading,fill='black')
    draw.rectangle((1100,365,1750,440),outline='black',width=3)
    draw.line((1750,395,1820,395,1820,270,1550,270),fill='black',width=2)
    draw.rectangle((1210,240,1550,300),outline='black',width=3)
    draw.line((1320,240,1320,300),fill='black',width=2)
    draw.line((1450,240,1450,300),fill='black',width=2)
    draw.text((1220,250),'垂直度',font=small,fill='black')
    draw.text((1340,250),'0.02',font=font,fill='black')
    draw.text((1470,250),'' if bad else 'A',font=font,fill='black')
    draw.polygon([(1150,440),(1140,458),(1160,458)],fill='black')
    draw.line((1150,458,1150,475),fill='black',width=2)
    draw.rectangle((1125,475,1175,515),outline='black',width=2)
    draw.text((1136,475),'A',font=font,fill='black')
    draw.text((65,575),'P003 同一通孔的对应视图',font=heading,fill='black')
    for x,label,value in [(120,'主视图','Φ20'),(545,'局部放大视图','Φ21' if bad else 'Φ20')]:
        draw.rectangle((x,660,x+280,860),outline='black',width=3)
        draw.ellipse((x+95,710,x+185,800),outline='black',width=3)
        draw.line((x+140,675,x+140,840),fill='black',width=1)
        draw.text((x,870),label,font=font,fill='black')
        draw.text((x+60,620),value,font=font,fill='black')
        draw.text((x,920),'孔标识：HOLE-A',font=small,fill='black')
    draw.text((1030,575),'P004 紧固件与技术要求',font=heading,fill='black')
    draw.text((1030,635),'1. 热处理：'+('待定' if bad else '淬火后回火'),font=font,fill='black')
    draw.text((1030,685),'2. 硬度 HRC '+('60～55' if bad else '55～60'),font=font,fill='black')
    draw.text((1030,735),'3. 表面粗糙度 Ra 1.6',font=font,fill='black')
    draw.text((1030,795),'标准引用：GB/T 70.1-'+('2000' if bad else '2008'),font=font,fill='black')
    draw.text((1030,845),'名称：内六角圆柱头螺钉；规格 M6×16',font=font,fill='black')
    draw.text((65,1030),'明细栏（仅P004的标准件明细，其他分区为独立测试零件）',font=font,fill='black')
    draw.rectangle((65,1090,1940,1250),outline='black',width=2)
    cols=[65,155,655,1230,1610,1790,1940]
    for x in cols: draw.line((x,1090,x,1250),fill='black',width=2)
    draw.line((65,1160,1940,1160),fill='black',width=2)
    headers=['序号','标准号','名称','规格','数量','材料']
    vals=['1','GB/T 70.1-'+('2000' if bad else '2008'),'内六角圆柱头螺钉','M6×16','1','钢']
    for i,(header,val) in enumerate(zip(headers,vals)):
        draw.text((cols[i]+10,1108),header,font=font,fill='black')
        draw.text((cols[i]+10,1185),val,font=font,fill='black')
    draw.rectangle((65,1300,1940,1555),outline='black',width=2)
    lines=['图名：专项检查测试板', '图号：TEST-E-'+('BAD' if bad else 'CLEAN'),
           '设计：测试人员     校核：测试人员     日期：2026.10.11',
           '比例：'+('1:0' if bad else '1:2')+'     单位：mm     版本：A',
           '注：图面简化示意，比例字段用于规则测试，不能据此测量图形。']
    for i,line in enumerate(lines):draw.text((85,1310+i*45),line,font=font if i<4 else small,fill='black')
    image.save(path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cloud',action='store_true')
    args=parser.parse_args()
    directory=ROOT/'data'/'acceptance'/'engineering_checks_20261011'
    directory.mkdir(parents=True,exist_ok=True)
    for bad,name in [(False,'E01_clean'),(True,'E02_defects')]:
        fixture(directory/(name+'.png'),bad)
    expected={'E01_clean':[], 'E02_defects':['ERR-03','ERR-04','ERR-05','ERR-07','ERR-09','ERR-10']}
    expected_rules={'E01_clean':[], 'E02_defects':['fit-interval','gdt-datum','view-equivalent-value','standard-lifecycle','requirement-placeholder','requirement-range','scale-positive']}
    (directory/'expected.json').write_text(json.dumps({'provenance':'程序设计答案，开发用合成样例，未经过独立工程师认证',
        'expected_codes':expected,'expected_rules':expected_rules,'limits':'只评价六项明确植入缺陷；不把未报告等同全图合规。'},ensure_ascii=False,indent=2),encoding='utf-8')
    if not args.cloud:
        print('Created fixtures: '+str(directory));return
    cfg=load_web_config()
    cfg['provider']['openai_compat'].update(timeout=120,retries=0,max_tokens=10000)
    cfg['assembly']={'enabled':False}
    provider=build_provider(cfg['provider'])
    run=directory/('results_'+time.strftime('%Y%m%d_%H%M%S'))
    run.mkdir()
    (run/'inputs').mkdir()
    for name in ('E01_clean.png','E02_defects.png','expected.json'):
        shutil.copyfile(directory/name,run/'inputs'/name)
    records=[]
    for name in expected:
        started=time.monotonic()
        path=run/'inputs'/(name+'.png')
        image=Image.open(path).convert('RGB')
        try:
            print(name+': title extraction',flush=True)
            title=extract_titleblock(provider,[image])['fields']
            print(name+': dimension extraction',flush=True)
            extraction=extract_dims_and_balloons(provider,[image])
            print(name+': BOM extraction',flush=True)
            outcome=AgentLoop(provider,2).run([image],get_prompt_builder('v4')(mode='per_page',page_no=1,total_pages=1,knowledge_snippets=[]),validate_bom_response)
            components=[c.to_dict() for c in outcome.value] if outcome.status=='validated' else []
            dims=extraction['dimensions']
            print(name+': hybrid inspection',flush=True)
            result=inspect(provider,[image],title,components,dims,extraction['balloons'],inspection_config(cfg,str(path),title))
            actual=sorted({r['err_id'] for r in result['issues'] if r['err_id'] in ('ERR-03','ERR-04','ERR-05','ERR-07','ERR-09','ERR-10')})
            record={'case':name,'expected':expected[name],'actual':actual,'missing':sorted(set(expected[name])-set(actual)),
                'extra':sorted(set(actual)-set(expected[name])),'source_sha256':sha256(str(path)),
                'model':provider.model,'seconds':round(time.monotonic()-started,2),'visual_status':result['visual_status']}
            actual_rules={r.get('rule_id') for r in result['issues']}
            record['missing_rules']=sorted(set(expected_rules[name])-actual_rules)
            record['passed']=not record['missing'] and not record['extra'] and not record['missing_rules'] and result['visual_status']=='validated'
            (run/(name+'.json')).write_text(json.dumps({'summary':record,'title':title,'dimensions':dims,'components':components,'inspection':result},ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as exc:
            record={'case':name,'passed':False,'error':str(exc),'model':getattr(provider,'model','unknown')}
            (run/(name+'.failure.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        records.append(record)
        print(json.dumps(record,ensure_ascii=False),flush=True)
        (run/'report.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Results: '+str(run))
    if not all(r['passed'] for r in records):sys.exit(1)


if __name__=='__main__':main()
