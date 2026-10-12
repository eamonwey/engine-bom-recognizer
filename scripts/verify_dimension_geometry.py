"""Run fresh dimension extraction and chain validation without changing saved jobs."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine_bom.webapp import load_web_config
from engine_bom.providers import build_provider
from engine_bom.ingestion import load_document
from engine_bom.titleblock import extract_dims_and_balloons
from engine_bom.dimension_chains import inspect_chains


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('image')
    parser.add_argument('output')
    args = parser.parse_args()
    cfg = load_web_config()
    provider = build_provider(cfg.get('provider') or {})
    images = [page.image for page in load_document(args.image, cfg.get('ingestion') or {})]
    dimensions = extract_dims_and_balloons(provider, images)['dimensions']
    print('Fresh dimension extraction complete: %d dimensions' % len(dimensions), flush=True)
    report = inspect_chains(provider, images, dimensions, attempts=2)
    output = {'source_file':args.image, 'dimensions':dimensions, 'dimension_chains':report}
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status':report['status'], 'issues':report['issues'],
                      'dimensions_of_interest':[d for d in dimensions if str(d.get('value')) in ('49','100','172')]},
                     ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
