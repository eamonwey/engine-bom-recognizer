import copy
import json
import os
import tempfile
import unittest
from decimal import Decimal
from PIL import Image
from engine_bom.engineering_checks import (GROUPS, parse_size, run_engineering_checks,
    validate_observations, validate_engineering_config, inspection_config)
from engine_bom.enterprise import validate_profile
from engine_bom.hybrid_inspection import inspect, gate_visual_engineering, merge_findings
from engine_bom.providers import ProviderResponse
from engine_bom.titleblock import extract_titleblock
from engine_bom.drawing_layout import titleblock_page_numbers, titleblock_images


def observation(ident='o1', **extra):
    return dict(id=ident, source_page=1, bbox=[.1,.1,.2,.2], location='主视图',
                evidence='原图标注', readable=True, **extra)


def facts(**extra):
    result = {key: [] for key in GROUPS}
    result.update(extra)
    return result


def dim(value, **extra):
    result = dict(value=value, source_page=1, unit='mm', view='主视图')
    result.update(extra)
    return result


class SizeTests(unittest.TestCase):
    def test_symmetric(self):
        size = parse_size('Φ20±0.02')
        self.assertEqual((size['lower'],size['upper']), (Decimal('19.98'),Decimal('20.02')))
    def test_asymmetric(self):
        size = parse_size('20 +0.02 / -0.01')
        self.assertEqual((size['lower'],size['upper']), (Decimal('19.99'),Decimal('20.02')))
    def test_both_negative_deviations(self):
        self.assertEqual(parse_size('20 -0.01/-0.03')['upper'], Decimal('19.99'))
    def test_limits(self):
        self.assertEqual(parse_size('20.02/19.98')['nominal'], None)
        self.assertEqual(parse_size('20.02/19.98')['lower'], Decimal('19.98'))
    def test_units(self):
        self.assertEqual(parse_size('2±.01cm','cm')['lower'], Decimal('19.9'))
    def test_no_units_not_invented(self):
        self.assertFalse(parse_size('20±.1','')['unit_known'])
    def test_band_has_no_invented_interval(self):
        self.assertIsNone(parse_size('20H7')['upper'])
    def test_bad_annotations(self):
        for value in ('20±-0.1','20+0.01/+0.02','19.98/20.02','20H99','20OO7','20Js7','NaN','Infinity','-20','20±30','20°'):
            with self.subTest(value=value), self.assertRaises(ValueError): parse_size(value)
    def test_conflicting_units(self):
        with self.assertRaises(ValueError): parse_size('20cm','mm')


class EngineeringTests(unittest.TestCase):
    def run_checks(self, data=None, dims=None, comps=None, title=None, config=None, metadata=None):
        return run_engineering_checks(data or facts(), dims or [], comps or [], title or {}, config or {}, metadata)
    def issues(self, report, code):
        return [r for r in report['issues'] if r['err_id']==code]
    def fit(self, hole='20+0.02/0', shaft='20-0.01/-0.03', intended='过盈配合'):
        return self.run_checks(facts(fits=[observation(hole_dimension_index=0,shaft_dimension_index=1,intended_fit=intended)]),[dim(hole),dim(shaft)])
    def test_fit_conflict(self):
        issue = self.issues(self.fit(),'ERR-03')[0]
        self.assertEqual(issue['calculation']['computed_fit'],'clearance')
        self.assertEqual(issue['calculation']['clearance_min_mm'],'0.01')
    def test_clearance_and_interference_and_transition(self):
        for hole,shaft,expected in [('20+.02/0','20-.01/-.03','间隙配合'),
                                    ('20+.01/0','20+.04/+.02','过盈配合'),
                                    ('20+.02/0','20+.01/-.01','过渡配合')]:
            with self.subTest(expected=expected): self.assertEqual(self.issues(self.fit(hole,shaft,expected),'ERR-03'),[])
    def test_unknown_intention_not_guessed(self):
        self.assertEqual(self.issues(self.fit(intended=None),'ERR-03'),[])
    def test_zero_boundary(self):
        self.assertEqual(self.issues(self.fit('20+.01/0','20+0/-.01','间隙配合'),'ERR-03'),[])
    def test_unitless_fit_is_uncertain(self):
        report=self.run_checks(facts(fits=[observation(hole_dimension_index=0,shaft_dimension_index=1)]),[dim('20±.01',unit=''),dim('20±.02',unit='')])
        self.assertEqual(self.issues(report,'ERR-03'),[])
        self.assertTrue(any('单位' in r['message'] for r in report['checks']))
    def test_band_role_case(self):
        self.assertTrue(self.issues(self.fit('20h7','20H7'),'ERR-03'))
    def test_no_table_is_unknown(self):
        self.assertEqual(self.issues(self.fit('20H7','20g6'),'ERR-03'),[])
    def test_unannotated_tolerance_is_not_exact(self):
        report=self.fit('20','20','过盈配合')
        self.assertEqual(self.issues(report,'ERR-03'),[])
        self.assertTrue(any('未注公差' in r['message'] for r in report['checks']))
    def test_imported_band_table(self):
        config={'tolerance_bands':[dict(band='H7',min_exclusive=18,max_inclusive=30,lower_mm=0,upper_mm=.021,source='测试设计值，非标准表'),
                                  dict(band='g6',min_exclusive=18,max_inclusive=30,lower_mm=-.02,upper_mm=-.007,source='测试设计值，非标准表')]}
        report=self.run_checks(facts(fits=[observation(hole_dimension_index=0,shaft_dimension_index=1,intended_fit='过盈配合')]),[dim('20H7'),dim('20g6')],config=config)
        self.assertEqual(self.issues(report,'ERR-03')[0]['calculation']['clearance_min_mm'],'0.007')
    def test_tolerance_reversed_and_unsupported(self):
        report=self.run_checks(dims=[dim('20+.01/+.02'),dim('20 ± -0.1'),dim('20H99')])
        self.assertEqual(len(self.issues(report,'ERR-03')),2)
        self.assertTrue(any(r['status']=='uncertain' for r in report['checks']))
    def test_plain_dimensions_not_tolerance_findings(self):
        self.assertEqual(self.run_checks(dims=[dim('20'),dim('30')])['checks'],[])
    def test_negative_frame(self):
        report=self.run_checks(facts(gdt=[observation(cells=['平面度','-0.01'],feature_kind='plane')]))
        self.assertEqual(len(self.issues(report,'ERR-04')),1)
    def test_shape_does_not_need_datum(self):
        for kind in ('平面度','圆度','圆柱度','直线度','位置度'):
            with self.subTest(kind=kind):
                report=self.run_checks(facts(gdt=[observation(cells=[kind,'0.01'],feature_kind='unknown')]))
                self.assertEqual(self.issues(report,'ERR-04'),[])
    def test_orientation_requires_datum(self):
        report=self.run_checks(facts(gdt=[observation(cells=['垂直度','0.01'])]))
        self.assertEqual(len(self.issues(report,'ERR-04')),1)
    def test_blank_datum_cell_is_not_complex_modifier(self):
        report=self.run_checks(facts(gdt=[observation(cells=['垂直度','0.01',''])]))
        self.assertEqual(self.issues(report,'ERR-04')[0]['rule_id'],'gdt-datum')
    def test_datum_present(self):
        report=self.run_checks(facts(gdt=[observation(cells=['垂直度','0.01','A'])],datums=[observation(label='A')]))
        self.assertEqual(self.issues(report,'ERR-04'),[])
    def test_unknown_datum_not_claimed_missing(self):
        report=self.run_checks(facts(gdt=[observation(cells=['垂直度','0.01','A'])]))
        self.assertEqual(self.issues(report,'ERR-04'),[])
        self.assertTrue(any('未在已识别' in r['message'] for r in report['checks']))
    def test_common_datum(self):
        report=self.run_checks(facts(gdt=[observation(cells=['平行度','0.01','A-B'])],datums=[observation('a',label='A'),observation('b',label='B')]))
        self.assertEqual(self.issues(report,'ERR-04'),[])
    def test_complex_frame_not_missing_datum_error(self):
        report=self.run_checks(facts(gdt=[observation(cells=['垂直度','0.01','复杂基准修饰'])]))
        self.assertEqual(self.issues(report,'ERR-04'),[])
    def test_shape_with_datum(self):
        self.assertTrue(self.issues(self.run_checks(facts(gdt=[observation(cells=['平面度','0.01','A'])])),'ERR-04'))
    def test_feature_mismatch(self):
        self.assertTrue(self.issues(self.run_checks(facts(gdt=[observation(cells=['圆度','0.01'],feature_kind='plane')])),'ERR-04'))
    def test_self_reference(self):
        report=self.run_checks(facts(gdt=[observation(cells=['垂直度','0.01','A'],feature_id='face1')],datums=[observation(label='A',feature_id='face1')]))
        self.assertTrue(self.issues(report,'ERR-04'))
    def test_zero_mmc_not_rejected(self):
        self.assertEqual(self.issues(self.run_checks(facts(gdt=[observation(cells=['位置度','0Ⓜ','A'])])),'ERR-04'),[])
    def view_pair(self, **kwargs):
        rows=[observation('v1',part_id='P1',feature_id='hole1',view='主视图',kind='dimension',value='20',unit='mm',comparable=True,association_evidence='同一孔中心线'),
              observation('v2',part_id='P1',feature_id='hole1',view='剖视图',kind='dimension',value='21',unit='mm',comparable=True,association_evidence='同一孔中心线')]
        rows[1].update(kwargs)
        return self.run_checks(facts(view_features=rows))
    def test_view_conflict(self): self.assertEqual(len(self.issues(self.view_pair(),'ERR-05')),1)
    def test_different_parts_not_compared(self): self.assertEqual(self.issues(self.view_pair(part_id='P2'),'ERR-05'),[])
    def test_projection_not_compared(self): self.assertEqual(self.issues(self.view_pair(comparable=False,exclusion_reason='斜向投影缩短'),'ERR-05'),[])
    def test_same_view_not_compared(self): self.assertEqual(self.issues(self.view_pair(view='主视图'),'ERR-05'),[])
    def test_unknown_correspondence(self): self.assertEqual(self.issues(self.view_pair(association_evidence=''),'ERR-05'),[])
    def test_view_units_normalized(self): self.assertEqual(self.issues(self.view_pair(value='2',unit='cm'),'ERR-05'),[])
    def test_unknown_part_keeps_other_facts(self):
        report=self.view_pair(part_id=None)
        self.assertEqual(self.issues(report,'ERR-05'),[])
        self.assertEqual(report['validation_errors'],[])
    def test_hole_count(self):
        rows=[observation('v1',part_id='P',feature_id='holes',view='主视图',kind='hole_count',value='4',comparable=True,association_evidence='同一组通孔'),
              observation('v2',part_id='P',feature_id='holes',view='俯视图',kind='hole_count',value='3',comparable=True,association_evidence='同一组通孔')]
        self.assertTrue(self.issues(self.run_checks(facts(view_features=rows)),'ERR-05'))
    def test_unknown_standard_not_rejected(self):
        report=self.run_checks(facts(standard_references=[observation(reference='GB/T 99999-2099',usage='standard_part')]))
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['checks'][0]['status'],'uncertain')
    def test_replaced_standard_has_source(self):
        report=self.run_checks(facts(standard_references=[observation(reference='GB/T 70.1—2000',usage='standard_part')]))
        issue=self.issues(report,'ERR-07')[0]
        self.assertIn('历史图纸',issue['message'])
        self.assertIn('samr.gov.cn',issue['calculation']['source'])
    def test_current_standard_not_whole_compliance(self):
        report=self.run_checks(facts(standard_references=[observation(reference='GB/T 1182-2018',usage='technical_requirement')]))
        self.assertEqual(report['issues'],[])
        self.assertEqual(report['compliance'],'not_certified')
    def test_standard_family_mismatch(self):
        report=self.run_checks(facts(standard_references=[observation(reference='GB/T 70.1-2008',usage='standard_part',component_index=0)]),comps=[dict(name_zh='六角螺母')])
        self.assertTrue(self.issues(report,'ERR-07'))
    def test_bad_fastener_value(self):
        report=self.run_checks(comps=[dict(specification='M6x-16',source_page=1)])
        self.assertTrue(self.issues(report,'ERR-07'))
    def test_space_conflict(self):
        report=self.run_checks(facts(fastener_spaces=[observation(kind='diametral_clearance',fastener_dimension_index=0,space_dimension_index=1)]),[dim('12±.1'),dim('10±.1')])
        self.assertTrue(self.issues(report,'ERR-07'))
    def test_possible_interference_is_uncertain(self):
        report=self.run_checks(facts(fastener_spaces=[observation(kind='diametral_clearance',fastener_dimension_index=0,space_dimension_index=1)]),[dim('10±.1'),dim('10±.1')])
        self.assertEqual(self.issues(report,'ERR-07'),[])
        self.assertEqual(report['checks'][-1]['status'],'uncertain')
    def test_through_hole_not_depth_conflict(self):
        report=self.run_checks(facts(fastener_spaces=[observation(kind='blind_hole_depth',blind_hole=False,fastener_dimension_index=0,space_dimension_index=1)]),[dim('30'),dim('10')])
        self.assertEqual(self.issues(report,'ERR-07'),[])
    def requirement(self, applies=True, notes=None, terms=None):
        config={'required_annotations':[dict(id='heat',requirement='注明热处理',source='测试企业规则R1',applies_when='指定淬火件',match_terms=['淬火','热处理'] if terms is None else terms)]}
        return self.run_checks(facts(requirement_applicability=[observation(rule_id='heat',applies=applies)],technical_requirements=notes or []),config=config)
    def test_missing_applicable_requirement(self): self.assertTrue(self.issues(self.requirement(),'ERR-09'))
    def test_not_applicable(self): self.assertEqual(self.issues(self.requirement(False),'ERR-09'),[])
    def test_unknown_applicability(self): self.assertEqual(self.issues(self.requirement(None),'ERR-09'),[])
    def test_missing_match_terms(self): self.assertEqual(self.issues(self.requirement(terms=[]),'ERR-09'),[])
    def test_present_requirement(self):
        self.assertEqual(self.issues(self.requirement(notes=[observation(text='淬火后回火')]),'ERR-09'),[])
    def test_other_page_note_not_assumed_same_part(self):
        note=observation(text='淬火后回火');note['source_page']=2
        self.assertTrue(self.issues(self.requirement(notes=[note]),'ERR-09'))
    def test_notes_inverted_hardness_and_negative_roughness(self):
        report=self.run_checks(facts(technical_requirements=[observation(text='硬度HRC 60～55；表面Ra -1.6')]))
        self.assertEqual(len(self.issues(report,'ERR-09')),2)
    def test_placeholder(self):
        self.assertTrue(self.issues(self.run_checks(facts(technical_requirements=[observation(text='热处理待定')])),'ERR-09'))
    def test_other_part_note_not_used(self):
        config={'required_annotations':[dict(id='heat',requirement='热处理',source='测试规则',applies_when='P1',match_terms=['淬火'])]}
        report=self.run_checks(facts(requirement_applicability=[observation(rule_id='heat',applies=True,part_id='P1')],
            technical_requirements=[observation(text='淬火',part_id='P2')]),config=config)
        self.assertTrue(self.issues(report,'ERR-09'))
    def test_multiple_scales_allowed(self):
        report=self.run_checks(title={'scale':'1:2 / A向2:1'},config={'title_source_page':1})
        self.assertEqual(self.issues(report,'ERR-10'),[])
    def test_scale_zero(self):
        self.assertTrue(self.issues(self.run_checks(title={'scale':'1:0'},config={'title_source_page':1}),'ERR-10'))
    def test_scale_unknown_page(self):
        self.assertEqual(self.issues(self.run_checks(title={'scale':'1:0'}),'ERR-10'),[])
    def test_scale_not_to_scale(self):
        self.assertEqual(self.issues(self.run_checks(title={'scale':'NTS'}),'ERR-10'),[])
    def test_enterprise_scale(self):
        report=self.run_checks(title={'scale':'1:3'},config={'title_source_page':1,'format_policy':{'allowed_scales':['1:1','1:2'],'source':'企业测试模板'}})
        self.assertTrue(self.issues(report,'ERR-10'))
    def test_sheet_a4_and_elongated(self):
        for w,h in [(210,297),(297,210),(297,630)]:
            with self.subTest(w=w,h=h):
                self.assertEqual(self.issues(self.run_checks(metadata=[dict(source_page=1,kind='pdf',width_mm=w,height_mm=h)]),'ERR-10'),[])
    def test_raster_has_no_size_verdict(self):
        report=self.run_checks(metadata=[dict(source_page=1,kind='raster_or_cad_render')])
        self.assertEqual(report['checks'][0]['status'],'uncertain')
    def test_wrong_enterprise_sheet(self):
        report=self.run_checks(config={'format_policy':{'source':'企业模板','allowed_sheets':['A3']}},metadata=[dict(source_page=1,kind='pdf',width_mm=210,height_mm=297)])
        self.assertTrue(self.issues(report,'ERR-10'))
    def test_unreadable_not_issues(self):
        obs=observation(cells=['垂直度','0.01']);obs['readable']=False
        self.assertEqual(self.issues(self.run_checks(facts(gdt=[obs])),'ERR-04'),[])
    def test_input_unchanged(self):
        data=facts(gdt=[observation(cells=['垂直度','0.01'])]);before=copy.deepcopy(data)
        self.run_checks(data)
        self.assertEqual(data,before)


class ValidationTests(unittest.TestCase):
    def test_bad_fact_rejected(self):
        row=observation(cells=['平面度','0.01'])
        for mutation in ('page','bbox','evidence','readable','cells','duplicate'):
            data=facts(gdt=[copy.deepcopy(row)])
            if mutation=='page': data['gdt'][0]['source_page']=True
            elif mutation=='bbox': data['gdt'][0]['bbox']=[0,0,float('nan'),1]
            elif mutation=='evidence': data['gdt'][0]['evidence']=''
            elif mutation=='readable': data['gdt'][0]['readable']='true'
            elif mutation=='cells': data['gdt'][0]['cells']=[0,1]
            else: data['gdt'].append(row)
            with self.subTest(mutation=mutation):
                result_errors = validate_observations(data,1,[],[])
                ids = [r.get('id') for r in data.get('gdt') or []]
                # 核心不变量：组内不保留重复 id（坏行被隔离或报错，均不允许重复存活）
                self.assertEqual(len(ids), len(set(ids)))
                if mutation != 'duplicate':
                    self.assertTrue(result_errors or data.get('quarantined'))
    def test_index_bases_not_guessed(self):
        for index in (-1,2,True,'0'):
            data=facts(fits=[observation(hole_dimension_index=index,shaft_dimension_index=1)])
            self.assertTrue(validate_observations(data,1,[dim('20'),dim('20')],[]))
    def test_unhashable_semantic_fields_rejected(self):
        data=facts(view_features=[observation(part_id=['P1'],feature_id='hole',view='主',kind='dimension',value='20',unit='mm',association_evidence='同孔',comparable=True)])
        self.assertTrue(validate_observations(data,1,[],[]))
    def test_legacy_generic_dimensions_not_cross_part_matched(self):
        from engine_bom.inspect_rules import check_dimensions
        self.assertEqual(check_dimensions([dict(tag='孔直径',value='20+.02/0',view='P1'),dict(tag='孔直径',value='20',view='P2')]),[])
        self.assertEqual(check_dimensions([dict(tag='D1',feature_id='bore',part_id='P1',value='20'),dict(tag='D1',feature_id='bore',part_id='P2',value='21')]),[])
    def test_missing_groups(self): self.assertTrue(validate_observations({},1,[],[]))
    def test_invalid_observation_does_not_crash_or_find(self):
        report=run_engineering_checks(facts(fits=[observation(hole_dimension_index=999,shaft_dimension_index=0)]),[dim('20')],[],{})
        # 隔离契约下坏行在 validate 阶段已被丢弃，直接调用时状态为 partial；核心意图：不崩溃、不产生发现
        self.assertIn(report['status'], ('invalid_observations', 'partial'))
        self.assertEqual(report['issues'],[])
    def test_bad_config(self):
        table=dict(band='H7',source='test',min_exclusive=18,max_inclusive=30,lower_mm=0,upper_mm=.021)
        for key,value in [('source',''),('max_inclusive',18),('lower_mm',.03),('upper_mm',float('nan'))]:
            row=dict(table);row[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): validate_engineering_config({'tolerance_bands':[row]})
        with self.assertRaises(ValueError): validate_engineering_config({'tolerance_bands':[table,table]})
        with self.assertRaises(ValueError): validate_engineering_config({'format_policy':{'allowed_scales':['1:0'],'source':'test'}})
    def test_enterprise_import_validates_tables(self):
        with self.assertRaises(ValueError): validate_profile({'inspection_rules':{'standards':[{'reference':'fake'}]}})
        with self.assertRaises(ValueError): validate_profile({'inspection_rules':{'enabled':False}})
    def test_same_config_both_routes(self):
        cfg={'inspection':{'enabled':True},'enterprise':{'required_annotations':[{'id':'x'}],'inspection_rules':{'format_policy':{'source':'test','allowed_scales':['1:2']}}}}
        result=inspection_config(cfg,'test.png',{'source_page':2})
        self.assertEqual(result['format_policy']['allowed_scales'],['1:2'])
        self.assertEqual(result['required_annotations'],[{'id':'x'}])
        self.assertEqual(result['page_metadata'][0]['kind'],'raster_or_cad_render')
    def test_pdf_metadata_original_units(self):
        import fitz
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,'a.pdf')
            with fitz.open() as doc:
                doc.new_page(width=210*72/25.4,height=297*72/25.4);doc.save(path)
            self.assertAlmostEqual(inspection_config({},path)['page_metadata'][0]['width_mm'],210,places=3)
    def test_title_crop_original_page_mapping(self):
        images=[Image.new('RGB',(10,10)) for _ in range(3)]
        regions=[dict(kind='title_block',source_page=2,bbox=[0,0,1,1]),dict(kind='title_block',source_page=2,bbox=[0,0,1,1]),dict(kind='title_block',source_page=3,bbox=[0,0,1,1])]
        self.assertEqual(titleblock_page_numbers(images,regions),[2,2,2,3,3])
        self.assertEqual(len(titleblock_images(images,regions)),5)
    def test_title_single_page_known(self):
        class Model:
            name='mock'
            def analyze(self,images,prompt): return ProviderResponse(json.dumps({'title_block':{'scale':'1:0'}}))
        fields=extract_titleblock(Model(),[object()],3)['fields']
        self.assertEqual(fields['source_page'],3)


class IntegrationTests(unittest.TestCase):
    def test_unverified_model_standard_claim_is_not_verified_issue(self):
        visual=[{'err_id':'ERR-07','message':'标准已废止','evidence':'模型猜测','source_page':1}]
        allowed, unverified=gate_visual_engineering(visual,[])
        self.assertEqual(allowed,[])
        self.assertEqual(unverified[0]['status'],'unverified')
    def test_visual_review_cannot_overwrite_computed_values(self):
        findings=[dict(finding_id='engineering-0',err_id='ERR-03',origin='engineering_rule',message='区间0.01至0.05',evidence='原文',source_page=1)]
        visual=[dict(related_rule_id='engineering-0',err_id='ERR-03',message='区间0.1至0.5',evidence='不正确复述',source_page=1)]
        allowed,_=gate_visual_engineering(visual,findings)
        merged=merge_findings(findings,allowed)
        self.assertEqual(merged[0]['message'],'区间0.01至0.05')
        self.assertEqual(merged[0]['origin'],'engineering_rule+vlm')
    def model(self, observations):
        class Model:
            name='test'
            count=0
            def analyze(self,images,prompt):
                self.count+=1
                return ProviderResponse(json.dumps({'issues':[],
                    'engineering_observations':observations,
                    'coverage':{'ERR-%02d'%n:{'status':'checked','evidence':'原图观察'} for n in range(1,11)}}))
        return Model()
    def test_hybrid_computes_all_six(self):
        data=facts(fits=[observation(hole_dimension_index=0,shaft_dimension_index=1,intended_fit='过盈配合')],
            gdt=[observation(cells=['垂直度','0.01'])],
            view_features=[observation('a',part_id='P',feature_id='hole',view='主',value='20',unit='mm',kind='dimension',comparable=True,association_evidence='同孔'),observation('b',part_id='P',feature_id='hole',view='剖',value='21',unit='mm',kind='dimension',comparable=True,association_evidence='同孔')],
            standard_references=[observation(reference='GB/T 70.1-2000',usage='standard_part')],
            technical_requirements=[observation(text='热处理待定')])
        result=inspect(self.model(data),[object()],{'scale':'1:0'},[],[dim('20+.02/0'),dim('20-.01/-.03')],[],{'title_source_page':1,'require_engineering_observations':True})
        self.assertTrue(set(('ERR-03','ERR-04','ERR-05','ERR-07','ERR-09','ERR-10')).issubset({r['err_id'] for r in result['issues']}))
        self.assertEqual(result['engineering']['extraction_status'],'validated')
        json.dumps(result)
    def test_model_compliance_is_not_a_pass(self):
        result=inspect(self.model(facts()),[object()],{},[],[],[],{'require_engineering_observations':True})
        self.assertEqual(result['checklist']['ERR-03']['status'],'uncertain')
    def test_missing_observations_retries_and_retains_numeric_checks(self):
        model=self.model(None)
        result=inspect(model,[object()],{},[],[dim('20±-0.1')],[],{'max_attempts':2,'require_engineering_observations':True})
        self.assertEqual(model.count,3)
        self.assertEqual(result['visual_status'],'needs_review')
        self.assertTrue(any(r['err_id']=='ERR-03' for r in result['issues']))
    def test_malformed_observations_are_not_used(self):
        data=facts(gdt=[observation(cells=['垂直度','0.01'])]);data['gdt'][0]['source_page']=99
        result=inspect(self.model(data),[object()],{},[],[],[],{'max_attempts':1})
        self.assertEqual(result['visual_status'],'needs_review')
        self.assertFalse(any(r['err_id']=='ERR-04' for r in result['issues']))
    def test_mock_still_computes_literal_tolerances(self):
        model=self.model(facts());model.name='mock'
        result=inspect(model,[object()],{},[],[dim('20±-0.1')],[],{})
        self.assertEqual(model.count,0)
        self.assertTrue(any(r['err_id']=='ERR-03' for r in result['issues']))
    def test_provider_failure_preserves_deterministic_findings(self):
        from engine_bom.providers import ProviderError
        class Model:
            name='test'
            def analyze(self,images,prompt): raise ProviderError('test failure')
        result=inspect(Model(),[object()],{},[],[dim('20±-0.1')],[],{'require_engineering_observations':True})
        self.assertEqual(result['visual_status'],'provider_failed')
        self.assertTrue(any(r['err_id']=='ERR-03' for r in result['issues']))


if __name__=='__main__': unittest.main()
