"""Vector assembly test drawings with measured geometry and explicit audit limits.
Reference design, not an independently certified manufacturing drawing set.
"""
from pathlib import Path
import json, math, hashlib, zipfile
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm
import fitz
import sys
if sys.version_info < (3,9):
    # ReportLab's PDF document identifier uses the newer optional hashlib keyword.
    from reportlab.pdfbase import pdfdoc
    pdfdoc.md5 = lambda data=b'', **kwargs: hashlib.md5(data)

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/acceptance/gb_reference_20260926'
OUT.mkdir(parents=True,exist_ok=True)
pdfmetrics.registerFont(TTFont('Fang','C:/Windows/Fonts/simfang.ttf'))
checks=[]
def txt(c,x,y,s,h=3.5,center=False):
    h=3.5 if h<4.5 else 5
    s=str(s); width=pdfmetrics.stringWidth(s,'Fang',h*mm)*.75/mm
    if center:x-=width/2
    assert x>=25 and x+width<=415.1 and y>=5 and y+h<=292.1,(s,x,y,width)
    t=c.beginText(x*mm,y*mm);t.setFont('Fang',h*mm);t.setHorizScale(75);t.textOut(s);c.drawText(t)
def ln(c,x1,y1,x2,y2,w=.25,dash=None):
    c.setLineWidth(w*mm);c.setDash([v*mm for v in dash] if dash else []);c.line(x1*mm,y1*mm,x2*mm,y2*mm);c.setDash([])
def box(c,x,y,w,h,line=.5):c.setLineWidth(line*mm);c.rect(x*mm,y*mm,w*mm,h*mm)
def circle(c,x,y,r,w=.5):c.setLineWidth(w*mm);c.circle(x*mm,y*mm,r*mm)
def socket(c,x,y,r):
    p=c.beginPath()
    for i in range(6):
        px=(x+r*math.cos(i*math.pi/3))*mm;py=(y+r*math.sin(i*math.pi/3))*mm
        (p.moveTo if i==0 else p.lineTo)(px,py)
    p.close();c.setLineWidth(.25*mm);c.drawPath(p)
def arrow(c,x,y,dx,dy):
    p=c.beginPath();p.moveTo(x*mm,y*mm);p.lineTo((x+dx*2+dy*.65)*mm,(y+dy*2-dx*.65)*mm);p.lineTo((x+dx*2-dy*.65)*mm,(y+dy*2+dx*.65)*mm);p.close();c.drawPath(p,fill=1,stroke=0)
def dim(c,x1,x2,y,origin,label):
    ln(c,x1,origin,x1,y+2);ln(c,x2,origin,x2,y+2);ln(c,x1,y,x2,y)
    arrow(c,x1,y,1,0);arrow(c,x2,y,-1,0);txt(c,(x1+x2)/2,y+1.3,label,center=True)
def vdim(c,y1,y2,x,origin,label):
    ln(c,origin,y1,x-2,y1);ln(c,origin,y2,x-2,y2);ln(c,x,y1,x,y2)
    arrow(c,x,y1,0,1);arrow(c,x,y2,0,-1);txt(c,x-7,(y1+y2)/2,label,3)
def center(c,x,y,rx,ry):
    ln(c,x-rx,y,x+rx,y,.18,[7,1.5,1,1.5]);ln(c,x,y-ry,x,y+ry,.18,[7,1.5,1,1.5])
def leader(c,n,tx,ty,x,y):
    ln(c,tx,ty,x,y);c.circle(tx*mm,ty*mm,.55*mm,stroke=0,fill=1);ln(c,x-3,y,x+4,y);txt(c,x+.5,y+1,n,5,True)
def hatch(c,x,y,w,h,reverse=False):
    c.saveState();p=c.beginPath();p.rect(x*mm,y*mm,w*mm,h*mm);c.clipPath(p,stroke=0)
    for k in range(-int(h)-4,int(w)+int(h)+4,3):
        ln(c,x+k,y,x+k+(-h if reverse else h),y+h,.18)
    c.restoreState();box(c,x,y,w,h)
def white(c,x,y,w,h):
    c.saveState();c.setFillColorRGB(1,1,1);c.rect(x*mm,y*mm,w*mm,h*mm,fill=1,stroke=0);c.restoreState()

PARTS={
 'P1001':('模块底板','45','100×60×10'), 'P1002':('四孔垫块','45','60×40×10'),
 'P1102':('两孔垫块','45','60×40×10'), 'P2001':('双模块安装板','Q235B','280×100×10'),
 'P4001':('三模块安装板','Q235B','410×100×10'),
 'B16':('内六角圆柱头螺钉','钢 / 8.8','M6×16'), 'B20':('内六角圆柱头螺钉','钢 / 8.8','M6×20'),
 'G100':('四螺钉垫块组件','组合件','见子装图'), 'G110':('两螺钉垫块组件','组合件','见子装图')}
SCREW_STANDARD='GB/T 70.1-2008'

def sheet(c,code,name,rows,scale,page,pages,defect=False):
    box(c,25,5,390,287,.7)
    ln(c,210,292,210,287,.5);ln(c,210,5,210,10,.5);ln(c,25,148.5,30,148.5,.5);ln(c,415,148.5,410,148.5,.5)
    txt(c,30,284,'机械制图参考测试图 · '+('故意错误样本' if defect else '基准样本'),4.2)
    # A 180 x 56 title block, right lower corner. Signature cells remain unsigned.
    x,y=235,5;box(c,x,y,180,56,.5)
    for xx in [x+55,x+110]:ln(c,xx,y,xx,y+56)
    for yy in [y+14,y+28,y+42]:ln(c,x,yy,x+55,yy)
    for yy in [y+14,y+28]:ln(c,x+55,yy,x+180,yy)
    ln(c,x+55,y+42,x+110,y+42)
    for yy,label,value in [(y+45,'设计','测试样本'),(y+31,'校核','未签署'),(y+17,'审核','未签署'),(y+3,'日期','2026-09-26')]:txt(c,x+2,yy,label);txt(c,x+18,yy,value,3)
    for yy,s in [(y+45,'材料：组合件'),(y+31,'比例 '+scale+'    版本 A'),(y+17,f'第 {page} 张 / 共 {pages} 张'),(y+3,'阶段：测试 / 单位 mm')]:txt(c,x+57,yy,s,3)
    txt(c,x+112,y+46,'BOM识别测试项目',4);txt(c,x+112,y+32,name,4)
    txt(c,x+112,y+18,code,5);txt(c,x+112,y+4,'未作生产放行',3.5)
    # Items grow upwards; the first item is directly above the title block.
    bounds=[235,245,287,345,357,380,415]
    for j,(pn,qty) in enumerate(rows):
        yy=61+j*8;ln(c,235,yy,415,yy)
        namep,mat,spec=PARTS[pn]
        vals=[str(j+1),pn,namep,str(qty),mat,spec]
        for i,value in enumerate(vals):txt(c,bounds[i]+1,yy+2.4,value,3.0 if i in (2,4,5) else 3.5)
    top=61+len(rows)*8;ln(c,235,top,415,top);ln(c,235,top+8,415,top+8)
    for xx in bounds:ln(c,xx,61,xx,top+8)
    for i,value in enumerate(['序号','图号/代号','名称','数量','材料','规格/备注']):txt(c,bounds[i]+1,top+2.4,value,3)
    txt(c,238,top+11,'明细栏数量：每1套本图所示装配体',3)
    txt(c,30,10,'图样参考公开机械制图国标；自审范围及未验证项见随附记录。',3)
    txt(c,30,16,'本图不含生产批准或国军标合规声明。PDF按实际大小打印。',3)

def module(c,variant,page,pages):
    code='G100' if variant==4 else 'G110';pad='P1002' if variant==4 else 'P1102'
    rows=[('P1001',1),(pad,1),('B16',variant)]
    sheet(c,code,PARTS[code][0],rows,'1:1',page,pages)
    ox=65;fz=222;py=109
    # Aligned front/plan views, first-angle: plan below front.
    hatch(c,ox,fz,100,10);hatch(c,ox+20,fz+10,60,10,True)
    for xx in [ox+30,ox+70]:
        white(c,xx-3.5,fz+10,7,10);ln(c,xx-3.5,fz+10,xx-3.5,fz+20);ln(c,xx+3.5,fz+10,xx+3.5,fz+20)
        white(c,xx-3,fz+4,6,16);box(c,xx-3,fz+4,6,16,.35);box(c,xx-5,fz+20,10,6,.5)
        ln(c,xx-2.4,fz+4,xx-2.4,fz+12,.18);ln(c,xx+2.4,fz+4,xx+2.4,fz+12,.18)
        center(c,xx,fz+15,0,15)
    txt(c,115,263,'A—A',5,True)
    dim(c,ox,ox+100,255,fz,'100');vdim(c,fz,fz+26,ox-13,ox,'26')
    leader(c,1,ox+8,fz+5,45,246);leader(c,2,ox+23,fz+17,40,263);leader(c,3,ox+70,fz+24,199,260)
    box(c,ox,py,100,60);box(c,ox+20,py+10,60,40)
    holeys=[18,42] if variant==4 else [30]
    for hx in [30,70]:
        for hy in holeys:
            circle(c,ox+hx,py+hy,5);socket(c,ox+hx,py+hy,2.89);center(c,ox+hx,py+hy,7,7)
    for hx in [10,90]:
        for hy in [8,52]:circle(c,ox+hx,py+hy,3.5);center(c,ox+hx,py+hy,6,6)
    cut_y=py+holeys[-1]
    for x in [ox-7,ox+107]:
        ln(c,x,cut_y,x,cut_y-7,.7);arrow(c,x,cut_y,0,-1);txt(c,x-2,cut_y+3,'A',5)
    ln(c,ox-7,cut_y,ox+107,cut_y,.25,[9,2,1,2])
    dim(c,ox+10,ox+90,94,py+8,'80');vdim(c,py+8,py+52,ox-14,ox+10,'44')
    vdim(c,py,py+60,ox-25,ox,'60')
    # Callout leaders terminate at clearance-hole boundaries.
    ln(c,ox+90,py+52,193,178);ln(c,193,178,224,178);txt(c,194,180,'4×Φ7 通孔',3.5)
    for k,s in enumerate([
      '技术要求', '1. 采用第一角投影；尺寸单位为mm。',
      '2. 上垫块居中，底板与垫块接合面贴合。',
      f'3. 件3为 {SCREW_STANDARD} M6×16，8.8级。',
      f'4. 件2以{variant}颗件3固定；穿过10厚垫块，',
      '   螺纹名义旋入底板6；底板螺纹孔深8。',
      '5. 4个Φ7通孔为对外安装接口，孔距80×44。',
      '6. 尺寸为装配接口要求；零件加工另需零件图。',
      '7. 接合面不得有毛刺；装配后无松动。',
      '8. 共用底板预留3排×2列M6孔，未用孔保留。',
      '9. 本测试不规定载荷、扭矩或强度验收指标。']):txt(c,240,257-k*7,s,3.3 if k else 4)
    checks.append({'sheet':code,'scale':'1:1','geometry_mm':[100,60,26], 'bom_qty':[1,1,variant], 'nominal_screw_engagement':6,'thread_depth':8,'body_width_on_pdf_mm':100})
    c.showPage();return rows

def top(c,code,count,variants,page,pages,bad=False):
    length=410 if count==3 else 280;base='P4001' if count==3 else 'P2001'
    modules=[]
    for v in variants:
        pn='G100' if v==4 else 'G110'
        if pn not in [p for p,q in modules]:modules.append((pn,variants.count(v)))
    rows=[(base,1)]+modules+[('B20',11 if bad else count*4)]
    name='三模块安装组件' if count==3 else ('混合模块安装组件' if len(modules)>1 else '双模块安装组件')
    sheet(c,code,name,rows,'1:2',page,pages,bad)
    ox=40;s=.5;fz=220;py=124;centres=[length/2+(i-(count-1)/2)*130 for i in range(count)]
    box(c,ox,fz,length*s,10*s)
    for centre,v in zip(centres,variants):
        x=ox+(centre-50)*s;box(c,x,fz+5,100*s,10*s);box(c,x+20*s,fz+10,60*s,10*s)
        # Inner module screw heads above pads.
        for xx in [x+30*s,x+70*s]:box(c,xx-5*s,fz+15,10*s,6*s)
        # Interface screws through module base into installation plate, outside pad.
        for xx in [x+10*s,x+90*s]:
            box(c,xx-5*s,fz+10,10*s,6*s);ln(c,xx-3*s,fz,xx-3*s,fz+10,.25,[2,1]);ln(c,xx+3*s,fz,xx+3*s,fz+10,.25,[2,1])
        number=2+[p for p,q in modules].index('G100' if v==4 else 'G110')
        leader(c,number,x+50*s,fz+12, x+48*s,253)
    leader(c,1,ox+4,fz+2,45,242)
    leader(c,len(rows),ox+(centres[-1]+40)*s,fz+12,ox+length*s-4,243)
    dim(c,ox,ox+length*s,270,fz,str(length));vdim(c,fz,fz+36*s,ox-7,ox,'36')
    box(c,ox,py,length*s,100*s)
    for centre,v in zip(centres,variants):
        x=ox+(centre-50)*s;y=py+20*s;box(c,x,y,100*s,60*s);box(c,x+20*s,y+10*s,60*s,40*s)
        for hx in [10,90]:
            for hy in [8,52]:circle(c,x+hx*s,y+hy*s,5*s);center(c,x+hx*s,y+hy*s,4,4)
        for hx in [30,70]:
            for hy in ([18,42] if v==4 else [30]):circle(c,x+hx*s,y+hy*s,5*s)
        center(c,x+50*s,py+50*s,0,30)
    center(c,ox+length*s/2,py+50*s,length*s/2+3,0)
    dim(c,ox+centres[0]*s,ox+centres[1]*s,111,py,'130')
    if count==3:dim(c,ox+centres[1]*s,ox+centres[2]*s,111,py,'130')
    vdim(c,py,py+100*s,ox-7,ox,'100')
    txt(c,40,75,'俯视图中模块相对于安装板宽度方向居中；模块中心对称布置。',3.2)
    txt(c,40,68,'各模块4处安装接口与子装图对应；同类模块只标注一次序号。',3.2)
    notes=['技术要求','1. 采用第一角投影；尺寸单位为mm。',f'2. 件1上安装{count}套模块；模块间中心距130。',
      f'3. 每套模块用4颗件{len(rows)}固定，螺钉从上方穿入。',
      f'4. 件{len(rows)}为 {SCREW_STANDARD} M6×20，8.8级。',
      '5. 件1安装孔为M6通螺纹，与模块80×44孔距对应。',
      '6. 穿过模块底板10厚，旋入件1名义长度10。',
      '7. 子装图列出每套模块内部零件及数量。',
      '8. 所有接合面贴合；紧固后模块不得松动。',
      '9. 本图仅为装配测试设计，未完成载荷校核。']
    for k,line in enumerate(notes):txt(c,265,266-k*7,line,3.15 if k else 4)
    if bad:txt(c,265,188,'故意错误样本：不可作为合格基准图。',3.5)
    checks.append({'sheet':code,'scale':'1:2','geometry_mm':[length,100,36],'body_width_on_pdf_mm':length/2,'module_count':count,'interface_screws_required':count*4,'interface_screws_printed':rows[-1][1],'expected_defect':bad})
    c.showPage();return rows

def generate():
    sets=[('N01',None,[4]),('N02','G200',[4,4]),('N03','G300',[4,2]),('E04','G400',[4,4,4])]
    manifest=[]
    for case,root,variants in sets:
        filename=OUT/(case+'.pdf');c=canvas.Canvas(str(filename),pagesize=(420*mm,297*mm));c.setTitle(case+' 装配层级测试图')
        sheetrows=[];unique=list(dict.fromkeys(variants));pages=1 if root is None else 1+len(unique)
        if root:sheetrows.append((root,top(c,root,len(variants),variants,1,pages,case=='E04')))
        for i,v in enumerate(unique):sheetrows.append(('G100' if v==4 else 'G110',module(c,v,i+1+(root is not None),pages)))
        c.save()
        root=root or 'G100';relations=[];occurrences=[];totals={}
        rowdict=dict(sheetrows)
        def walk(pn,path,mult):
            occurrences.append({'path':path,'part_number':pn,'total_quantity_on_path':mult})
            for child,qty in rowdict.get(pn,[]):
                trueqty=12 if case=='E04' and pn=='G400' and child=='B20' else qty
                relations.append({'parent_path':path,'parent':pn,'child':child,'quantity_per_parent':trueqty})
                totals[child]=totals.get(child,0)+mult*trueqty
                walk(child,path+'/'+child,mult*trueqty)
        walk(root,root,1)
        expected={'case':case,'root':root,'root_source':'标题栏图号；根总成不重复列入自身明细栏',
          'bom_by_sheet':[{'source_page':i+1,'drawing_no':pn,'rows':[{'item_no':j+1,'part_number':p,'name_zh':PARTS[p][0],'material':PARTS[p][1],'specification':PARTS[p][2],'quantity':q} for j,(p,q) in enumerate(rows)]} for i,(pn,rows) in enumerate(sheetrows)],
          'relations':relations,'occurrences':occurrences,'rolled_up_quantities':totals,'node_count':len(occurrences),'max_depth':max(p['path'].count('/')+1 for p in occurrences),
          'expected_findings':([{'err_id':'ERR-08','source_page':1,'part_number':'B20','printed_quantity':11,'required_quantity':12,'evidence':'3套模块，每套4颗安装螺钉，3×4=12；第一页明细栏11','action':'原文BOM保留11；提出12的修订候选，不自动替换'}] if case=='E04' else []),
          'status':'synthetic_reference_not_production_approved','caution':'这是预期目标，未实测模型。层级根来自标题栏，需要跨页按图号关联，不能混淆各页序号。'}
        (OUT/(case+'.expected.json')).write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding='utf-8')
        with fitz.open(filename) as pdf:
            assert len(pdf)==pages
            for i,page in enumerate(pdf):
                assert abs(page.rect.width/mm-420)<.01 and abs(page.rect.height/mm-297)<.01
                assert sheetrows[i][0] in page.get_text()
                page.get_pixmap(matrix=fitz.Matrix(2,2)).save(str(OUT/(case+f'-p{i+1}.png')))
        manifest.append({'case':case,'pages':pages,'bom_rows_per_page':[len(rows) for pn,rows in sheetrows],'nodes':len(occurrences),'max_depth':expected['max_depth'],'pdf_sha256':hashlib.sha256(filename.read_bytes()).hexdigest()})
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'geometry_audit.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__':generate()
