"""Live title-block-root acceptance; expected data is used only after inference."""
import json
import sys
from collections import Counter
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine_bom.webapp import load_web_config
from engine_bom.pipeline import BomPipeline

root = Path(__file__).resolve().parents[1]
folder = root / 'data/acceptance/gb_reference_20260926'
out = root / 'data/test_runs' / ('title_root_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
cfg = load_web_config()
cfg['output'] = {'dir': str(out), 'formats': ['json']}
result = BomPipeline(cfg, base_dir=str(root)).process_file(str(folder / 'N01.pdf'))
if result.bom is None:
    raise RuntimeError(result.errors)
bom = result.bom.to_dict()
tree = bom['assembly']
components = bom['components'] + tree.get('context_components', [])
nodes = {n['id']: n for n in tree['nodes']}
actual = Counter((components[nodes[n['parent_id']]['component_index']]['part_number'],
                  components[n['component_index']]['part_number'], n.get('quantity_per_parent'))
                 for n in nodes.values() if n['parent_id'] is not None)
expected = json.loads((folder / 'N01.expected.json').read_text(encoding='utf-8'))
target = Counter((e['parent'], e['child'], e['quantity_per_parent']) for e in expected['relations'])
summary = {'case': 'N01', 'passed': actual == target,
           'roots': [components[n['component_index']]['part_number'] for n in nodes.values() if n['parent_id'] is None],
           'bom_rows': len(bom['components']), 'title_roots': tree.get('context_components', []),
           'missing': list((target - actual).elements()), 'extra': list((actual - target).elements())}
out.mkdir(parents=True, exist_ok=True)
(out / 'acceptance.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
assert summary['passed'] and summary['roots'] == [expected['root']], 'Title-root acceptance failed'
