"""Deterministic assembly test sheets; all expected quantities derive from explicit edges."""
import json, hashlib, zipfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import fitz

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/acceptance/assembly_hierarchy_20260926'
OUT.mkdir(parents=True,exist_ok=True)
FONT='C:/Windows/Fonts/msyh.ttc'
CASES=[
 dict(id='H01',name='轴承支座组件',parts=[('A100','轴承支座组件','组合件','套'),('P101','底座','45','件'),('P102','轴承','GCr15','件'),('B103','六角螺栓M8×20','35','件')],edges=[(0,1,1),(0,2,2),(0,3,4)]),
 dict(id='H02',name='双夹紧单元',parts=[('A200','双夹紧单元','组合件','套'),('S210','夹紧子总成','组合件','套'),('P220','安装板','Q235B','件'),('P211','夹爪','45','件'),('B212','内六角螺钉M6×16','35','件')],edges=[(0,1,2),(0,2,1),(1,3,2),(1,4,3)]),
 dict(id='H03',name='双模块机架',parts=[('A300','双模块机架','组合件','套'),('S310','驱动子总成','组合件','套'),('S320','导向子总成','组合件','套'),('P311','驱动座','45','件'),('P321','导向套','青铜','件'),('B330','六角螺栓M6×20','35','件')],edges=[(0,1,2),(0,2,1),(1,3,1),(1,5,2),(2,4,2),(2,5,4)]),
 dict(id='H04',name='三夹紧单元',parts=[('A400','三夹紧单元','组合件','套'),('S410','夹紧子总成','组合件','套'),('P420','安装板','Q235B','件'),('P411','夹爪','45','件'),('B412','内六角螺钉M6×16','35','件')],edges=[(0,1,3),(0,2,1),(1,3,2),(1,4,4)],wrong=(4,11)),
]

def make(case):
    parts,edges=case['parts'],case['edges']; totals=[0]*len(parts);totals[0]=1
    nodes=[dict(id='root',parent_id=None,component_index=0,quantity_per_parent=None,source_page=1,evidence='标题及装配说明：整机数量1套')]
    def walk(part,parent_id,mult):
        for a,b,q in edges:
            if a!=part:continue
            totals[b]+=mult*q
            nid='n'+str(len(nodes));nodes.append(dict(id=nid,parent_id=parent_id,component_index=b,quantity_per_parent=q,source_page=1,evidence=f'{parts[a][0]} 每套包含 {parts[b][0]} × {q}'))
            walk(b,nid,mult*q)
    walk(0,'root',1)
    printed=totals[:]
    if 'wrong' in case:printed[case['wrong'][0]]=case['wrong'][1]
    image=Image.new('RGB',(3000,2120),'white');d=ImageDraw.Draw(image)
    def text(x,y,s,size=30,fill='black'):d.text((x,y),s,font=ImageFont.truetype(FONT,size),fill=fill)
    def line(xy,width=3):d.line(xy,fill='black',width=width)
    def rect(box,width=3):d.rectangle(box,outline='black',width=width)
    def bolt(x,y):
        rect((x,y,x+90,y+22));rect((x+31,y+22,x+59,y+100))
        for yy in range(y+35,y+96,12):line((x+31,yy,x+59,yy-10),2)
    def balloon(x,y,label,tx,ty):
        d.ellipse((x-24,y-24,x+24,y+24),outline='black',width=3);text(x-10,y-21,str(label),27);line((x+22,y,tx,ty),2)
    rect((30,30,2970,2090),4)
    text(70,50,f'{case["id"]}  {case["name"]} — 装配关系测试图',48)
    text(70,120,'轴测/拆分示意 · 位置仅辅助识别，装配关系以本图文字说明为依据',29)
    line((40,180,2960,180));line((1700,180,1700,1690))
    text(80,205,'装配结构示意',34)
    # Schematic exploded views: brackets/plate, rings, screws, replicated modules.
    rect((210,760,1450,850));line((210,850,265,900,1505,900,1505,810,1450,760))
    line((1450,850,1505,900));text(460,925,'整机 / 总成：'+parts[0][0],34)
    children=[(b,q) for a,b,q in edges if a==0]
    for j,(b,q) in enumerate(children):
        x=250+j*440
        if parts[b][0].startswith('B'):
            bolt(x+80,510)
        elif '轴承' in parts[b][1]:
            d.ellipse((x+20,445,x+225,650),outline='black',width=5);d.ellipse((x+67,492,x+178,603),outline='black',width=4)
        else:
            rect((x,475,x+260,615),4);rect((x+35,405,x+225,475),4)
            d.ellipse((x+96,510,x+165,580),outline='black',width=3)
        line((x+130,660,x+130,750),2)
        balloon(x+25,360,b+1,x+130,405)
        text(x-25,290,f'{parts[b][0]} × {q}',31)
    text(80,1010,'装配说明（× 后数值均为“每一个父件”的用量）',32)
    for k,(a,b,q) in enumerate(edges):
        text(90,1080+k*65,f'{k+1}. {parts[a][0]} 每套包含 {parts[b][0]} × {q}',32)
    text(90,1520,'整机基准数量：1套。子总成重复安装时，其内部零件用量随之相乘。',29)
    text(90,1580,'同一件号允许用于不同父件；此时为不同装配节点，不能合并父关系。',29)
    text(1760,210,'明细栏（数量＝每1套整机的展开总量）',33)
    cols=[1740,1840,2040,2510,2730,2870,2950]
    headers=['序号','件号','名称','材料','数量','单位']
    for i,h in enumerate(headers):text(cols[i]+8,280,h,27)
    for row in range(len(parts)+2):line((1740,265+row*92,2950,265+row*92),2)
    for x in cols:line((x,265,x,265+(len(parts)+1)*92),2)
    for i,(pn,name,mat,unit) in enumerate(parts):
        vals=[str(i+1),pn,name,mat,str(printed[i]),unit]
        for k,value in enumerate(vals):text(cols[k]+8,375+i*92,value,26 if k==2 else 28)
    text(1760,1030,'技术说明',33)
    for k,s in enumerate(['1. 图中件号与明细栏件号相对应。','2. 明细栏包含整机、子总成和零件。','3. 图形为结构示意，不按比例测量。','4. 本图只用于BOM及装配关系测试。','5. 不进行尺寸、公差、形位合规验收。']):text(1760,1090+k*65,s,29)
    line((40,1690,2960,1690));text(80,1730,'装配示意图 / 非生产制造图',38)
    text(80,1800,'图号：'+case['id']+'-ASM     图名：'+case['name'],34)
    text(80,1860,'设计：测试员     日期：2026-09-26     版本：A     页码：1/1',32)
    text(80,1920,'材料：组合件（各件见明细栏）     比例：不按比例     单位：mm',32)
    text(80,1990,'合成测试数据；未经独立工程师审定，不用于加工、制造或工程签署。',29)
    stem=OUT/case['id'];image.save(str(stem)+'.png')
    doc=fitz.open();page=doc.new_page(width=900,height=636);page.insert_image(page.rect,filename=str(stem)+'.png');doc.save(str(stem)+'.pdf');doc.close()
    expected=dict(case_id=case['id'],synthetic=True,review_status='programmatically_consistent_not_independently_engineer_reviewed',
        source_sha256=hashlib.sha256(Path(str(stem)+'.png').read_bytes()).hexdigest(),
        components=[dict(item_no=i+1,part_number=p[0],name_zh=p[1],material=p[2],quantity=printed[i],unit=p[3],source_page=1) for i,p in enumerate(parts)],
        assembly={'nodes':nodes},exploded_quantities={p[0]:totals[i] for i,p in enumerate(parts)},
        expected_findings=([dict(err_id='ERR-08',part_number=parts[case['wrong'][0]][0],printed_quantity=11,expected_quantity=12,evidence='3套子总成 × 每套4颗 = 12，与明细栏11冲突',action='保留原始提取11；提出改为12的候选，需人工确认')] if 'wrong' in case else []),
        scope='BOM字段及装配父子关系；不评价尺寸/公差/形位合规。根节点level=1，用量null。节点ID可不同，以父子件号及用量比较。')
    from engine_bom.assembly import validate_tree
    tree=validate_tree(expected['assembly'],expected['components']);expected['max_depth']=tree['max_depth'];expected['expected_node_count']=len(nodes)
    Path(str(stem)+'.expected.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding='utf-8')
    return expected

if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT))
    results=[make(c) for c in CASES]
    (OUT/'manifest.json').write_text(json.dumps([{'id':r['case_id'],'bom_rows':len(r['components']),'nodes':r['expected_node_count'],'depth':r['max_depth']} for r in results],ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(json.loads((OUT/'manifest.json').read_text(encoding='utf-8')),ensure_ascii=False))
