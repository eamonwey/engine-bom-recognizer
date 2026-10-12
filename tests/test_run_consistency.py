import copy,json,tempfile,unittest
from pathlib import Path
from engine_bom.run_consistency import compare_runs,snapshot


class RunConsistencyTests(unittest.TestCase):
    def result(self):
        return dict(source_sha256='a'*64,bom={'components':[{'item_no':1,'name_zh':'盖','quantity':1}],
            'assembly':{'nodes':[{'id':'base','parent_id':None,'component_index':0}]}},dimensions=[],issues=[])

    def test_no_same_bytes_reference_does_not_claim_stability(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(compare_runs(self.result(),folder)['status'],'no_reference')

    def test_generated_ids_and_row_order_are_not_part_identity(self):
        a=self.result();b=copy.deepcopy(a);b['bom']['assembly']['nodes'][0]['id']='random'
        self.assertEqual(snapshot(a),snapshot(b))

    def test_differences_are_reported_without_overwriting_new_predictions(self):
        a=self.result();b=copy.deepcopy(a);b['bom']['components'][0]['quantity']=2
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'old.json').write_text(json.dumps({'result':a}),encoding='utf8')
            report=compare_runs(b,folder)
        self.assertEqual(report['status'],'disagreement');self.assertEqual(report['references'][0]['different_fields'],['bom'])
        self.assertEqual(b['bom']['components'][0]['quantity'],2)

    def test_bad_history_other_hash_and_current_job_are_ignored(self):
        a=self.result()
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'bad.json').write_text('broken',encoding='utf8')
            Path(folder,'malformed.json').write_text('[]',encoding='utf8')
            Path(folder,'self.json').write_text(json.dumps({'result':a}),encoding='utf8')
            Path(folder,'other.json').write_text(json.dumps({'result':dict(a,source_sha256='b'*64)}),encoding='utf8')
            self.assertEqual(compare_runs(a,folder,exclude_job='self')['status'],'no_reference')


if __name__=='__main__':unittest.main()
