"""Recheck saved real-model observations without another network request."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engine_bom.dimension_chains import inspect_chains
from engine_bom.providers import ProviderResponse
from scripts.test_tolerance_inspection import score


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('run',type=Path)
    args=parser.parse_args()
    records=json.loads((args.run/'report.json').read_text(encoding='utf-8'))
    expected=json.loads((args.run/'inputs'/'expected.json').read_text(encoding='utf-8'))
    class ReplayProvider:
        def __init__(self,calls):
            self.calls=[c for c in calls if 'TASK:DIMENSION_CHAINS' in c['task']]
        def analyze(self,images,prompt):
            if 'TASK:DIMENSION_CHAINS' not in prompt or not self.calls:
                raise AssertionError('No saved reply for this stage; no network request allowed')
            call=self.calls.pop(0)
            return ProviderResponse(call['raw_text'],call['model'])
    results=[]
    for row in records:
        saved=json.loads((args.run/(row['case']+'.json')).read_text(encoding='utf-8'))
        report=inspect_chains(ReplayProvider(saved['calls']),[object()],saved['dimensions']['dimensions'])
        passed=score(report,expected['cases'][row['case']])
        results.append({'case':row['case'],'passed':passed,'status':report['tolerance_status']})
    print(json.dumps(results,ensure_ascii=False,indent=2))
    (args.run/'replay.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in results):sys.exit(1)


if __name__=='__main__':main()
