import copy
import itertools
import json
import random
import unittest
from decimal import Decimal

from engine_bom.dimension_chains import inspect_chains, validate_chains
from engine_bom.engineering_checks import parse_size, run_engineering_checks
from engine_bom.hybrid_inspection import inspect, gate_visual_chains, merge_findings
from engine_bom.providers import ProviderError, ProviderResponse
from engine_bom.tolerance_chains import calculate_chain, validate_tolerance_chains, discover_tolerance_chains


def gap_fixture(requirement='10±0.3'):
    dims = []
    for tag, value, ends in [('装配间隙S',requirement,[.82,.9]),('内件长度B','90±0.1',[.1,.82]),('腔体长度L','100±0.1',[.1,.9])]:
        dims.append({'tag':tag,'value':value,'unit':'mm','view':'主视图','source_page':1,
            'linear_geometry':{'axis':'horizontal','dimension_line':[[ends[0],.5],[ends[1],.5]],'evidence':'尺寸线两端箭头与界线相接'},
            'dimension_role':'component','role_evidence':''})
    dims[0].update(dimension_role='closing_requirement',role_evidence='装配后间隙S要求 '+requirement+' mm')
    chain = {'closing_index':0,'start':'B','end':'C','source_page':1,'view':'主视图','evidence':'B到C间隙，B到A反向内件，A到C正向腔体',
        'terms':[{'dimension_index':1,'coefficient':-1,'start':'B','end':'A'},
                 {'dimension_index':2,'coefficient':1,'start':'A','end':'C'}]}
    data = {'status':'checked','evidence':'主视图装配界面有明确功能要求','chains':[],
        'tolerance_status':'checked','tolerance_evidence':'S=L-B，组成环均有明确±公差','tolerance_chains':[chain]}
    return dims, chain, data


class ToleranceChainTests(unittest.TestCase):
    def setUp(self):
        self.dims,self.chain,self.data = gap_fixture()

    def run_chain(self):
        return calculate_chain(self.chain,self.dims,1)

    def reject(self):
        result,issues,errors=validate_tolerance_chains([self.chain],self.dims,1)
        self.assertTrue(errors)
        self.assertEqual(result,[])
        self.assertEqual(issues,[])

    def test_clearance_within(self):
        r=self.run_chain()
        self.assertEqual(Decimal(r['minimum_mm']),Decimal('9.8'))
        self.assertEqual(Decimal(r['maximum_mm']),Decimal('10.2'))
        self.assertEqual(Decimal(r['nominal_mm']),Decimal('10'))
        self.assertEqual(r['conformance'],'within_limits')
        self.assertEqual(r['terms'][0]['role'],'减环')
        self.assertTrue(r['needs_review'])
        self.assertEqual(r['compliance'],'not_certified')

    def test_partial_exceed_is_not_every_part_failure(self):
        self.dims[0]['value']='10±0.1'
        results,issues,errors=validate_tolerance_chains([self.chain],self.dims,1)
        self.assertFalse(errors)
        self.assertEqual(results[0]['conformance'],'may_exceed_limits')
        self.assertEqual(issues[0]['err_id'],'ERR-01')
        self.assertEqual(issues[0]['rule_id'],'tolerance-chain-worst-case')
        self.assertIn('可能超差',issues[0]['message'])
        self.assertIn('不代表每件',issues[0]['suggestion'])

    def test_disjoint_high_and_low(self):
        for value in ('8±0.1','12±0.1'):
            self.dims[0]['value']=value
            self.assertEqual(self.run_chain()['conformance'],'outside_limits')

    def test_exact_bounds_are_inclusive(self):
        self.dims[0]['value']='10±0.2'
        r=self.run_chain()
        self.assertEqual(r['conformance'],'within_limits')
        self.assertTrue(r['at_boundary'])
        self.assertEqual(Decimal(r['lower_margin_mm']),0)

    def test_touch_only_not_contained(self):
        self.dims[0]['value']='9.7±0.1'
        self.assertEqual(self.run_chain()['conformance'],'may_exceed_limits')

    def test_asymmetric_deviations_and_negative_reversal(self):
        self.dims[1]['value']='90 +0.15/-0.05'
        self.dims[2]['value']='100 +0.2/-0.1'
        r=self.run_chain()
        self.assertEqual(Decimal(r['minimum_mm']),Decimal('9.75'))
        self.assertEqual(Decimal(r['maximum_mm']),Decimal('10.25'))
        self.assertEqual(Decimal(r['terms'][0]['contribution_min_mm']),Decimal('-90.15'))

    def test_both_negative_deviations(self):
        self.dims[1]['value']='90 -0.01/-0.03'
        self.dims[2]['value']='100 -0.02/-0.04'
        r=self.run_chain()
        self.assertEqual(Decimal(r['minimum_mm']),Decimal('9.97'))
        self.assertEqual(Decimal(r['maximum_mm']),Decimal('10.01'))

    def test_limits_without_nominal_do_not_invent_nominal(self):
        self.dims[1]['value']='90.1/89.9'
        self.dims[0]['value']='10.3/9.7'
        r=self.run_chain()
        self.assertIsNone(r['nominal_mm'])
        self.assertEqual(r['conformance'],'within_limits')

    def test_mixed_known_units_are_normalized(self):
        self.dims[2].update(value='10±0.01',unit='cm')
        self.assertEqual(Decimal(self.run_chain()['minimum_mm']),Decimal('9.8'))

    def test_micrometres_and_suffix(self):
        self.dims[0].update(value='10000±300um',unit='')
        self.assertEqual(self.run_chain()['conformance'],'within_limits')

    def test_unknown_units(self):
        self.dims[1]['unit']=''
        self.reject()

    def test_conflicting_units(self):
        self.dims[1]['value']='90±0.1cm'
        self.reject()

    def test_unsupported_units(self):
        self.dims[1]['unit']='inch'
        self.reject()

    def test_missing_tolerance_is_unknown_not_zero(self):
        self.dims[1]['value']='90'
        self.reject()

    def test_explicit_zero_tolerance_is_not_unstated(self):
        self.dims[1]['value']='90±0'
        self.assertEqual(Decimal(self.run_chain()['minimum_mm']),Decimal('9.9'))

    def test_general_tolerance_cannot_be_invented(self):
        self.dims[1]['value']='90（未注公差按m级）'
        self.reject()

    def test_invalid_size_kinds_and_bands(self):
        for value in ('Φ90±0.1','R90±0.1','90H7','90°±0.1'):
            self.setUp();self.dims[1]['value']=value;self.reject()

    def test_inverted_tolerance_negative_magnitude_or_limits(self):
        for value in ('90±-0.1','90 -0.3/-0.1','89.9/90.1'):
            self.setUp();self.dims[1]['value']=value;self.reject()

    def test_nonphysical_component(self):
        for value in ('0±0.1','-1±0.1','0.1±0.2'):
            self.setUp();self.dims[1]['value']=value;self.reject()

    def test_signed_closing_requirement(self):
        self.dims[2]['value']='89.9±0.01'
        self.dims[1]['value']='90±0.01'
        self.dims[0]['value']='-0.1±0.05'
        r=self.run_chain()
        self.assertEqual(Decimal(r['minimum_mm']),Decimal('-.12'))
        self.assertEqual(r['conformance'],'within_limits')
        with self.assertRaises(ValueError):parse_size('-0.1±0.05')

    def test_zero_centered_closing_requirement(self):
        self.dims[2]['value']='90±0.01'
        self.dims[0]['value']='0±0.2'
        self.assertEqual(self.run_chain()['conformance'],'within_limits')

    def test_signed_requirement_not_reported_as_negative_physical_size(self):
        self.dims[0]['value']='-0.1±0.05'
        r=run_engineering_checks({},self.dims,[],{}, {})
        self.assertFalse(any(i['rule_id']=='tolerance-format' for i in r['issues']))
        self.dims[0]['dimension_role']='component'
        r=run_engineering_checks({},self.dims,[],{}, {})
        self.assertTrue(any(i['rule_id']=='tolerance-format' for i in r['issues']))

    def test_closing_requirement_cannot_be_an_arbitrary_dimension(self):
        self.dims[0]['dimension_role']='component';self.reject()

    def test_closing_requirement_needs_original_evidence(self):
        self.dims[0]['role_evidence']='';self.reject()

    def test_proposed_path_cannot_mix_explicit_assembly_scopes(self):
        for d in self.dims:d['assembly_scope']='装配A'
        self.dims[1]['assembly_scope']='装配B'
        self.reject()

    def test_proposed_path_cannot_reuse_another_functional_requirement(self):
        self.dims[1]['dimension_role']='closing_requirement'
        self.reject()

    def test_no_mutation_of_source_or_proposal(self):
        original=copy.deepcopy((self.dims,self.chain))
        self.run_chain()
        self.assertEqual((self.dims,self.chain),original)

    def test_wrong_sign_cannot_force_a_good_answer(self):
        self.chain['terms'][0]['coefficient']=1;self.reject()

    def test_wrong_sign_types(self):
        for sign in (True,False,1.0,'-1',0,2,None):
            self.setUp();self.chain['terms'][0]['coefficient']=sign;self.reject()

    def test_invalid_index_types_and_bounds(self):
        for idx in (True,1.0,-1,3,'1',None):
            self.setUp();self.chain['terms'][0]['dimension_index']=idx;self.reject()

    def test_duplicate_dimension_or_closing_in_terms(self):
        for idx in (0,2):
            self.setUp();self.chain['terms'][0]['dimension_index']=idx;self.reject()

    def test_cross_view_and_cross_page(self):
        self.dims[1]['view']='左视图';self.reject()
        self.setUp();self.dims[1]['source_page']=2;self.reject()

    def test_missing_and_boolean_page(self):
        for page in (None,True,'1',0):
            self.setUp();self.dims[1]['source_page']=page;self.reject()

    def test_invalid_chain_page(self):
        for page in (True,0,2,'1'):
            self.setUp();self.chain['source_page']=page;self.reject()

    def test_missing_geometry_or_evidence(self):
        self.dims[1]['linear_geometry']=None;self.reject()
        self.setUp();self.dims[1]['linear_geometry']['evidence']=False;self.reject()

    def test_cross_axis(self):
        self.dims[1]['linear_geometry'].update(axis='vertical',dimension_line=[[.5,.1],[.5,.82]])
        self.reject()

    def test_gap_in_endpoint_path(self):
        self.dims[1]['linear_geometry']['dimension_line'][0][0]=.15;self.reject()

    def test_wrong_closing_endpoint(self):
        self.dims[0]['linear_geometry']['dimension_line'][1][0]=.95;self.reject()

    def test_aliases_cannot_hide_cycle(self):
        self.chain['terms'][0]['end']='C';self.reject()

    def test_logical_gap(self):
        self.chain['terms'][1]['start']='Z';self.reject()

    def test_vertical_chain(self):
        for d in self.dims:
            g=d['linear_geometry'];g['axis']='vertical';g['dimension_line']=[[y,x] for x,y in g['dimension_line']]
        self.assertEqual(self.run_chain()['conformance'],'within_limits')

    def test_bad_values_are_rejected_without_crash(self):
        for value in (True,90,None,'NaN±.1','Infinity±.1','1e4±.1','9'*170+'±.1'):
            self.setUp();self.dims[1]['value']=value;self.reject()

    def test_multiple_decreasing_links(self):
        self.dims[1]['value']='50±0.1'
        self.dims[1]['linear_geometry']['dimension_line']=[[.42,.5],[.82,.5]]
        self.dims.append({'value':'40±0.1','tag':'左件A','unit':'mm','view':'主视图','source_page':1,'dimension_role':'component',
            'linear_geometry':{'axis':'horizontal','dimension_line':[[.1,.5],[.42,.5]],'evidence':'左件两端'}})
        self.chain['terms'][0]['end']='M'
        self.chain['terms'].insert(1,{'dimension_index':3,'coefficient':-1,'start':'M','end':'A'})
        r=self.run_chain()
        self.assertEqual(Decimal(r['minimum_mm']),Decimal('9.7'))
        self.assertTrue(r['at_boundary'])

    def test_all_increasing_links(self):
        self.dims[0]['linear_geometry']['dimension_line']=[[.1,.5],[.9,.5]]
        self.dims[0]['value']='100±0.3'
        self.dims[1]['value']='40±0.1'
        self.dims[1]['linear_geometry']['dimension_line']=[[.1,.5],[.42,.5]]
        self.dims[2]['value']='60±0.1'
        self.dims[2]['linear_geometry']['dimension_line']=[[.42,.5],[.9,.5]]
        self.chain.update(start='A',end='C',terms=[
            {'dimension_index':1,'coefficient':1,'start':'A','end':'B'},
            {'dimension_index':2,'coefficient':1,'start':'B','end':'C'}])
        self.assertEqual(self.run_chain()['conformance'],'within_limits')

    def test_extreme_cancellation_precision(self):
        self.dims[2]['value']='999999999999±0.000000000001'
        self.dims[1]['value']='999999999989±0.000000000001'
        r=self.run_chain()
        self.assertEqual(Decimal(r['minimum_mm']),Decimal('9.999999999998'))

    def test_short_or_oversize_path(self):
        self.chain['terms']=[];self.reject()
        self.setUp();self.chain['terms']*=51;self.reject()

    def test_duplicate_chain_rejected(self):
        r,i,e=validate_tolerance_chains([self.chain,copy.deepcopy(self.chain)],self.dims,1)
        self.assertTrue(e);self.assertFalse(r);self.assertFalse(i)

    def test_malformed_chains_rejected(self):
        for chain in ([],None,True,{}, {'terms':[None,None]}):
            r,i,e=validate_tolerance_chains([chain],self.dims,1)
            self.assertTrue(e);self.assertFalse(i)

    def test_atomic_validation_keeps_no_partial_issues(self):
        self.dims[0]['value']='10±0.1'
        bad=copy.deepcopy(self.chain);bad['terms'][0]['coefficient']=2
        r,i,e=validate_tolerance_chains([self.chain,bad],self.dims,1)
        self.assertTrue(e);self.assertEqual(i,[]);self.assertEqual(r,[])

    def test_new_report_integrates_with_ordinary_chains(self):
        self.dims[0]['value']='10±0.1'
        result,errors=validate_chains(json.dumps(self.data),self.dims,1,require_tolerance=True)
        self.assertFalse(errors)
        self.assertEqual(len(result['tolerance_chains']),1)
        self.assertEqual(len(result['issues']),1)

    def test_missing_new_stage_not_a_clean_result(self):
        for key in ('tolerance_chains','tolerance_status','tolerance_evidence'):
            data=copy.deepcopy(self.data);data.pop(key)
            r,e=validate_chains(json.dumps(data),self.dims,1,require_tolerance=True)
            self.assertTrue(e);self.assertEqual(r['issues'],[])

    def test_uncertain_cannot_include_computed_chain(self):
        self.data['tolerance_status']='uncertain'
        r,e=validate_chains(json.dumps(self.data),self.dims,1)
        self.assertTrue(e);self.assertEqual(r['issues'],[])

    def test_explicit_uncertain_reason_preserved(self):
        self.data.update(tolerance_status='uncertain',tolerance_evidence='图面未注组成环公差',tolerance_chains=[])
        r,e=validate_chains(json.dumps(self.data),self.dims,1,require_tolerance=True)
        self.assertFalse(e);self.assertEqual(r['tolerance_status'],'uncertain')
        self.assertFalse(r['tolerance_chains'])

    def test_agent_retry_corrects_path_but_does_not_change_original_dimensions(self):
        data=copy.deepcopy(self.data)
        class Provider:
            count=0
            def analyze(self,images,prompt):
                self.count+=1
                reply=copy.deepcopy(data)
                if self.count==1:reply['tolerance_chains'][0]['terms'][0]['coefficient']=1
                return ProviderResponse(json.dumps(reply),'test')
        p=Provider();r=inspect_chains(p,[object()],self.dims,2)
        self.assertEqual(p.count,2);self.assertEqual(r['status'],'checked')
        self.assertEqual(self.dims[1]['value'],'90±0.1')

    def test_provider_error_retains_events(self):
        class Provider:
            def analyze(self,*args):raise ProviderError('quota exhausted')
        r=inspect_chains(Provider(),[object()],self.dims)
        self.assertEqual(r['tolerance_status'],'provider_failed')
        self.assertEqual(r['events'][0]['action'],'provider_error')

    def test_hybrid_pipeline_computes_candidate_and_blocks_free_prose(self):
        self.dims[0]['value']='10±0.1'
        data=copy.deepcopy(self.data)
        class Provider:
            name='test'
            def analyze(self,images,prompt):
                if prompt.startswith('TASK:DIMENSION_CHAINS'):return ProviderResponse(json.dumps(data),'test')
                return ProviderResponse(json.dumps({'issues':[{'err_id':'ERR-01','check_kind':'dimension_chain','message':'尺寸链应改为99','evidence':'猜测','source_page':1}],
                    'coverage':{'ERR-%02d'%n:{'status':'uncertain','evidence':'尚需复核'} for n in range(1,11)}}),'test')
        r=inspect(Provider(),[object()],{},[],self.dims,[],{'max_attempts':1})
        findings=[i for i in r['issues'] if i.get('rule_id')=='tolerance-chain-worst-case']
        self.assertEqual(len(findings),1)
        self.assertEqual(findings[0]['finding_id'],'chain-0')
        self.assertTrue(r['unverified_findings'])
        self.assertIn('9.8',findings[0]['message'])

    def test_chain_calculation_cannot_be_overwritten_on_merge(self):
        self.dims[0]['value']='10±0.1'
        _,issues,_=validate_tolerance_chains([self.chain],self.dims,1)
        issues[0]['finding_id']='chain-0'
        result=merge_findings(issues,[{'err_id':'ERR-01','related_rule_id':'chain-0','message':'改为99','evidence':'无依据','source_page':2}])
        self.assertEqual(result[0]['message'],issues[0]['message'])
        self.assertEqual(result[0]['source_page'],1)
        self.assertEqual(gate_visual_chains([{'err_id':'ERR-01','related_rule_id':'chain-0'}],issues),( [], []))

    def test_random_asymmetric_intervals_against_endpoint_enumeration(self):
        rng=random.Random(20261011)
        for _ in range(100):
            lower1,upper1=(Decimal(rng.randrange(0,25))/100 for _ in range(2))
            lower2,upper2=(Decimal(rng.randrange(0,25))/100 for _ in range(2))
            self.dims[1]['value']='90 +%s/-%s'%(upper1,lower1)
            self.dims[2]['value']='100 +%s/-%s'%(upper2,lower2)
            r=self.run_chain()
            corners=[a-b for a,b in itertools.product((100-lower2,100+upper2),(90-lower1,90+upper1))]
            self.assertEqual(Decimal(r['minimum_mm']),min(corners))
            self.assertEqual(Decimal(r['maximum_mm']),max(corners))

    def scoped(self):
        for d in self.dims:d['assembly_scope']='装配A'

    def test_endpoint_graph_unique_signed_path_without_model(self):
        self.scoped()
        r=discover_tolerance_chains(self.dims,1)
        self.assertEqual(r['tolerance_status'],'checked')
        self.assertEqual(Decimal(r['tolerance_chains'][0]['minimum_mm']),Decimal('9.8'))
        self.assertEqual(r['tolerance_chains'][0]['path_source'],'deterministic_endpoint_graph')
        class Provider:
            def analyze(self,*args):raise AssertionError('Unique graph needs no second VLM path proposal')
        self.assertEqual(inspect_chains(Provider(),[object()],self.dims)['tolerance_status'],'checked')

    def test_endpoint_graph_missing_tolerance_keeps_unknown(self):
        self.scoped();self.dims[1]['value']='90'
        r=discover_tolerance_chains(self.dims,1)
        self.assertEqual(r['tolerance_status'],'uncertain')
        self.assertIn('未注公差',r['unresolved_chains'][0]['reason'])
        self.assertFalse(r['issues'])

    def test_endpoint_graph_ambiguous_paths_never_chooses_by_values(self):
        self.scoped()
        duplicate=copy.deepcopy(self.dims[1]);duplicate['value']='80±0.1'
        self.dims.append(duplicate)
        r=discover_tolerance_chains(self.dims,1)
        self.assertIn('多个端点路径',r['unresolved_chains'][0]['reason'])
        self.assertFalse(r['tolerance_chains'])

    def test_endpoint_graph_one_link_alternative_is_also_ambiguity(self):
        self.scoped()
        duplicate=copy.deepcopy(self.dims[0]);duplicate.update(dimension_role='component',value='10±0.1')
        self.dims.append(duplicate)
        r=discover_tolerance_chains(self.dims,1)
        self.assertIn('多个端点路径',r['unresolved_chains'][0]['reason'])

    def test_endpoint_graph_different_assemblies_not_joined(self):
        self.scoped();self.dims[1]['assembly_scope']='装配B'
        r=discover_tolerance_chains(self.dims,1)
        self.assertEqual(r['tolerance_status'],'uncertain')
        self.assertFalse(r['tolerance_chains'])

    def test_endpoint_graph_unknown_scope_needs_explicit_observation(self):
        self.assertEqual(discover_tolerance_chains(self.dims,1)['resolution'],'needs_model')

    def test_endpoint_graph_disconnected_requirement(self):
        self.scoped();self.dims[0]['linear_geometry']['dimension_line']=[[.92,.5],[.97,.5]]
        r=discover_tolerance_chains(self.dims,1)
        self.assertEqual(r['tolerance_status'],'uncertain')
        self.assertFalse(r['issues'])

    def test_endpoint_graph_invalid_geometry_and_empty_input(self):
        self.scoped();self.dims[0]['linear_geometry']=None
        self.assertTrue(discover_tolerance_chains(self.dims,1)['unresolved_chains'])
        self.assertEqual(discover_tolerance_chains([],1)['resolution'],'needs_model')

    def test_endpoint_graph_does_not_snap_transitive_endpoint_gap(self):
        self.scoped()
        self.dims[1]['linear_geometry']['dimension_line'][1][0]=.826
        extra=copy.deepcopy(self.dims[1]);extra['linear_geometry']['dimension_line']=[[.823,.5],[.95,.5]]
        self.dims.append(extra)
        self.assertFalse(discover_tolerance_chains(self.dims,1)['tolerance_chains'])

    def test_endpoint_graph_preserves_computation_on_unrelated_provider_failure(self):
        self.scoped();self.dims[0]['value']='10±0.1'
        self.dims.extend([{'value':str(x),'unit':'mm'} for x in (1,2,3)])
        class Provider:
            def analyze(self,*args):raise ProviderError('quota exhausted')
        r=inspect_chains(Provider(),[object()],self.dims)
        self.assertEqual(r['status'],'provider_failed')
        self.assertEqual(r['tolerance_status'],'checked')
        self.assertEqual(len(r['issues']),1)


if __name__=='__main__':unittest.main()
