"""Verify vision with existing credentials, save first suitable Qwen profile."""
import copy
import argparse
import datetime
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fitz
from PIL import Image
from engine_bom.providers.openai_compat import OpenAICompatVisionProvider
from engine_bom.parsing import extract_json_payload
from engine_bom.webapp import load_web_config, save_web_settings

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--out',default='data/reports/validation/model_selection_2026-09-17.json')
parser.add_argument('--skip',nargs='*',default=[])
args=parser.parse_args()
out=ROOT/args.out
if out.exists(): raise RuntimeError('Use a new --out path; preserve earlier model selection reports')
cfg=load_web_config()
profile=cfg['provider']['openai_compat']
doc=fitz.open(str(ROOT/'data/validation/synthetic/inputs/synthetic_01_clean.pdf'))
pix=doc[0].get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False)
image=Image.frombytes('RGB',[pix.width,pix.height],pix.samples)
doc.close()
records=[]
selected=None
for model in ['qwen3.7-max-2026-06-08','qwen3.7-plus','qwen3.8-flash','qwen3.6-plus','qwen3.5-plus']:
    if model in args.skip: continue
    local=copy.deepcopy(profile)
    local.update(model=model,enable_thinking=False,max_tokens=128,timeout=45,retries=0)
    try:
        response=OpenAICompatVisionProvider(local).analyze([image],'阅读图片，只返回JSON对象 {"drawing_no":"图中Drawing no后的图号原文"}。不要猜测。')
        value,errors=extract_json_payload(response.raw_text)
        verified=isinstance(value,dict) and value.get('drawing_no')=='SYN-ASM-01'
        records.append({'model':model,'status':'vision_verified' if verified else 'incorrect_probe','reply':response.raw_text,'latency_s':response.latency_s,'usage':response.usage})
        if verified:
            selected=model
            save_web_settings({'provider':{'name':'openai_compat','openai_compat':{'model':model,'enable_thinking':False,'max_tokens':12000}}})
            break
    except Exception as exc:
        records.append({'model':model,'status':'unavailable','error':str(exc)[:700]})
    print(model,records[-1]['status'],flush=True)
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':'https://help.aliyun.com/zh/model-studio/vision-model','candidates':records,'selected':selected,'billing_mode_changed':False,'probe':'Read synthetic drawing number from actual image; no label supplied'},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'selected':selected,'report':str(out)},ensure_ascii=False))
if not selected:sys.exit(2)

