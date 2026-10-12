"""Real model acceptance on synthetic data only; never saves configuration secrets."""
import copy
import json
import sys
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine_bom import webapp as w

out = Path(sys.argv[1]).resolve() / 'live'
out.mkdir(parents=True, exist_ok=True)
config = w.load_web_config()
config['output'] = {'dir': str(out / 'outputs'), 'formats': ['json', 'csv', 'xlsx']}
w.load_web_config = lambda: copy.deepcopy(config)
records = []
fixtures = ROOT / 'data/acceptance/gb_reference_20260926'
for name, path in [('axis', ROOT/'data/acceptance/axis_support_01/TEST-100-A.png')] + [(n, fixtures/(n+'.pdf')) for n in ['N01', 'N02', 'N03', 'E04']]:
    started = time.monotonic()
    folder = out/name
    folder.mkdir(exist_ok=True)
    print('START '+name, flush=True)
    try:
        result = w._job_bom(str(folder), str(path), {'provider': 'openai_compat'})
        (folder/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        records.append({'case': name, 'status': 'completed', 'seconds': round(time.monotonic()-started, 2), 'rows': len(result['bom']['components']), 'assembly_status': result['bom']['assembly'].get('inference_status'), 'issue_count': len(result['issues'])})
    except Exception as exc:
        # Provider errors may include response body; record type/message, never config.
        records.append({'case': name, 'status': 'failed', 'seconds': round(time.monotonic()-started, 2), 'error': str(exc)})
    (out/'runs.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(records[-1], ensure_ascii=True), flush=True)
