"""Restore the user's known original Qwen credentials without displaying them."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
from engine_bom.providers.openai_compat import OpenAICompatVisionProvider
from engine_bom.providers.base import ProviderError
from engine_bom.parsing import extract_json_payload

def main():
    source=Path('C:/Users/v10/.zcode/workspace/default/engine-bom-recognizer/data/web_settings.json')
    original=json.loads(source.read_text(encoding='utf8'))['provider']['openai_compat']
    cfg=dict(original,model='qwen3.7-flash',temperature=0.0,max_tokens=16384,enable_thinking=False,timeout=180,retries=1)
    provider=OpenAICompatVisionProvider(dict(cfg,max_tokens=128,retries=0))
    checked=False;failure=None
    try:
        reply=provider.analyze([Image.new('RGB',(64,64),'white')],
            'Read the image background color. Return only JSON with the single key visible_color, value one lowercase color word.')
        value,errors=extract_json_payload(reply.raw_text)
        checked=not errors and isinstance(value,dict) and value.get('visible_color')=='white'
    except ProviderError as exc:failure=type(exc).__name__
    if not checked:cfg['api_key']=''  # Never send the old GLM credential to Qwen.
    target=ROOT/'data/web_settings.json';current=json.loads(target.read_text(encoding='utf8'))
    backup=ROOT/'.runtime/provider_restore';backup.mkdir(parents=True,exist_ok=True)
    backup_file=backup/'glm-settings.json'
    if not backup_file.exists():
        backup_file.write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf8')
    current['provider']={'name':'openai_compat','openai_compat':cfg}
    temp=target.with_suffix('.tmp');temp.write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(target)
    print(json.dumps({'model':provider.model,'visual_connection_check':'passed' if checked else 'needs_valid_api_key',
                      'error_type':failure},ensure_ascii=False))

if __name__=='__main__':main()
