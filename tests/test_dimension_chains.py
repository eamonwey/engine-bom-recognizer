import copy
import json
import unittest
from engine_bom.dimension_chains import validate_chains
from engine_bom.hybrid_inspection import merge_findings, inspect, ground_coverage, gate_visual_chains
from engine_bom.providers import ProviderResponse


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.dims = [{'value':v,'view':'主视图','unit':'mm','source_page':1} for v in ['100','40','50']]
        for dim, points in zip(self.dims, [[[.1,.7],[.9,.7]], [[.1,.6],[.5,.6]], [[.5,.6],[.9,.6]]]):
            dim['linear_geometry'] = {'axis':'horizontal', 'dimension_line':points,
                                      'evidence':'箭头与尺寸界线交点'}
        self.data = {'status':'checked','evidence':'检查主视图总长及下方串联尺寸', 'chains':[
            {'total_index':0,'start':'A','end':'C','source_page':1,'view':'主视图','evidence':'A-B-C连续，共享总长端点',
             'segments':[{'dimension_index':1,'start':'A','end':'B'},{'dimension_index':2,'start':'B','end':'C'}]}]}

    def validate(self):
        return validate_chains(json.dumps(self.data),self.dims,1)

    def test_conflict(self):
        result, errors = self.validate()
        self.assertFalse(errors)
        self.assertEqual(len(result['issues']),1)
        self.assertIn('90',result['issues'][0]['message'])

    def test_balanced_and_units(self):
        self.dims[0]['value']='90'
        self.dims[1].update(value='4',unit='cm')
        result, errors=self.validate()
        self.assertFalse(errors)
        self.assertEqual(result['issues'],[])

    def test_historical_hallucinated_chain_without_geometry_is_rejected(self):
        # Production incident: VLM fabricated Left_End -> Mid -> Right_End.
        for dim, value in zip(self.dims, ['172', '49', '100']):
            dim['value'] = value
            dim.pop('linear_geometry')
        result, errors = self.validate()
        self.assertTrue(errors)
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['issues'], [])

    def test_vertical_100_cannot_be_added_to_horizontal_49(self):
        for dim, value in zip(self.dims, ['172', '49', '100']):
            dim['value'] = value
        self.dims[2]['linear_geometry'] = {
            'axis':'vertical', 'dimension_line':[[.46,.07],[.46,.33]], 'evidence':'右侧竖直尺寸线'}
        result, errors = self.validate()
        self.assertTrue(any('水平与竖直' in error for error in errors))
        self.assertEqual(result['issues'], [])

    def test_endpoint_names_cannot_hide_gaps_overlap_or_wrong_outer_endpoints(self):
        for points in ([[.55,.6],[.9,.6]], [[.45,.6],[.9,.6]],
                       [[.5,.6],[.8,.6]], [[.5,.6],[.95,.6]]):
            self.setUp()
            self.dims[2]['linear_geometry']['dimension_line'] = points
            result, errors = self.validate()
            self.assertTrue(errors)
            self.assertEqual(result['issues'], [])

    def test_invalid_or_falsely_declared_direction(self):
        for points in ([[.5,.2],[.5,.8]], [[.5,.2],[.5,.2]],
                       [[float('nan'),.2],[.9,.2]], [[True,.2],[.9,.2]],
                       [[-.1,.2],[.9,.2]]):
            self.setUp()
            self.dims[2]['linear_geometry']['dimension_line'] = points
            result, errors = self.validate()
            self.assertTrue(errors)
            self.assertEqual(result['issues'], [])

    def test_vertical_valid_chain_and_small_coordinate_noise(self):
        for dim in self.dims:
            geo = dim['linear_geometry']
            geo['axis'] = 'vertical'
            geo['dimension_line'] = [[y,x] for x,y in geo['dimension_line']]
        self.dims[2]['linear_geometry']['dimension_line'][0][1] += .001
        result, errors = self.validate()
        self.assertFalse(errors)
        self.assertEqual(len(result['issues']), 1)

    def test_free_text_visual_review_cannot_reintroduce_rejected_chain(self):
        for kind in (None, 'dimension_chain', 'cross_view'):
            issue = {'err_id':'ERR-01', 'check_kind':kind,
                     'message':'水平尺寸链49+100与172矛盾', 'evidence':'分段相接'}
            allowed, uncertain = gate_visual_chains([issue], [])
            self.assertEqual(allowed, [])
            self.assertEqual(uncertain[0]['status'], 'unverified')

    def test_cross_view_observation_and_other_errors_are_preserved(self):
        issues = [{'err_id':'ERR-01', 'check_kind':'cross_view', 'message':'同一孔径在两视图读数不同'},
                  {'err_id':'ERR-08', 'message':'日期为空'}]
        allowed,unknown=gate_visual_chains(issues, [])
        self.assertEqual(allowed,[issues[1]])
        self.assertEqual(unknown[0]['message'],issues[0]['message'])
        self.assertEqual(unknown[0]['status'],'unverified')

    def test_visual_prose_cannot_overwrite_validated_chain(self):
        issue = {'err_id':'ERR-01', 'related_rule_id':'chain-0', 'message':'错误的复述'}
        self.assertEqual(gate_visual_chains([issue], [{'finding_id':'chain-0'}]), ([], []))

    def test_hybrid_pipeline_rejects_repeated_model_hallucination(self):
        original = copy.deepcopy(self.data)
        dims = copy.deepcopy(self.dims)
        for dim in dims:
            dim.pop('linear_geometry')

        class Provider:
            name = 'test'

            def analyze(self, images, prompt):
                if prompt.startswith('TASK:DIMENSION_CHAINS'):
                    return ProviderResponse(json.dumps(original), 'test')
                return ProviderResponse(json.dumps({
                    'issues':[{'err_id':'ERR-01', 'check_kind':'dimension_chain',
                               'message':'尺寸链矛盾', 'evidence':'40+50不等于100', 'source_page':1}],
                    'coverage':{'ERR-%02d' % n:{'status':'checked','evidence':'模型称已检查'} for n in range(1,11)},
                }), 'test')

        report = inspect(Provider(), [object()], {}, [], dims, [], {'max_attempts':1})
        self.assertEqual(report['dimension_chains']['status'], 'needs_review')
        self.assertFalse(any(i['err_id'] == 'ERR-01' for i in report['issues']))
        self.assertEqual(len(report['unverified_findings']), 1)
        self.assertEqual(report['checklist']['ERR-01']['status'], 'uncertain')

    def test_reject_geometry_and_input_errors(self):
        for mutation in ('gap','repeat','view','page','tolerance','unit'):
            self.setUp()
            if mutation=='gap': self.data['chains'][0]['segments'][1]['start']='D'
            if mutation=='repeat': self.data['chains'][0]['segments'][1]['dimension_index']=1
            if mutation=='view': self.dims[1]['view']='俯视图'
            if mutation=='page': self.dims[1]['source_page']=2
            if mutation=='tolerance': self.dims[1]['value']='40±1'
            if mutation=='unit': self.dims[1]['unit']='inch'
            result,errors=self.validate()
            self.assertTrue(errors,mutation)
            self.assertEqual(result['issues'],[],mutation)

    def test_merge_preserves_sources_and_severity(self):
        rules=[{'finding_id':'rule-0','err_id':'ERR-08','message':'date missing','severity':'高'}]
        visual=[{'related_rule_id':'rule-0','err_id':'ERR-08','message':'日期为空','evidence':'右下标题栏','severity':'中'}]
        result=merge_findings(rules,visual)
        self.assertEqual(len(result),1)
        self.assertEqual(len(result[0]['sources']),2)
        self.assertEqual(result[0]['severity'],'高')
        self.assertEqual(rules[0]['message'],'date missing')
        visual[0]['err_id']='ERR-01'
        self.assertEqual(len(merge_findings(rules,visual)),2)

    def test_missing_coverage_retries(self):
        class Provider:
            name='test'
            count=0
            def analyze(self,images,prompt):
                self.count+=1
                data={'issues':[]}
                if self.count>1:
                    data['coverage']={'ERR-%02d'%n:{'status':'uncertain','evidence':'图面证据不足'} for n in range(1,11)}
                return ProviderResponse(json.dumps(data),'test')
        provider=Provider()
        result=inspect(provider,[],{},[],[],[],{'max_attempts':2})
        self.assertEqual(provider.count,2)
        self.assertEqual(result['visual_status'],'validated')
        self.assertEqual(len(result['checklist']),10)

    def test_semantic_merge_without_model_ids(self):
        rules=[{'finding_id':'rule-0','err_id':'ERR-08','message':'标题栏必填字段缺失: date','location':'标题栏'},
               {'finding_id':'rule-1','err_id':'ERR-08','message':'明细栏第 4 行数量非正数','location':'明细栏第 4 行'}]
        visual=[{'err_id':'ERR-08','message':'日期为空','location':'标题栏'},
                {'err_id':'ERR-08','message':'数量为“0”，与4件冲突','location':'明细栏第4行'},
                {'err_id':'ERR-08','message':'数量为“0”','location':'明细栏第5行'}]
        result=merge_findings(rules,visual)
        self.assertEqual(len(result),3)
        self.assertEqual([len(r['sources']) for r in result],[2,2,1])

    def test_unverified_compliance_is_not_a_pass(self):
        raw={'ERR-03':{'status':'checked','evidence':'符合一般制图规范'},
             'ERR-06':{'status':'not_applicable','evidence':'所有材料均为45'}}
        result=ground_coverage(raw,[],{'issues':[]})
        for item in result.values():
            self.assertEqual(item['status'],'uncertain')
            self.assertNotIn('符合',item['evidence'])
            self.assertEqual(item['basis'],'unverified_model')
        self.assertEqual(result['ERR-03']['model_observation'],raw['ERR-03'])

    def test_computed_findings_do_not_imply_complete_coverage(self):
        result=ground_coverage({'ERR-08':{'status':'checked','evidence':'全合格'}},
            [{'err_id':'ERR-08','message':'日期缺失'}],{'issues':[]})
        self.assertEqual(result['ERR-08']['status'],'checked')
        self.assertIn('不代表',result['ERR-08']['evidence'])

if __name__=='__main__': unittest.main()
