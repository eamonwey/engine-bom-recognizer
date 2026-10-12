import json
import os
import tempfile
import unittest
from PIL import Image
from engine_bom.agent_loop import AgentLoop, validate_bom_response, validate_issues_response
from engine_bom.providers import ProviderResponse, ProviderError
from engine_bom.corrections import apply_corrections, sha256
from engine_bom.evaluation.strict import evaluate_strict
from engine_bom.schema import BomDocument, BomComponent, _coerce_int
from engine_bom.hybrid_inspection import valid_bbox, inspect


class SequenceProvider:
    name = "test"
    def __init__(self, values):
        self.values = iter(values)
        self.calls = []
    def analyze(self, images, prompt):
        self.calls.append((len(images), prompt))
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return ProviderResponse(value, "test")


class TestAgent(unittest.TestCase):
    def test_bad_json_recovers(self):
        provider = SequenceProvider(["not JSON", '{"components":[]}'])
        result = AgentLoop(provider).run([Image.new("RGB", (32,32))], "read", validate_bom_response)
        self.assertEqual(result.status, "validated")
        self.assertEqual(len(result.events), 2)
        self.assertEqual(result.events[1]["strategy"], "contrast_enhancement")

    def test_exhaustion_is_not_success(self):
        provider = SequenceProvider(["bad"]*3)
        result = AgentLoop(provider).run([Image.new("RGB", (32,32))], "read", validate_bom_response)
        self.assertEqual(result.status, "needs_review")
        self.assertEqual(provider.calls[-1][0], 5)

    def test_auth_failure_not_prompt_retried(self):
        provider = SequenceProvider([ProviderError("HTTP 401")])
        with self.assertRaises(ProviderError):
            AgentLoop(provider).run([], "read", validate_bom_response)
        self.assertEqual(len(provider.calls),1)

    def test_wrong_shape_not_empty_success(self):
        _, errors = validate_bom_response('{"foo":1}')
        self.assertTrue(errors)

    def test_visual_evidence_required(self):
        _, errors = validate_issues_response('{"issues":[{"err_id":"ERR-05","message":"bad"}]}')
        self.assertTrue(errors)

    def test_visual_page_rejected(self):
        issue = {"err_id":"ERR-05","message":"bad","evidence":"view","source_page":2,"bbox":None}
        provider = SequenceProvider([json.dumps({"issues":[issue]}),json.dumps({"issues":[issue]})])
        report = inspect(provider, [Image.new("RGB",(10,10))], {}, [], [], [], {"max_attempts":1})
        self.assertEqual(report["visual_status"], "needs_review")
        self.assertFalse(any(i["origin"] == "vlm" for i in report["issues"]))

    def test_negative_quantity_not_made_positive(self):
        self.assertEqual(_coerce_int("-3件")[0], -3)

    def test_bbox_rejects_inverted(self):
        self.assertFalse(valid_bbox([.5,.1,.1,.4]))

    def test_equivalent_dimension_units_not_conflict(self):
        from engine_bom.inspect_rules import check_dimensions
        self.assertEqual(check_dimensions([{"tag":"length","value":"10.0mm"},
                                           {"tag":"length","value":"1cm"}]), [])

    def test_assembly_material_not_required(self):
        from engine_bom.inspect_rules import check_titleblock
        issues = check_titleblock({"material_applicable":False})
        self.assertFalse(any(i["err_id"] == "ERR-06" for i in issues))


class TestStrict(unittest.TestCase):
    def test_wrong_part_number_not_rescued_by_name(self):
        gt = BomDocument("g", "g.png", components=[BomComponent(part_number="A",name_en="bolt",quantity=1)])
        pred = BomDocument("g", "g.png", components=[BomComponent(part_number="B",name_en="bolt",quantity=1)])
        result = evaluate_strict(pred, gt)
        self.assertEqual(result["tp"],0)
        self.assertEqual(result["fields"]["quantity"]["accuracy"],0)

    def test_missing_row_in_field_denominator(self):
        a = BomComponent(part_number="A",quantity=1)
        b = BomComponent(part_number="B",quantity=2)
        result = evaluate_strict(BomDocument("g","g",components=[a]), BomDocument("g","g",components=[a,b]))
        self.assertEqual(result["fields"]["quantity"]["accuracy"], .5)

    def test_cli_missing_prediction_is_counted(self):
        from argparse import Namespace
        from engine_bom.cli import _cmd_evaluate
        with tempfile.TemporaryDirectory() as d:
            pred_dir, anno_dir = os.path.join(d,"pred"),os.path.join(d,"anno")
            os.makedirs(pred_dir); os.makedirs(anno_dir)
            with open(os.path.join(anno_dir,"g.json"),"w") as f:
                json.dump({"components":[{"part_number":"A","quantity":1}]},f)
            prefix = os.path.join(d,"report")
            self.assertEqual(_cmd_evaluate(Namespace(pred_dir=pred_dir,anno_dir=anno_dir,output_prefix=prefix)),0)
            with open(prefix+".report.json") as f:
                report = json.load(f)
            self.assertEqual(report["strict"]["fn"],1)
            self.assertEqual(report["missing_predictions"],["g"])


class TestCorrections(unittest.TestCase):
    def test_image_copy_and_audit(self):
        with tempfile.TemporaryDirectory() as d:
            source, output = os.path.join(d,"source.png"), os.path.join(d,"revision.png")
            Image.new("RGB",(400,200),"white").save(source)
            before = sha256(source)
            patch = {"approved":True,"source_page":1,"bbox":[.1,.1,.7,.4],"new_text":"42"}
            journal = apply_corrections(source,output,[patch],"tester")
            self.assertEqual(before,sha256(source))
            self.assertNotEqual(before,sha256(output))
            self.assertTrue(os.path.exists(output+".audit.json"))
            self.assertEqual(journal["reviewer"],"tester")

    def test_unapproved_correction_rejected(self):
        with self.assertRaises(ValueError):
            apply_corrections("x.png","y.png",[{"approved":False}],"tester")

    def test_pdf_replacement_preserves_original(self):
        import fitz
        with tempfile.TemporaryDirectory() as d:
            source, output = os.path.join(d,"source.pdf"), os.path.join(d,"revision.pdf")
            doc = fitz.open()
            page = doc.new_page(width=400,height=200)
            page.insert_text((50,50),"41",fontsize=12)
            doc.save(source)
            doc.close()
            before = sha256(source)
            patch = {"approved":True,"source_page":1,"bbox":[.1,.15,.4,.35],"old_text":"41","new_text":"42"}
            apply_corrections(source,output,[patch],"tester")
            self.assertEqual(before,sha256(source))
            with fitz.open(output) as revised:
                self.assertIn("42", revised[0].get_text())
                self.assertNotIn("41", revised[0].get_text())
