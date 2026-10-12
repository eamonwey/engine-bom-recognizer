"""Re-run installation inference against an image and a saved BOM, without editing the job."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine_bom.webapp import load_web_config
from engine_bom.providers import build_provider
from engine_bom.ingestion import load_document
from engine_bom.assembly import infer_assembly

if __name__ == '__main__':
    image_path, job_path, output_path = sys.argv[1:]
    cfg = load_web_config()
    components = json.loads(Path(job_path).read_text(encoding='utf-8'))['bom']['components']
    images = [p.image for p in load_document(image_path, cfg.get('ingestion') or {})]
    result = infer_assembly(build_provider(cfg['provider']), images, components, cfg['assembly'])
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: result.get(k) for k in ('inference_status', 'relation_semantics', 'max_depth', 'unresolved_component_indices')}, ensure_ascii=False))
    for node in result['nodes']:
        print(node['component_index'], node.get('component_name'), node['parent_id'], node.get('quantity_per_parent'))
