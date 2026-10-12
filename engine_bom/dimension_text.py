"""Optional local OCR evidence. Text and position are not geometric identity."""
import os
import re
import sys
import threading
from pathlib import Path

_lock=threading.Lock()
_engine=None
_dll_handles=[]


def _get_engine():
    global _engine
    if _engine is None:
        runtime=Path(__file__).resolve().parents[1]/'.runtime/ocr'
        if runtime.is_dir():
            if str(runtime) not in sys.path:sys.path.append(str(runtime))
            native=runtime/'onnxruntime/capi'
            if os.name=='nt' and hasattr(os,'add_dll_directory') and native.is_dir():
                _dll_handles.append(os.add_dll_directory(str(native)))
        from rapidocr_onnxruntime import RapidOCR
        _engine=RapidOCR(det_limit_side_len=2400)
    return _engine


def fit_body(text):
    if not isinstance(text,str):return None
    body=re.sub(r'\s+','',text).lstrip('ΦφØ∅')
    return body if re.fullmatch(r'\d+(?:\.\d+)?[A-Za-z]{1,2}\d{1,2}(?:/[A-Za-z]{1,2}\d{1,2})?',body) else None


def read_fit_text(images,collect_neighbors=False):
    report={'status':'not_available','observations':[],'numeric_neighbors':[],
        'warning':'本地OCR仅提供原文与文字位置，不证明配合关系；缺失直径符号不会自动补成直径。'}
    try:
        import numpy as np
        with _lock:
            engine=_get_engine()
            for page,original in enumerate(images,1):
                if not hasattr(original,'size'):continue
                image=original.convert('RGB');scale=min(2,3100/max(image.size))
                if scale!=1:image=image.resize((max(1,round(image.width*scale)),max(1,round(image.height*scale))))
                rows,_=engine(np.array(image))
                for row in rows or []:
                    if not isinstance(row,(list,tuple)) or len(row)!=3:continue
                    points,text,confidence=row
                    body=fit_body(text)
                    if body is None or confidence<.88:continue
                    box=[min(p[0] for p in points)/image.width,min(p[1] for p in points)/image.height,
                         max(p[0] for p in points)/image.width,max(p[1] for p in points)/image.height]
                    if not all(0<=v<=1 for v in box) or box[0]>=box[2] or box[1]>=box[3]:continue
                    report['observations'].append(dict(raw_text=text,fit_body=body,confidence=float(confidence),source_page=page,bbox=box))
            if collect_neighbors:
                # A tiny handwritten fit glyph can merge into neighboring
                # digits (e.g. "627"). Preserve raw candidates; never convert
                # them into a guessed fit/diameter. A separate crop reread is
                # required to recognize a diameter symbol and nominal value.
                seeds=[s for s in report['observations'] if '/' in s['fit_body']][:6]
                for seed in seeds:
                    original=images[seed['source_page']-1];w,h=original.size;a=seed['bbox']
                    px=[round(max(0,a[0]-.08)*w),round(max(0,a[1]-.12)*h),round(min(1,a[2]+.08)*w),round(min(1,a[3]+.12)*h)]
                    tile=original.crop(tuple(px)).convert('RGB');tile=tile.resize((tile.width*2,tile.height*2))
                    rows,_=engine(np.array(tile))
                    for points,text,confidence in rows or []:
                        if not re.fullmatch(r'\d{3,4}',str(text)) or confidence<.6:continue
                        box=[(min(p[0] for p in points)/2+px[0])/w,(min(p[1] for p in points)/2+px[1])/h,
                             (max(p[0] for p in points)/2+px[0])/w,(max(p[1] for p in points)/2+px[1])/h]
                        candidate=dict(raw_text=text,source_page=seed['source_page'],bbox=box)
                        if candidate not in report['numeric_neighbors']:report['numeric_neighbors'].append(candidate)
        report['status']='read' if report['observations'] else 'no_readable_fit_text'
    except (ImportError,OSError,RuntimeError,ValueError) as exc:
        report['error_type']=type(exc).__name__
    return report


def refine_positions(observations,local_text):
    """Only an exact fit-body reread may refine a unique nearby text position."""
    output=[]
    for observation in observations:
        obs=dict(observation);body=fit_body(obs.get('value'));box=obs.get('bbox')
        matches=[]
        for text in local_text.get('observations',[]):
            exact=body and body==text.get('fit_body')
            # Numeric-only support requires a visibly reread diameter symbol,
            # and explicitly leaves the fit suffix unverified. Bare "627"
            # cannot support a claimed nominal 62.
            micro=text.get('nominal_diameter')
            claim=re.match(r'^[ΦφØ∅](\d+(?:\.\d+)?)',str(obs.get('value') or ''))
            numeric=micro is not None and claim and claim.group(1)==micro
            if not (exact or numeric) or obs.get('source_page')!=text['source_page']:continue
            a,b=box,text['bbox'];distance=((a[0]+a[2]-b[0]-b[2])/2)**2+((a[1]+a[3]-b[1]-b[3])/2)**2
            if distance<=.15**2:matches.append((distance,text))
        matches.sort(key=lambda entry:entry[0])
        # Similar repeated annotations cannot be resolved by arbitrary order.
        if matches and (len(matches)==1 or matches[1][0]-matches[0][0]>.03**2):
            text=matches[0][1]
            obs.update(bbox_before_local_text=box,bbox=text['bbox'],local_text_evidence=text)
            if text.get('fit_unreadable'):obs['fit_text_unverified']=True
        output.append(obs)
    return output


def filter_position_conflicts(observations,local_text):
    """Quarantine a claimed value placed on a differently read text region.

    High overlap is required. OCR is a veto requiring rereading, never a source
    of replacement nominal values or object identities.
    """
    kept=[];rejected=[]
    for obs in observations:
        body=fit_body(obs.get('value'));a=obs.get('bbox');conflicts=[]
        for text in local_text.get('observations',[]):
            if not body or body==text.get('fit_body') or obs.get('source_page')!=text.get('source_page') or text.get('confidence',0)<.88:continue
            b=text['bbox']
            area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area
            if union>0 and area/union>=.6:conflicts.append(text)
        if conflicts:
            rejected.append({'observation':obs,'reasons':['尺寸值与同一文字框的本地回读矛盾，不能采纳该定位，必须重新读图'],
                             'local_text_conflicts':conflicts})
        else:kept.append(obs)
    return kept,rejected
