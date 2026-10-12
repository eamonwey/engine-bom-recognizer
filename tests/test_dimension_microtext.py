import json,unittest
from PIL import Image
from engine_bom.dimension_microtext import diameter_prefix,reread_neighbors
from engine_bom.dimension_text import refine_positions
from engine_bom.dimension_links import nominal
from engine_bom.providers.base import ProviderResponse,ProviderError


class MicroTextTests(unittest.TestCase):
    def test_missing_fit_glyph_does_not_invent_j_or_split_627(self):
        self.assertEqual(diameter_prefix('Φ62√7'),'62')
        self.assertEqual(diameter_prefix('Φ627'),'627')
        for text in ('627','Φ6?7','Φ?2J7','Φ62 + 2','Φ62与60'):
            self.assertIsNone(diameter_prefix(text))
        self.assertIsNone(nominal(dict(value='Φ62√7',kind='diameter',unit='mm')))
        self.assertEqual(nominal(dict(value='Φ62√7',kind='diameter',unit='mm',fit_text_unverified=True)),62)

    def test_bare_numeric_candidate_is_not_passed_as_a_suggested_reading(self):
        class Model:
            def analyze(model,images,prompt):
                self.assertNotIn('627',prompt);self.assertNotIn('62',prompt)
                return ProviderResponse(json.dumps({'texts':[{'id':'text-1','raw_text':'Φ62√7','readable':True}]}))
        r=reread_neighbors(Model(),[Image.new('RGB',(1000,1000),'white')],
                           [dict(raw_text='627',source_page=1,bbox=[.2,.3,.3,.32])])
        text=r['observations'][0]
        self.assertEqual(text['raw_text'],'Φ62√7');self.assertTrue(text['fit_unreadable'])
        self.assertEqual(text['nominal_diameter'],'62');self.assertNotIn('confidence',text)

    def test_partial_or_failed_reply_is_not_text_support(self):
        class Model:
            def analyze(model,*args):return ProviderResponse('{"texts":[]}')
        candidates=[dict(raw_text='627',source_page=1,bbox=[.2,.3,.3,.32])]
        r=reread_neighbors(Model(),[Image.new('RGB',(1000,1000))],candidates)
        self.assertEqual(r['status'],'needs_review');self.assertFalse(r['observations'])
        class Offline:
            def analyze(model,*args):raise ProviderError('offline')
        self.assertEqual(reread_neighbors(Offline(),[Image.new('RGB',(1000,1000))],candidates)['status'],'provider_failed')

    def test_nominal_support_refines_position_without_overwriting_fit_or_digits(self):
        obs=dict(value='Φ62J7',source_page=1,bbox=[.21,.3,.31,.32])
        text=dict(raw_text='Φ62√7',nominal_diameter='62',fit_body=None,fit_unreadable=True,
                  source_page=1,bbox=[.2,.3,.3,.32])
        r=refine_positions([obs],{'observations':[text]})[0]
        self.assertEqual(r['value'],'Φ62J7');self.assertTrue(r['fit_text_unverified'])
        self.assertEqual(r['bbox'],text['bbox'])
        text['nominal_diameter']='627'
        self.assertEqual(refine_positions([obs],{'observations':[text]})[0]['bbox'],obs['bbox'])


if __name__=='__main__':unittest.main()
