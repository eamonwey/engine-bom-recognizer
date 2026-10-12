import copy
import json
import unittest
from engine_bom.titleblock import dimension_role_error, extract_dims_and_balloons
from engine_bom.providers import ProviderResponse
from tests.test_tolerance_chains import gap_fixture


class DimensionRoleLoopTests(unittest.TestCase):
    def test_role_quote_must_refer_to_its_dimension(self):
        dims,_,_=gap_fixture()
        wrong=dict(dims[2],dimension_role='closing_requirement',role_evidence=dims[0]['role_evidence'])
        self.assertIsNotNone(dimension_role_error(wrong))
        self.assertIsNone(dimension_role_error(dims[0]))
        self.assertIsNone(dimension_role_error(dims[2]))
        self.assertIsNotNone(dimension_role_error(dict(dims[0],role_evidence='')))

    def test_wrong_role_retries_reading_original_image(self):
        dims,_,_=gap_fixture()
        wrong=copy.deepcopy(dims)
        wrong[2].update(dimension_role='closing_requirement',role_evidence=dims[0]['role_evidence'])
        class Provider:
            name='test'
            calls=[]
            def analyze(self,images,prompt):
                self.calls.append((images,prompt))
                return ProviderResponse(json.dumps({'dimensions':wrong if len(self.calls)==1 else dims,'balloons':[]}), 'test')
        p=Provider();images=[object()]
        result=extract_dims_and_balloons(p,images)
        self.assertEqual(result['status'],'validated')
        self.assertEqual(len(result['events']),2)
        self.assertIn('重新阅读原图',p.calls[1][1])
        self.assertIs(p.calls[1][0],images)
        self.assertEqual(result['dimensions'][2]['dimension_role'],'component')

    def test_exhausted_role_validation_does_not_feed_invalid_dimensions(self):
        class Provider:
            name='test'
            def analyze(self,*args):
                return ProviderResponse(json.dumps({'dimensions':[{'value':'100','tag':'L',
                    'dimension_role':'closing_requirement','role_evidence':'间隙S要求10±0.1'}],'balloons':[]}), 'test')
        result=extract_dims_and_balloons(Provider(),[object()])
        self.assertEqual(result['status'],'needs_review')
        self.assertEqual(len(result['events']),3)
        self.assertFalse(result['dimensions'])
        self.assertTrue(result['warnings'])

    def test_old_payload_without_new_role_fields_still_accepted(self):
        class Provider:
            name='test'
            def analyze(self,*args):
                return ProviderResponse('{"dimensions":[{"value":"20"}],"balloons":[1]}','test')
        result=extract_dims_and_balloons(Provider(),[object()])
        self.assertEqual(result['status'],'validated')
        self.assertEqual(result['dimensions'][0]['source_page'],1)


if __name__=='__main__':unittest.main()
