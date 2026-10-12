# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from engine_bom.config import DEFAULT_CONFIG, deep_merge
from engine_bom.pipeline import BomPipeline


def _make_config(out_dir, mode="per_page"):
    return deep_merge(DEFAULT_CONFIG, {
        "provider": {"name": "mock"},
        "recognition": {"mode": mode},
        "output": {"dir": out_dir, "formats": ["json", "csv"]},
        "knowledge": {"enabled": False},
    })


def _make_image(path):
    Image.new("RGB", (400, 300), "white").save(path)


class TestPipelineMock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        img_path = os.path.join(self.tmp.name, "sample_doc.png")
        _make_image(img_path)
        self.img_path = img_path

    def tearDown(self):
        self.tmp.cleanup()

    def test_process_image_per_page(self):
        pipeline = BomPipeline(_make_config(self.tmp.name))
        result = pipeline.process_file(self.img_path)
        self.assertEqual(result.status, "ok", result.errors)
        self.assertIsNotNone(result.bom)
        # Mock 故意漏掉第 12 项（水泵）
        self.assertEqual(result.bom.total_components, 11)
        self.assertTrue(any(os.path.isfile(p) for p in result.outputs if p.endswith(".json")))
        pred_json = os.path.join(self.tmp.name, "sample_doc.json")
        with open(pred_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["model_info"]["provider"], "mock")
        self.assertEqual(len(data["components"]), 11)
        trace = os.path.join(self.tmp.name, "traces", "sample_doc.trace.json")
        self.assertTrue(os.path.isfile(trace))

    def test_process_whole_doc_mode(self):
        pipeline = BomPipeline(_make_config(self.tmp.name, mode="whole_doc"))
        result = pipeline.process_file(self.img_path)
        self.assertEqual(result.status, "ok", result.errors)
        self.assertEqual(result.bom.model_info["recognition_mode"], "whole_doc")

    def test_missing_file(self):
        pipeline = BomPipeline(_make_config(self.tmp.name))
        result = pipeline.process_file(os.path.join(self.tmp.name, "nope.png"))
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.errors)


if __name__ == "__main__":
    unittest.main()
