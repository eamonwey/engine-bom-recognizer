# -*- coding: utf-8 -*-
"""展开数量对账（reconcile_quantities）单元测试。

覆盖验收包暴露的两类错误：
  * H02 式重复节点：同一子件在 S210 下出现两个节点 → 展开量翻倍被检出；
  * H04 式明细栏印错：树正确（3×4=12）但明细栏写 11 → 冲突检出且保留原值。
"""
import unittest

from engine_bom.assembly import reconcile_quantities, validate_tree


def _node(id, parent, ci, qty):
    return {"id": id, "parent_id": parent, "component_index": ci,
            "quantity_per_parent": qty, "source_page": 1, "evidence": "图示"}


def _comps():
    # 仿 H02 双夹紧单元: A200=1, S210=2, P220=1, P211=4, B212=6
    return [
        {"part_number": "A200", "name_zh": "双夹紧单元", "quantity": 1},
        {"part_number": "S210", "name_zh": "夹紧子总成", "quantity": 2},
        {"part_number": "P220", "name_zh": "安装板", "quantity": 1},
        {"part_number": "P211", "name_zh": "夹爪", "quantity": 4},
        {"part_number": "B212", "name_zh": "内六角螺钉", "quantity": 6},
    ]


def _clean_tree():
    return {"nodes": [
        _node("root", None, 0, None),
        _node("n1", "root", 1, 2),
        _node("n2", "root", 2, 1),
        _node("n3", "n1", 3, 2),
        _node("n4", "n1", 4, 3),
    ]}


class ReconcileQuantitiesTest(unittest.TestCase):
    def test_clean_tree_no_conflicts(self):
        self.assertEqual(reconcile_quantities(_clean_tree(), _comps()), [])

    def test_duplicate_occurrence_detected(self):
        """H02 式: P211/B212 各拆成两个重复节点 → 展开量 8/12 ≠ 4/6。"""
        tree = {"nodes": _clean_tree()["nodes"] + [
            _node("n5", "n1", 3, 2),
            _node("n6", "n1", 4, 3),
        ]}
        conflicts = reconcile_quantities(tree, _comps())
        by_pn = {c["part_number"]: c for c in conflicts}
        self.assertEqual(set(by_pn), {"P211", "B212"})
        self.assertEqual(by_pn["P211"]["exploded_quantity"], 8)
        self.assertEqual(by_pn["P211"]["printed_quantity"], 4)
        self.assertEqual(by_pn["B212"]["exploded_quantity"], 12)
        self.assertTrue(all(c["err_id"] == "ERR-08" for c in conflicts))
        self.assertTrue(validate_tree(tree, _comps()) is not None)  # 结构校验不拦截

    def test_printed_quantity_mismatch_preserved(self):
        """H04 式: 树正确展开 3×4=12，明细栏印 11 → 检出冲突，printed 保留 11。"""
        comps = [
            {"part_number": "A400", "name_zh": "三夹紧单元", "quantity": 1},
            {"part_number": "S410", "name_zh": "夹紧子总成", "quantity": 3},
            {"part_number": "P411", "name_zh": "夹爪", "quantity": 6},
            {"part_number": "B412", "name_zh": "内六角螺钉", "quantity": 11},
        ]
        tree = {"nodes": [
            _node("root", None, 0, None),
            _node("n1", "root", 1, 3),   # S410: 1×3=3 ✓
            _node("n2", "n1", 2, 2),     # P411: 3×2=6 ✓
            _node("n3", "n1", 3, 4),     # B412: 3×4=12 vs 印 11
        ]}
        conflicts = reconcile_quantities(tree, comps)
        self.assertEqual(len(conflicts), 1)
        c = conflicts[0]
        self.assertEqual(c["err_id"], "ERR-08")
        self.assertEqual(c["part_number"], "B412")
        self.assertEqual(c["printed_quantity"], 11)
        self.assertEqual(c["exploded_quantity"], 12)
        self.assertIn("明细栏为 11", c["message"])

    def test_shared_part_two_paths_sums_correctly(self):
        """仿 H03: 同一行两条父路径, 展开量相加后与明细一致 → 不误报。"""
        comps = [
            {"part_number": "A300", "name_zh": "机架", "quantity": 1},
            {"part_number": "S310", "name_zh": "驱动子总成", "quantity": 2},
            {"part_number": "S320", "name_zh": "导向子总成", "quantity": 1},
            {"part_number": "B330", "name_zh": "六角螺栓", "quantity": 8},
        ]
        tree = {"nodes": [
            _node("root", None, 0, None),
            _node("n1", "root", 1, 2),
            _node("n2", "root", 2, 1),
            _node("n3", "n1", 3, 2),   # 2×2=4
            _node("n4", "n2", 3, 4),   # 1×4=4 → 合计 8 ✓
        ]}
        self.assertEqual(reconcile_quantities(tree, comps), [])

    def test_unknown_quantity_branch_skipped(self):
        """每父用量未知的分支无法对账 → 该行不判定、不误报。"""
        comps = _comps()
        comps[3]["quantity"] = 999  # 若误判必然冲突
        tree = {"nodes": _clean_tree()["nodes"][:4] + [_node("n4", "n1", 4, 3)]}
        tree["nodes"][3]["quantity_per_parent"] = None  # P211 分支未知
        self.assertEqual(reconcile_quantities(tree, comps), [])

    def test_missing_row_quantity_skipped(self):
        comps = _comps()
        del comps[3]["quantity"]
        self.assertEqual(reconcile_quantities(_clean_tree(), comps), [])


if __name__ == "__main__":
    unittest.main()
