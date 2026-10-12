import io
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from engine_bom import webapp as w
from engine_bom.titleblock import validate_titleblock, extract_titleblock
from engine_bom.hybrid_inspection import merge_findings


class ReportFixTests(unittest.TestCase):
    def test_title_crop_retains_page_and_label_margin(self):
        from PIL import Image
        from engine_bom.drawing_layout import titleblock_images
        page=Image.new('RGB',(1000,1000))
        images=titleblock_images([page],[{'kind':'title_block','source_page':1,'bbox':[.62,.73,.98,.96]}])
        self.assertIs(images[0],page)
        self.assertGreater(images[1].width,360)

    def test_material_label_overrides_assembly_assumption(self):
        fields, errors = validate_titleblock(json.dumps({'material':'','material_applicable':False,
            'field_evidence':{'material':{'label':'材料','value':'TC11'}}}))
        self.assertEqual(errors, [])
        self.assertEqual(fields['material'], 'TC11')
        self.assertTrue(fields['material_applicable'])

    def test_bare_number_is_not_guessed_to_be_material(self):
        fields, errors = validate_titleblock('{"extra":{"title_no_field":"45"}}')
        self.assertTrue(errors)
        self.assertNotIn('material', fields)

    def test_mislabelled_extra_is_rejected(self):
        _, errors = validate_titleblock(json.dumps({'extra':{'title_no_field':'35'},
            'field_evidence':{'material':{'label':'','value':''},'title_no_field':{'label':'材料','value':'35'}}}))
        self.assertTrue(any('不是序号' in e for e in errors))

    def test_title_retry_and_exhaustion_visible(self):
        provider = SimpleNamespace(name='test', analyze=lambda *_:SimpleNamespace(raw_text='{}',model='test',latency_s=0))
        result = extract_titleblock(provider, [])
        self.assertEqual(result['fields']['extraction_status'], 'needs_review')
        self.assertTrue(result['fields']['extraction_warnings'])

    def test_chain_merge_cannot_promote_speculative_fix(self):
        rule={'err_id':'ERR-01','finding_id':'chain-0','message':'40+50 != 100','suggestion':'核实','chain':{}}
        visual={'err_id':'ERR-01','related_rule_id':'chain-0','suggestion':'改为50+50'}
        result=merge_findings([rule],[visual])[0]
        self.assertIn('不能唯一确定',result['suggestion'])
        self.assertNotIn('50+50',result['suggestion'])
        self.assertEqual(result['sources'][1]['suggestion'],'改为50+50')

    def test_missing_second_upload_does_not_create_job(self):
        with patch.object(w,'_create_job') as create:
            with self.assertRaises(ValueError):w._prepare_upload_job('compare', {'before':SimpleNamespace(filename='a.txt')}, ['before','after'])
            create.assert_not_called()

    def test_upload_write_failure_marks_terminal(self):
        with patch.object(w,'_jobs',{'test':{'dir':'unused'}}), patch.object(w,'_create_job',return_value='test'), patch.object(w,'_save_upload',side_effect=OSError('disk full')), patch.object(w,'_finish_job') as finish:
            with self.assertRaises(OSError):w._prepare_upload_job('bom', {'file':SimpleNamespace(filename='a.png')}, ['file'])
            finish.assert_called_once_with('test',error='disk full')
