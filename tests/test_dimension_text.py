import unittest
from unittest.mock import patch
from engine_bom.dimension_text import read_fit_text,fit_body,refine_positions


class LocalDimensionTextTests(unittest.TestCase):
    def test_ocr_cannot_invent_missing_diameter_symbol_or_fix_similar_digits(self):
        self.assertEqual(fit_body('60H9/h9'),'60H9/h9')
        self.assertEqual(fit_body('Φ 60 H9/h9'),'60H9/h9')
        self.assertIsNone(fit_body('627'));self.assertIsNone(fit_body('招6094'))

    def test_unavailable_runtime_is_explicit_not_success(self):
        with patch('engine_bom.dimension_text._get_engine',side_effect=ImportError('unavailable')):
            report=read_fit_text([object()])
        self.assertEqual(report['status'],'not_available');self.assertEqual(report['observations'],[])

    def test_exact_local_reread_refines_box_and_preserves_old_evidence(self):
        old={'value':'Φ60H9/h9','bbox':[.35,.85,.4,.9],'source_page':1,'component_index':0}
        text={'raw_text':'60H9/h9','fit_body':'60H9/h9','bbox':[.25,.86,.31,.89],'source_page':1}
        refined=refine_positions([old],{'observations':[text]})[0]
        self.assertEqual(refined['bbox'],text['bbox']);self.assertEqual(refined['bbox_before_local_text'],old['bbox'])
        self.assertEqual(refined['value'],old['value']);self.assertNotIn('bbox_before_local_text',old)

    def test_ambiguous_repeated_annotations_and_other_pages_cannot_choose_a_position(self):
        old={'value':'Φ62J7','bbox':[.25,.5,.3,.6],'source_page':1}
        texts=[{'fit_body':'62J7','bbox':[.25,.48,.3,.58],'source_page':1},
               {'fit_body':'62J7','bbox':[.25,.52,.3,.62],'source_page':1}]
        self.assertEqual(refine_positions([old],{'observations':texts})[0],old)
        texts[0]['source_page']=2;texts.pop()
        self.assertEqual(refine_positions([old],{'observations':texts})[0],old)

    def test_mismatched_digits_are_never_replaced_from_ocr(self):
        old={'value':'Φ62H9/h9','bbox':[.25,.5,.3,.6],'source_page':1}
        text={'fit_body':'60H9/h9','bbox':[.25,.5,.3,.6],'source_page':1}
        self.assertEqual(refine_positions([old],{'observations':[text]})[0],old)
