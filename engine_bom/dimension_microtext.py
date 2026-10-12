"""Tightly reread undecodable OCR neighbors, without expected numerical values."""
import json,re
from .agent_loop import AgentLoop
from .parsing import extract_json_payload
from .providers import ProviderError
from .dimension_text import fit_body


def diameter_prefix(text):
    # An unresolved fit letter is kept verbatim. No 627 -> 62 transformation.
    if not isinstance(text,str):return None
    value=re.sub(r'\s+','',text)
    if '?' in value:return None  # Missing digits must never be inferred.
    match=re.fullmatch(r'[ΦφØ∅](\d+(?:\.\d+)?)(?:[A-Za-z√?]{1,2}\d{0,2}(?:/[A-Za-z?]{1,2}\d{0,2})?)?',value)
    return match.group(1) if match else None


def reread_neighbors(provider,images,candidates):
    from PIL import Image
    inputs=[];mapping=[]
    for candidate in candidates[:8]:
        image=images[candidate['source_page']-1];w,h=image.size;a=candidate['bbox']
        height=(a[3]-a[1])*h
        px=[max(0,round(a[0]*w-height)),max(0,round(a[1]*h-height*.15)),
            min(w,round(a[2]*w+height*.15)),min(h,round(a[3]*h+height*.15))]
        tile=image.crop(tuple(px)).convert('RGB');tile=tile.resize((tile.width*3,tile.height*3),Image.LANCZOS)
        inputs.append(tile);mapping.append(dict(id='text-%d'%len(inputs),source_page=candidate['source_page'],
            bbox=[px[0]/w,px[1]/h,px[2]/w,px[3]/h]))
    report={'status':'not_run','observations':[],'events':[],
        'warning':'局部回读仍由视觉模型完成；不补猜不清的公差字母，也不证明实体配合关系。'}
    if not inputs:return report
    prompt='''TASK:DIMENSION_MICROTEXT
只逐字转写每张局部的中间那行纸面原文。不使用标准、型号、另一处文字或机械常识补猜字符。
看不清的字符用?，无法阅读填readable=false。不要判断尺寸是否正确，不输出建议数字。
保留直径符号；纸面没有则不能补上。只输出{"texts":[{"id":"text-1","raw_text":"原文","readable":true}]}。
每张图都必须返回一次。顺序：'''+json.dumps([m['id'] for m in mapping])
    def validator(raw):
        value,errors=extract_json_payload(raw);rows=value.get('texts') if isinstance(value,dict) else None
        if not isinstance(rows,list) or len(rows)!=len(mapping) or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) for r in rows):return {},['必须逐张返回texts']
        if {r['id'] for r in rows}!={m['id'] for m in mapping}:return {},['局部文字id缺失或重复']
        if any(type(r.get('readable')) is not bool or not isinstance(r.get('raw_text'),str) for r in rows):return {},['需原文与readable布尔值']
        return value,errors
    loop=AgentLoop(provider,1)
    try:result=loop.run(inputs,prompt,validator)
    except ProviderError:return dict(report,status='provider_failed',events=loop.last_result.events)
    report.update(status=result.status,events=result.events)
    if result.status!='validated':return report
    indexed={m['id']:m for m in mapping}
    report['readings']=result.value['texts']
    for row in result.value['texts']:
        number=diameter_prefix(row['raw_text'])
        if not row['readable'] or number is None:continue
        body=fit_body(row['raw_text'])
        report['observations'].append(dict(indexed[row['id']],raw_text=row['raw_text'],fit_body=body,
            nominal_diameter=number,fit_unreadable=body is None,origin='vlm_microtext'))
    return report
