import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from engine_bom import webapp
from engine_bom.review_workflow import ReviewStore


class P1Regressions(unittest.TestCase):
    def test_same_named_versions_keep_distinct_content(self):
        with tempfile.TemporaryDirectory() as folder:
            form={'before':webapp._UploadedPart('drawing.txt',b'old TC4'), 'after':webapp._UploadedPart('drawing.txt',b'new TC11')}
            before=webapp._save_upload(folder,form,'before')
            after=webapp._save_upload(folder,form,'after')
            self.assertNotEqual(before,after)
            with open(before,'rb') as handle: self.assertEqual(handle.read(),b'old TC4')
            with open(after,'rb') as handle: self.assertEqual(handle.read(),b'new TC11')

    def test_review_cannot_approve_different_visible_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ReviewStore(os.path.join(folder,'review.db'))
            store.transition('a','submit',{'id':'a','role':'editor'},payload={'quantity':1})
            with self.assertRaises(ValueError):
                store.transition('a','review',{'id':'b','role':'reviewer'},1,{'quantity':99})
            self.assertEqual(store.get('a')['state'],'submitted')

    def test_concurrent_log_appends_are_lossless(self):
        with tempfile.TemporaryDirectory() as folder:
            path=os.path.join(folder,'log.json')
            with ThreadPoolExecutor(max_workers=12) as pool:
                list(pool.map(lambda i:webapp._append_log(path,{'sequence':i}),range(120)))
            with open(path,encoding='utf-8') as handle: records=json.load(handle)
            self.assertEqual(sorted(r['sequence'] for r in records),list(range(120)))

    def test_corrupt_log_is_not_silently_erased(self):
        with tempfile.TemporaryDirectory() as folder:
            path=os.path.join(folder,'log.json')
            with open(path,'w') as handle: handle.write('{broken')
            with self.assertRaises(ValueError): webapp._append_log(path,{'new':1})
            with open(path) as handle: self.assertEqual(handle.read(),'{broken')

    def test_review_saves_update_task_file(self):
        with tempfile.TemporaryDirectory() as folder:
            for kind in ('doc','bom'):
                result=({'extraction':{'tech_params':[]}} if kind=='doc' else {'bom':{'components':[{'part_number':'A'}],'model_info':{'pages':1}}})
                job={'kind':kind,'status':'done','dir':folder,'result':result}
                target=os.path.join(folder,'result.json')
                with open(target,'w') as handle: json.dump(result,handle)
                handler=object.__new__(webapp.Handler)
                handler._json=lambda *a,**k:None
                payload=({'job_id':'j','file_name':'d','extraction':{'tech_params':[{'name':'new'}]}} if kind=='doc' else {'job_id':'j','reviewer':'tester','assembly':{'nodes':[{'id':'n','parent_id':None,'component_index':0,'source_page':1,'evidence':'view'}]}})
                handler._read_json_body=lambda:payload
                with patch.object(webapp,'_jobs',{'j':job}),patch.object(webapp,'DATA_DIR',folder),patch.object(webapp,'REVIEWLOG_PATH',os.path.join(folder,'log.json')):
                    if kind=='doc': handler._api_doc_save()
                    else: handler._api_assembly_save()
                with open(target,encoding='utf-8') as handle: persisted=json.load(handle)
                self.assertEqual(persisted,job['result'])

    def test_approval_requires_visible_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ReviewStore(os.path.join(folder,'review.db'))
            store.transition('a','submit',{'id':'a','role':'editor'},payload={'x':1})
            with self.assertRaises(ValueError):
                store.transition('a','review',{'id':'b','role':'reviewer'},1)
            store.transition('a','review',{'id':'b','role':'reviewer'},1,{'x':1})
            with self.assertRaises(ValueError):
                store.transition('a','approve',{'id':'c','role':'approver'},2,{'x':2})
            self.assertEqual(store.get('a')['state'],'reviewed')
            result=store.transition('a','approve',{'id':'c','role':'approver'},2,{'x':1})
            self.assertEqual(result['state'],'approved')

    def test_failed_replace_preserves_log_and_removes_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            path=os.path.join(folder,'log.json')
            webapp._append_log(path,{'sequence':0})
            with open(path,'rb') as handle: original=handle.read()
            with patch.object(webapp.os,'replace',side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError): webapp._append_log(path,{'sequence':1})
            with open(path,'rb') as handle: self.assertEqual(handle.read(),original)
            self.assertEqual(os.listdir(folder),['log.json'])

    def test_failed_result_write_does_not_publish_new_memory_state(self):
        with tempfile.TemporaryDirectory() as folder:
            job={'kind':'doc','status':'done','dir':folder,'result':{'extraction':{'old':1}}}
            with patch.object(webapp,'_jobs',{'j':job}),patch.object(webapp,'_atomic_json',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    webapp._save_result_section('j','doc','extraction',{'new':1})
            self.assertEqual(job['result'],{'extraction':{'old':1}})

if __name__=='__main__': unittest.main()
