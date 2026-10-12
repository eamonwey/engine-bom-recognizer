"""Re-run real inspection using existing extraction; preserve the original job."""
import json
import os
import sys
import urllib.request
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from engine_bom.webapp import load_web_config
from engine_bom.pipeline import BomPipeline
from engine_bom.hybrid_inspection import inspect

root=Path(__file__).resolve().parents[1]
folder=root/'data'/'acceptance'/'axis_support_01'/('retest_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
folder.mkdir(parents=True,exist_ok=False)
with urllib.request.urlopen('http://127.0.0.1:8788/api/jobs/20260923135530-75599a') as response:
    original=json.load(response)
(folder/'original_job.json').write_text(json.dumps(original,ensure_ascii=False,indent=2),encoding='utf-8')
data=original['result']
config=load_web_config()
provider=BomPipeline(config,base_dir=str(folder)).provider
image=Image.open(root/'data'/'acceptance'/'axis_support_01'/'TEST-100-A.png').convert('RGB')
report=inspect(provider,[image],data['title_block'],data['bom']['components'],data['dimensions'],data['balloons'],config.get('inspection'))
(folder/'inspection.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'report':str(folder/'inspection.json'),'visual_status':report['visual_status'],
 'chains':report['dimension_chains']['status'],'issues':report['issues'],
 'attempts':len(report['events'])},ensure_ascii=False,indent=2))
