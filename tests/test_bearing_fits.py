# -*- coding: utf-8 -*-
"""轴承型号 ↔ 配合尺寸一致性规则的回归测试。

场景来源：减速器图纸实测中，用户将 6206 座孔 Ø62 改为 Ø60，旧规则链只能给出
"一组值不一致"的模糊分组；本规则按明细栏轴承型号推算标准配合尺寸，单点指认。
"""
import unittest

from engine_bom.inspect_rules import _bearing_expected_dims, check_bearing_fits

_COMPS = [
    {"name_zh": "齿轮箱体"},
    {"name_zh": "轴承6206", "part_number": "GB/T 276"},
    {"name_zh": "轴承6204", "part_number": "GB/T 276"},
    {"name_zh": "齿轮轴"},
    {"name_zh": "输出轴"},
]


def _dim(value, tag, view="A-A剖视"):
    return {"value": value, "tag": tag, "view": view}


class TestBearingExpectedDims(unittest.TestCase):
    def test_known_models(self):
        self.assertEqual(_bearing_expected_dims("6206"), (30, 62))
        self.assertEqual(_bearing_expected_dims("6204"), (20, 47))
        self.assertEqual(_bearing_expected_dims("6202"), (15, 35))
        self.assertEqual(_bearing_expected_dims("7507"), (35, 72))

    def test_unknown_series_partial(self):
        # 未知系列的轴承只推算内径（末两位×5），外径返回 None
        self.assertEqual(_bearing_expected_dims("6241"), (41 * 5, None))


class TestBearingFitConsistency(unittest.TestCase):
    def test_correct_fits_no_finding(self):
        dims = [
            _dim("Ø 62 J7", "高速轴轴承位直径"),
            _dim("Ø62J7", "轴承座孔直径"),
            _dim("Ø47 H9/h9", "轴承座孔直径"),
            _dim("Ø30k6", "低速轴轴承位直径"),
            _dim("Ø20k6", "高速轴轴承位直径"),
        ]
        self.assertEqual(check_bearing_fits(_COMPS, dims), [])

    def test_tampered_seat_single_point_accusation(self):
        # 用户实测场景：6206 座孔 62 被改为 60 —— 应单点指认 60 并给出应为 62
        dims = [
            _dim("Ø 62 J7", "高速轴轴承位直径"),
            dict(_dim("Ø60H9", "轴承座孔直径"),bearing_component_index=1,bearing_interface='outer',association_evidence='尺寸界线明确指向件2轴承外圈直接配合的箱体孔'),
            _dim("Ø47H9/h9", "轴承座孔直径"),
            _dim("Ø30k6", "低速轴轴承位直径"),
        ]
        issues = check_bearing_fits(_COMPS, dims)
        self.assertEqual(len(issues), 1)
        self.assertIn("标注 60 mm", issues[0]["message"])
        self.assertIn("6206", issues[0]["message"])
        self.assertIn("应为 62 mm", issues[0]["message"])

    def test_no_bearings_in_bom_returns_empty(self):
        comps = [{"name_zh": "齿轮箱体"}]
        dims = [_dim("Ø60H9/h9", "轴承座孔直径")]
        self.assertEqual(check_bearing_fits(comps, dims), [])

    def test_unrelated_tagged_dims_ignored(self):
        # 带"轴承"字样的名称（如 轴承盖）不产生型号；无型号则规则静默
        comps = [{"name_zh": "轴承盖"}]
        dims = [_dim("Ø60H9/h9", "轴承座孔直径")]
        self.assertEqual(check_bearing_fits(comps, dims), [])

    def test_non_seat_dims_skipped(self):
        dims = [_dim("Ø52h9", "低速轴输出端直径"), _dim("174", "总体高度")]
        self.assertEqual(check_bearing_fits(_COMPS, dims), [])


if __name__ == "__main__":
    unittest.main()
