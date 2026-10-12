import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from engine_bom.evaluation.validation import check_manifest,review_consensus,score_defects
from engine_bom.ingestion import load_document,IngestionError


class ValidationProtocolTests(unittest.TestCase):
    def test_printed_bad_quantity_is_evidence_not_loop_failure(self):
        from engine_bom.agent_loop import validate_bom_response
        components,errors=validate_bom_response('{"components":[{"part_number":"A","quantity":0},{"part_number":"A","quantity":-1}]}')
        self.assertFalse(errors)
        self.assertEqual([c.quantity for c in components],[0,-1])

    def test_pipeline_preserves_printed_numbers_and_repeated_rows(self):
        from PIL import Image
        from engine_bom.pipeline import BomPipeline
        from engine_bom.config import DEFAULT_CONFIG,deep_merge
        from engine_bom.agent_loop import AgentLoop
        from engine_bom.providers.base import ProviderResponse
        class Provider:
            def analyze(self,images,prompt):
                return ProviderResponse(raw_text='{"components":[{"item_no":9,"part_number":"A","name_en":"BOLT","quantity":0},{"item_no":3,"part_number":"A","name_en":"BOLT","quantity":5}]}')
            def describe(self):return {"provider":"test"}
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"drawing.png";Image.new("RGB",(100,100),"white").save(str(path))
            cfg=deep_merge(DEFAULT_CONFIG,{"provider":{"name":"mock"},"recognition":{"prompt_version":"v3"},"output":{"dir":tmp,"formats":["json"]}})
            pipeline=BomPipeline(cfg,tmp);pipeline.provider=Provider();pipeline.agent=AgentLoop(pipeline.provider)
            result=pipeline.process_file(str(path))
            self.assertEqual(result.status,"ok",result.errors)
            self.assertEqual([c.item_no for c in result.bom.components],[9,3])
            self.assertEqual([c.quantity for c in result.bom.components],[0,5])
            self.assertTrue(any("数量非正数" in s for s in result.bom.validation_issues))

    def test_missing_prediction_is_fn(self):
        score=score_defects([],[{"err_id":"ERR-01","source_page":1,"bbox":[.1,.1,.2,.2]}])
        self.assertEqual(score["fn"],1)

    def test_duplicate_detections_penalized_separately(self):
        g={"err_id":"ERR-08","source_page":1,"bbox":[.1,.1,.2,.2]}
        self.assertEqual(score_defects([g,g],[g])["fp"],1)

    def test_clean_false_alarm(self):
        self.assertTrue(score_defects([{"err_id":"ERR-08"}],[])["negative_false_alarm"])

    def test_localization_not_equal_to_type_match(self):
        p={"err_id":"ERR-01","source_page":1,"bbox":[.8,.8,.9,.9]}
        g=dict(p,bbox=[.1,.1,.2,.2])
        result=score_defects([p],[g])
        self.assertEqual(result["tp"],1);self.assertEqual(result["localized_tp"],0)

    def test_consensus_requires_two_real_independent_reviewers(self):
        case={"id":"x","input_sha256":"sha"}
        one={"case_id":"x","input_sha256":"sha","reviewer":"Alice","reviewer_kind":"human",
             "independent":True,"status":"approved","reviewed_at":"2026-09-17","components":[],"empty_confirmed":True}
        self.assertEqual(review_consensus(case,[one,dict(one,reviewer="alice")])["status"],"pending")
        self.assertEqual(review_consensus(case,[one,dict(one,reviewer="Bob",reviewer_kind="ai")])["status"],"pending")
        self.assertEqual(review_consensus(case,[one,dict(one,reviewer="Bob",independent=False)])["status"],"pending")
        self.assertEqual(review_consensus(case,[one,dict(one,reviewer="Bob")])["status"],"approved")

    def test_stale_review_rejected(self):
        case={"id":"x","input_sha256":"new"}
        record={"case_id":"x","input_sha256":"old","reviewer_kind":"human","independent":True,
                "status":"approved","reviewed_at":"date","components":[],"reviewer":"A"}
        self.assertEqual(review_consensus(case,[record,dict(record,reviewer="B")])["status"],"pending")

    def test_disagreement_not_averaged(self):
        case={"id":"x","input_sha256":"sha"}
        record={"case_id":"x","input_sha256":"sha","reviewer_kind":"human","independent":True,
                "status":"approved","reviewed_at":"date","components":[{"part_number":"A","quantity":1,"source_page":2}],"reviewer":"A"}
        other=dict(record,reviewer="B",components=[{"part_number":"A","quantity":2,"source_page":2}])
        self.assertEqual(review_consensus(case,[record,other])["status"],"disagreement")

    def test_hash_change_and_group_leakage_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"input").write_bytes(b"a");(root/"label").write_bytes(b"b")
            c={"id":"x","group_id":"part","split":"test","input":"input","annotation":"label",
                "input_sha256":hashlib.sha256(b"a").hexdigest(),"annotation_sha256":hashlib.sha256(b"b").hexdigest()}
            self.assertFalse(check_manifest(root,{"cases":[c]}))
            self.assertTrue(check_manifest(root,{"cases":[c,dict(c,id="y",split="train")]}))
            (root/"input").write_bytes(b"changed")
            self.assertTrue(check_manifest(root,{"cases":[c]}))

    def test_3d_only_pdf_rejected(self):
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"only3d.pdf"
            doc=fitz.open();page=doc.new_page();xref=doc.get_new_xref()
            doc.update_object(xref,"<< /Type /Annot /Subtype /3D /Rect [0 0 100 100] >>")
            doc.xref_set_key(page.xref,"Annots","[%d 0 R]"%xref)
            doc.save(str(path));doc.close()
            with self.assertRaises(IngestionError):load_document(str(path),{})


if __name__=="__main__":unittest.main()
