# -*- coding: utf-8 -*-
"""tree_metrics（装配父子关系评测）单元测试。"""
import os
import unittest

from engine_bom.evaluation.tree_metrics import (
    compare_edges, evaluate_assembly_case, nested_to_edges, tree_edges)


def _comps(*pns):
    return [{"part_number": pn, "name_zh": "件" + pn} for pn in pns]


H03_COMPONENTS = _comps("A300", "S310", "S320", "P311", "P321", "B330")

H03_NODES = [
    {"id": "root", "parent_id": None, "component_index": 0, "quantity_per_parent": None},
    {"id": "n1", "parent_id": "root", "component_index": 1, "quantity_per_parent": 2},
    {"id": "n2", "parent_id": "n1", "component_index": 3, "quantity_per_parent": 1},
    {"id": "n3", "parent_id": "n1", "component_index": 5, "quantity_per_parent": 2},
    {"id": "n4", "parent_id": "root", "component_index": 2, "quantity_per_parent": 1},
    {"id": "n5", "parent_id": "n4", "component_index": 4, "quantity_per_parent": 2},
    {"id": "n6", "parent_id": "n4", "component_index": 5, "quantity_per_parent": 4},
]


def _expected_h03():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "data", "acceptance",
                        "assembly_hierarchy_20260926", "H03.expected.json")
    if not os.path.exists(path):
        return None
    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TreeEdgesTest(unittest.TestCase):
    def test_edges_from_nodes(self):
        edges = tree_edges(H03_NODES, H03_COMPONENTS)
        self.assertEqual(edges["relations"][("A300", "S310")], 1)
        self.assertEqual(edges["relations"][("S310", "B330")], 1)
        self.assertEqual(edges["relations"][("S320", "B330")], 1)
        self.assertEqual(edges["qtys"][("S310", "B330")], [2])
        self.assertEqual(edges["qtys"][("S320", "B330")], [4])
        self.assertEqual(edges["root_keys"], ["A300"])

    def test_shared_part_two_parents_distinct_edges(self):
        """H03 共享螺栓: 同一 B330 行必须拆成两条不同父路径的边。"""
        edges = tree_edges(H03_NODES, H03_COMPONENTS)
        self.assertEqual(edges["relations"][("A300", "B330")], 0)
        self.assertEqual(sum(n for (p, _), n in edges["relations"].items()
                             if _ == "B330"), 2)

    def test_nested_to_edges_as1_style(self):
        tree = {"name": "as1", "qty": 1, "children": [
            {"name": "bracket-assembly", "qty": 2, "children": [
                {"name": "bolt", "qty": 3, "children": []}]}]}
        edges = nested_to_edges(tree)
        self.assertEqual(edges["relations"], {("as1", "bracket-assembly"): 1,
                                              ("bracket-assembly", "bolt"): 1})
        self.assertEqual(edges["qtys"][("as1", "bracket-assembly")], [2])
        self.assertEqual(edges["qtys"][("bracket-assembly", "bolt")], [3])


class CompareEdgesTest(unittest.TestCase):
    def setUp(self):
        self.gt = tree_edges(H03_NODES, H03_COMPONENTS)

    def test_perfect_prediction(self):
        pred = tree_edges(H03_NODES, H03_COMPONENTS)
        result = compare_edges(self.gt, pred)
        self.assertEqual(result["f1"], 1.0)
        self.assertEqual(result["qty_accuracy"], 1.0)
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["extra"], [])

    def test_wrong_parent_detected(self):
        """键挂错父件（B330 全挂 S310）→ 关系 F1 下降并给出明细。"""
        wrong = [dict(n) for n in H03_NODES]
        for n in wrong:
            if n["id"] == "n6":
                n["parent_id"] = "n1"
                n["quantity_per_parent"] = 6  # 2+4 合并
        pred = tree_edges(wrong, H03_COMPONENTS)
        result = compare_edges(self.gt, pred)
        self.assertLess(result["f1"], 1.0)
        self.assertIn("S320 → B330 ×1", result["missing"])
        self.assertTrue(any("S320" in m for m in result["extra"]) or result["extra"])

    def test_qty_error_on_correct_relation(self):
        wrong = [dict(n) for n in H03_NODES]
        for n in wrong:
            if n["id"] == "n3":
                n["quantity_per_parent"] = 8  # 把 BOM 总量当每父用量
        pred = tree_edges(wrong, H03_COMPONENTS)
        result = compare_edges(self.gt, pred)
        self.assertEqual(result["f1"], 1.0)          # 关系仍全对
        self.assertAlmostEqual(result["qty_accuracy"], 5 / 6, places=3)
        self.assertTrue(result["qty_mistakes"])

    def test_extra_root(self):
        flat = [dict(n, parent_id=None, quantity_per_parent=None) for n in H03_NODES]
        pred = tree_edges(flat, H03_COMPONENTS)
        result = compare_edges(self.gt, pred)
        self.assertEqual(result["n_hit"], 0)         # 平铺零信息树应得 0 分
        self.assertEqual(result["recall"], 0.0)


class EvaluateCaseTest(unittest.TestCase):
    def test_evaluate_h03_case_against_expected(self):
        expected = _expected_h03()
        if expected is None:
            self.skipTest("验收包不在本机")
        score = evaluate_assembly_case(
            {"nodes": [dict(n) for n in H03_NODES], "max_depth": 3},
            H03_COMPONENTS, expected)
        self.assertEqual(score["relations"]["f1"], 1.0)
        self.assertEqual(score["expected_node_count"], 7)
        self.assertEqual(score["bom_missing"], [])
        self.assertEqual(score["bom_extra"], [])

    def test_unresolved_and_unverified_counted(self):
        expected = {"case_id": "X",
                    "components": H03_COMPONENTS,
                    "assembly": {"nodes": H03_NODES},
                    "expected_node_count": 7, "max_depth": 3}
        partial = {"nodes": H03_NODES[:4], "unverified_nodes": [{"id": "n9"}],
                   "unresolved_component_indices": [4, 5], "max_depth": 2}
        score = evaluate_assembly_case(partial, H03_COMPONENTS, expected)
        self.assertEqual(score["unresolved_component_indices"], [4, 5])
        self.assertEqual(score["node_count_unverified"], 1)
        self.assertLess(score["relations"]["recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
