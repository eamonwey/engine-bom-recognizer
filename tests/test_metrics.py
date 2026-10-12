# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_bom.evaluation.metrics import (evaluate_corpus, evaluate_document,
                                           match_components, render_markdown_report)
from engine_bom.schema import BomComponent, BomDocument


def _doc(doc_id, comps):
    return BomDocument(document_id=doc_id, components=comps)


GT = _doc("d1", [
    BomComponent(item_no=1, part_number="X1", name_zh="活塞", specification="S1", quantity=2),
    BomComponent(item_no=2, part_number="Y1", name_zh="连杆", specification="S2", quantity=5),
    BomComponent(item_no=3, part_number="Z1", name_zh="曲轴", quantity=1),
])
PRED = _doc("d1", [
    BomComponent(item_no=1, part_number="x1", name_zh="活塞", specification="s1", quantity=2),
    BomComponent(item_no=2, part_number="", name_zh="连杆", specification="", quantity=4),
    BomComponent(item_no=3, part_number="FP1", name_zh="涡轮增压器"),
])


class TestMatching(unittest.TestCase):
    def test_pn_match_normalized(self):
        pairs = match_components(PRED.components, GT.components)
        matched_gt = {j for _, j in pairs}
        self.assertIn(0, matched_gt)  # x1 == X1 归一化后精确匹配
        self.assertIn(1, matched_gt)  # 名称匹配
        self.assertNotIn(2, matched_gt)

    def test_name_fuzzy(self):
        pred = [BomComponent(name_zh="进气 门")]
        gt = [BomComponent(name_zh="进气门")]
        self.assertEqual(match_components(pred, gt), [(0, 0)])


class TestEvaluateDocument(unittest.TestCase):
    def setUp(self):
        self.res = evaluate_document(PRED, GT)

    def test_detection_metrics(self):
        self.assertEqual(self.res["n_gt"], 3)
        self.assertEqual(self.res["n_pred"], 3)
        self.assertEqual(self.res["n_matched"], 2)
        self.assertAlmostEqual(self.res["precision"], 2 / 3, places=4)
        self.assertAlmostEqual(self.res["recall"], 2 / 3, places=4)
        self.assertEqual(self.res["missed_gt"], ["曲轴"])
        self.assertEqual(self.res["false_positives"], ["涡轮增压器"])

    def test_field_metrics(self):
        pn = self.res["fields"]["part_number"]
        self.assertEqual((pn["correct"], pn["total"]), (1, 2))  # x1 对; 连杆 pn 缺失错
        qty = self.res["fields"]["quantity"]
        self.assertEqual((qty["correct"], qty["total"]), (1, 2))  # 4 != 5
        spec = self.res["fields"]["specification"]
        self.assertEqual((spec["correct"], spec["total"]), (1, 2))
        # 字段总准确率: 活塞 4/4 全对, 连杆 1/4（仅名称对） -> 5/8
        self.assertAlmostEqual(self.res["field_accuracy"], 5 / 8, places=4)
        self.assertFalse(self.res["exact_bom"])

    def test_perfect(self):
        res = evaluate_document(GT, GT)
        self.assertTrue(res["exact_bom"])
        self.assertEqual(res["f1"], 1.0)


class TestCorpus(unittest.TestCase):
    def test_aggregate_and_report(self):
        agg = evaluate_corpus([self_res()], meta={"experiment": "t", "run": "r", "model": "m",
                                                  "prompt_version": "v1"})
        det = agg["component_detection"]
        self.assertEqual(det["total_matched"], 2)
        self.assertAlmostEqual(det["micro_precision"], 2 / 3, places=4)
        md = render_markdown_report(agg)
        self.assertIn("BOM 识别评测报告", md)
        self.assertIn("漏检元器件", md)
        self.assertIn("曲轴", md)

    def test_empty(self):
        agg = evaluate_corpus([])
        self.assertEqual(agg["n_documents"], 0)


def self_res():
    return evaluate_document(PRED, GT)


if __name__ == "__main__":
    unittest.main()
