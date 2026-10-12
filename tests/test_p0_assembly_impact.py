import json
import os
import tempfile
import unittest
from PIL import Image
from engine_bom.assembly import validate_tree, infer_assembly
from engine_bom.impact import analyze_impact, validate_index
from engine_bom.document_layout import chunks
from engine_bom.changedetect import align_and_diff
from engine_bom.review_workflow import ReviewStore, authenticate
from engine_bom.providers.base import ProviderError, ProviderResponse
from engine_bom.docextract import extract_elements


def node(key, parent, index=0):
    return dict(id=key,parent_id=parent,component_index=index,source_page=1,evidence='图示连接',quantity_per_parent=1)


class AssemblyTests(unittest.TestCase):
    def test_three_levels_and_occurrences(self):
        tree=validate_tree({'nodes':[node('a',None),node('b','a',1),node('c','b',2),node('d','a',2)]},[{}, {}, {}, {}])
        self.assertEqual(tree['max_depth'],3)
        self.assertEqual(tree['unresolved_component_indices'],[3])
    def test_cycle(self):
        with self.assertRaises(ValueError): validate_tree({'nodes':[node('a','b'),node('b','a')]},[{}])
    def test_dangling(self):
        with self.assertRaises(ValueError): validate_tree({'nodes':[node('a','absent')]},[{}])
    def test_missing_evidence(self):
        n=node('a',None); n['evidence']=''
        with self.assertRaises(ValueError): validate_tree({'nodes':[n]},[{}])
    def test_nonfinite_quantity(self):
        n=node('a',None); n['quantity_per_parent']=float('nan')
        with self.assertRaises(ValueError): validate_tree({'nodes':[n]},[{}])
    def test_failed_provider_preserves_unknown(self):
        class Broken:
            name='real'
            def analyze(self,*args): raise ProviderError('no credits')
        result=infer_assembly(Broken(),[],[{}])
        self.assertEqual(result['inference_status'],'provider_failed')
        self.assertEqual(result['unresolved_component_indices'],[0])


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.index={'objects':[dict(id='spec',kind='document',keywords=['TC4']),dict(id='bom',kind='bom',depends_on=['spec']),dict(id='process',kind='process',depends_on=['bom']),dict(id='test',kind='inspection',depends_on=['process'])]}
    def test_trace(self):
        result=analyze_impact([{'before':'材料TC4','after':'材料TC11'}],self.index)
        target=next(o for o in result['objects'] if o['id']=='test')
        self.assertEqual(target['reasons'][0]['dependency_path'],['spec','bom','process','test'])
    def test_identifier_boundary(self):
        self.assertEqual(analyze_impact([{'before':'TC40'}],self.index)['objects'],[])
    def test_empty_does_not_mean_clear(self):
        self.assertEqual(analyze_impact([],{'objects':[]})['status'],'not_configured')
    def test_invalid_reference(self):
        self.index['objects'][0]['depends_on']=['absent']
        with self.assertRaises(ValueError): validate_index(self.index)
    def test_invalid_identifiers(self):
        self.index['objects'][0]['identifiers']='TC4'
        with self.assertRaises(ValueError): validate_index(self.index)
    def test_cycle_terminates(self):
        self.index['objects'][0]['depends_on']=['test']
        self.assertEqual(len(analyze_impact([{'before':'TC4'}],self.index)['objects']),4)


class DocumentTests(unittest.TestCase):
    def test_long_tail_retained(self):
        text='a'*25000+'TAIL'
        parts=list(chunks([dict(id='b1',text=text)]))
        self.assertEqual(''.join(b['text'] for p in parts for b in p),text)
    def test_reordered_paragraphs(self):
        self.assertEqual(align_and_diff(['A','B','C'],['C','A','B']),[])
    def test_duplicate_deletion_not_lost(self):
        result=align_and_diff(['A','A','B'],['A','B'])
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['type'],'removed')
    def test_minus_is_data(self):
        self.assertEqual(len(align_and_diff(['温度 -55℃'],['温度 55℃'])),1)
    def test_decimal_is_data(self):
        self.assertEqual(len(align_and_diff(['公差 0.05'],['公差 005'])),1)
    def test_source_validation_retries(self):
        class Model:
            name='real'
            calls=0
            def analyze(self,images,prompt):
                self.calls+=1
                return ProviderResponse(json.dumps(dict(tech_params=[dict(name='温度',source_block_id='wrong' if self.calls==1 else 'b1')],materials=[],process_requirements=[],inspection=[])))
        model=Model()
        result=extract_elements(model,{'blocks':[dict(id='b1',text='温度100℃',source_page=3,bbox=[0,0,1,1])]})
        self.assertEqual(model.calls,2)
        self.assertEqual(result['tech_params'][0]['source_page'],3)
        self.assertEqual(result['tech_params'][0]['source_text'],'温度100℃')
    def test_scan_original_page(self):
        class Model:
            name='real'
            def analyze(self,images,prompt):
                rows=[dict(name='温度',source_page=999,bbox=[-1,0,1,1])] if images else []
                return ProviderResponse(json.dumps(dict(tech_params=rows,materials=[],process_requirements=[],inspection=[])))
        result=extract_elements(Model(),{'blocks':[dict(id='b1',text='A'*45,source_page=1)]},[Image.new('RGB',(10,10)),Image.new('RGB',(10,10))])
        self.assertEqual(result['tech_params'][0]['source_page'],2)
        self.assertIsNone(result['tech_params'][0]['bbox'])


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ReviewStore(os.path.join(self.temp.name,'review.db'))
        self.editor={'id':'alice','role':'editor'}
        self.reviewer={'id':'bob','role':'reviewer'}
        self.approver={'id':'carol','role':'approver'}
    def tearDown(self): self.temp.cleanup()
    def test_full_flow_and_revision_invalidation(self):
        first=self.store.transition('a','submit',self.editor,payload={'x':1})
        self.store.transition('a','review',self.reviewer,1,{'x':1})
        approved=self.store.transition('a','approve',self.approver,2,{'x':1})
        self.assertEqual(approved['state'],'approved')
        changed=self.store.transition('a','submit',self.editor,3,{'x':2})
        self.assertEqual(changed['state'],'submitted')
        self.assertIsNone(changed['approver'])
        self.assertNotEqual(first['hash'],changed['hash'])
        self.assertEqual(len(changed['audit']),4)
    def test_wrong_role(self):
        with self.assertRaises(PermissionError): self.store.transition('a','approve',self.editor)
    def test_no_self_review(self):
        self.store.transition('a','submit',self.editor,payload={'x':1})
        with self.assertRaises(PermissionError): self.store.transition('a','review',{'id':'alice','role':'reviewer'},1,{'x':1})
    def test_stale_revision(self):
        self.store.transition('a','submit',self.editor,payload={'x':1})
        with self.assertRaises(ValueError): self.store.transition('a','submit',self.editor,0,{'x':2})
    def test_bad_token(self):
        with self.assertRaises(PermissionError): authenticate([], 'bad')


class CadTests(unittest.TestCase):
    def test_dxf_renders(self):
        import ezdxf
        from engine_bom.ingestion import load_document
        with tempfile.TemporaryDirectory() as folder:
            path=os.path.join(folder,'drawing.dxf')
            drawing=ezdxf.new(); drawing.modelspace().add_circle((0,0),10); drawing.saveas(path)
            pages=load_document(path,{'dpi':72,'max_image_long_side':500})
            self.assertTrue(pages)
            self.assertLessEqual(max(pages[0].size),500)
            self.assertLess(pages[0].image.convert('L').getextrema()[0],250)

class EnterpriseTests(unittest.TestCase):
    def test_mapping(self):
        from engine_bom.enterprise import mapped_components
        result=mapped_components([{'part_number':'A','quantity':2}],{'export_fields':{'part_number':'物料编码','quantity':'用量'}})
        self.assertEqual(result['rows'],[{'物料编码':'A','用量':2}])
    def test_bad_duplicate_columns(self):
        from engine_bom.enterprise import validate_profile
        with self.assertRaises(ValueError): validate_profile({'export_fields':{'part_number':'A','quantity':'A'}})
    def test_requirement_needs_basis(self):
        from engine_bom.enterprise import validate_profile
        with self.assertRaises(ValueError): validate_profile({'required_annotations':[{'id':'a','requirement':'必须标注'}]})

class WebIntegrationTests(unittest.TestCase):
    def test_save_exports_and_roles(self):
        import threading
        import hashlib
        from http.client import HTTPConnection
        from http.server import ThreadingHTTPServer
        from unittest.mock import patch
        from engine_bom import webapp
        with tempfile.TemporaryDirectory() as folder:
            users=[{'id':'editor','role':'editor','token_sha256':hashlib.sha256(b'editor-secret').hexdigest()}]
            with open(os.path.join(folder,'review_users.json'),'w') as f: json.dump(users,f)
            job={'kind':'bom','status':'done','dir':folder,'result':{'document_id':'sample','bom':{'components':[{'part_number':'A','quantity':1}],'assembly':{'nodes':[node('a',None)]}}}}
            with patch.object(webapp,'DATA_DIR',folder), patch.object(webapp,'REVIEWLOG_PATH',os.path.join(folder,'log.json')), patch.object(webapp,'_jobs',{'sample':job}):
                server=ThreadingHTTPServer(('127.0.0.1',0),webapp.Handler)
                thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
                conn=HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                def request(path,payload,token=''):
                    conn.request('POST',path,json.dumps(payload).encode(),{'Content-Type':'application/json','X-API-Token':webapp._API_TOKEN,'X-Review-Token':token})
                    response=conn.getresponse(); return response.status,json.loads(response.read())
                try:
                    status,_=request('/api/bom/save',{'job_id':'sample','document_id':'sample','components':[{'part_number':'B','quantity':2}]})
                    self.assertEqual(status,200)
                    conn.request('GET','/api/export/bom/sample?fmt=json'); response=conn.getresponse(); bom=json.loads(response.read())
                    self.assertEqual(bom['components'][0]['part_number'],'B')
                    self.assertEqual(bom['assembly']['inference_status'],'invalidated_by_bom_edit')
                    status,result=request('/api/reviews/transition',{'document_id':'sample','action':'submit','payload':bom},'editor-secret')
                    self.assertEqual(status,200)
                    status,_=request('/api/reviews/transition',{'document_id':'sample','action':'approve','revision':1},'editor-secret')
                    self.assertEqual(status,403)
                finally:
                    conn.close(); server.shutdown();server.server_close();thread.join()
