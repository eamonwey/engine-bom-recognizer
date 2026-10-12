import json
import io
import urllib.error
import unittest
from unittest.mock import patch
from PIL import Image
from engine_bom.assembly import quarantine_tree_candidate,infer_assembly
from engine_bom.agent_loop import AgentLoop
from engine_bom.providers.base import ProviderResponse
from engine_bom.providers.base import ProviderConfigError
from engine_bom.providers.openai_compat import OpenAICompatVisionProvider
from tests.test_gearbox_regressions import node


class RecoveryAndTraceTests(unittest.TestCase):
    def setUp(self):
        self.components=[{'name_zh':n,'quantity':1} for n in ['箱体','盖','油封']]
        self.rows=[node('base',0,'箱体'),node('cover',1,'盖','base',0),node('seal',2,'油封','cover',1)]

    def test_invalid_identity_is_isolated_without_guessing_or_promoting_descendant(self):
        self.rows[1]['component_name']='错误名称'
        safe,pending=quarantine_tree_candidate({'nodes':self.rows},self.components,1)
        self.assertEqual([n['id'] for n in safe['nodes']],['base'])
        self.assertEqual({n['id'] for n in pending},{'cover','seal'})
        self.assertEqual(pending[0]['component_name'],'错误名称')

    def test_duplicate_ids_cycles_and_unhashable_ids_do_not_crash_recovery(self):
        for rows in [self.rows+[self.rows[1]],
                     [dict(self.rows[0],parent_id='cover',parent_component_index=1),*self.rows[1:]],
                     self.rows+[dict(self.rows[2],id=['bad'])]]:
            with self.subTest(rows=rows):
                safe,pending=quarantine_tree_candidate({'nodes':rows},self.components,1)
                self.assertTrue(pending)
                self.assertTrue(all(n['relation_status']=='uncertain' for n in pending))

    def test_valid_recovered_subgraph_requires_independent_reread(self):
        self.rows[2]['component_name']='错误名称'
        class Model:
            name='recorded'
            def analyze(model,*args):return ProviderResponse(json.dumps({'nodes':self.rows},ensure_ascii=False))
        with patch('engine_bom.installation_review.verify_installation',side_effect=lambda p,i,t,c:dict(t,verification_events=[])) as verify:
            r=infer_assembly(Model(),[object()],self.components,dict(method='installation',max_attempts=1,verify_visual=True))
        verify.assert_called_once()
        self.assertEqual({n['id'] for n in r['nodes']},{'base','cover'})
        self.assertIn('seal',[n['id'] for n in r['unverified_nodes']])
        self.assertEqual(r['inference_status'],'needs_review')

    def test_valid_json_at_token_limit_is_not_completed(self):
        class Model:
            def analyze(model,*args):return ProviderResponse('{}',finish_reason='length')
        validator=unittest.mock.Mock(return_value=({},[]))
        r=AgentLoop(Model(),1).run([], 'prompt',validator)
        self.assertEqual(r.status,'needs_review');self.assertIn('长度上限',r.events[0]['errors'][0])
        validator.assert_not_called()

    def test_request_fingerprints_are_stable_and_do_not_include_credentials(self):
        p=OpenAICompatVisionProvider({'base_url':'http://local.invalid','model':'test','api_key':'test-secret-only'})
        with patch.object(p,'_post_chat',return_value='{}'):
            a=p.analyze([Image.new('RGB',(10,10),'white')],'prompt')
            b=p.analyze([Image.new('RGB',(10,10),'white')],'prompt')
            c=p.analyze([Image.new('RGB',(10,10),'white')],'new prompt')
        self.assertEqual(a.request_metadata,b.request_metadata)
        self.assertNotEqual(a.request_metadata['request_sha256'],c.request_metadata['request_sha256'])
        self.assertNotIn('test-secret-only',json.dumps(a.request_metadata))
        self.assertEqual(a.request_metadata['input_image_sizes'],[[10,10]])

    def test_quota_429_is_terminal_instead_of_three_fake_timeout_retries(self):
        p=OpenAICompatVisionProvider({'base_url':'http://local.invalid','model':'test','api_key':'test-secret-only','retries':2})
        error=urllib.error.HTTPError('http://local.invalid',429,'limit',{},io.BytesIO(b'{"error":{"code":"1113","message":"quota exhausted"}}'))
        with patch('urllib.request.urlopen',side_effect=error) as request,patch('time.sleep') as sleep:
            with self.assertRaises(ProviderConfigError):p.analyze([],'prompt')
        request.assert_called_once();sleep.assert_not_called()


if __name__=='__main__':unittest.main()
