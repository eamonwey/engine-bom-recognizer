# -*- coding: utf-8 -*-
"""2026-09-28 减速器图纸实测暴露问题的回归测试：
weight 字段贯通、国标代号判重不误报、标准号-名称一致性校验。
"""
import csv
import os
import tempfile
import unittest

from engine_bom.export import write_csv
from engine_bom.schema import (
    BomComponent, check_standard_references, component_from_dict,
    components_from_payload, merge_components, validate_components,
)


class TestWeightField(unittest.TestCase):
    def test_weight_alias_and_coercion(self):
        comps, _ = components_from_payload([
            {"item_no": 1, "name_zh": "齿轮箱体", "weight": 3836},
            {"item_no": 2, "name_zh": "螺钉", "重量": "1.8"},
        ])
        self.assertEqual(comps[0].weight, 3836.0)
        self.assertEqual(comps[1].weight, 1.8)

    def test_weight_in_csv_export(self):
        bom = type("B", (), {})()  # 用真实 BomDocument 结构更直接
        from engine_bom.schema import BomDocument
        doc = BomDocument(document_id="t")
        c, _ = component_from_dict({"item_no": 1, "name_zh": "齿轮箱体", "weight": 3836})
        c2, _ = component_from_dict({"item_no": 2, "name_zh": "螺钉", "weight": 1.8})
        doc.components = [c, c2]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bom.csv")
            write_csv(doc, path)
            with open(path, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        self.assertIn("重量(g)", rows[0])
        self.assertEqual(rows[1][rows[0].index("重量(g)")], "3836")
        self.assertEqual(rows[2][rows[0].index("重量(g)")], "1.8")

    def test_merge_fills_missing_weight(self):
        p1 = [BomComponent(part_number="A-1", name_zh="箱体")]
        p2 = [BomComponent(part_number="A-1", name_zh="箱体", weight=2519)]
        merged, _ = merge_components([p1, p2])
        self.assertEqual(merged[0].weight, 2519.0)


class TestDuplicateRule(unittest.TestCase):
    def test_standard_code_reuse_not_flagged(self):
        # 同一国标号下不同规格是正常 BOM 行（减速器图纸实测的误报场景）
        comps = [
            BomComponent(part_number="GB/T 1276", name_zh="轴承6206", quantity=2),
            BomComponent(part_number="GB/T 1276", name_zh="轴承6204", quantity=2),
            BomComponent(part_number="GB/T 41", name_zh="螺母M8", quantity=5),
            BomComponent(part_number="GB/T 41", name_zh="螺母M10", quantity=1),
        ]
        issues = validate_components(comps)
        self.assertFalse(any("件号重复" in i for i in issues))

    def test_standard_code_same_name_flagged(self):
        comps = [
            BomComponent(part_number="GB/T 818", name_zh="螺钉M4X10", quantity=4),
            BomComponent(part_number="GB/T 818", name_zh="螺钉M4X10", quantity=4),
        ]
        issues = validate_components(comps)
        self.assertTrue(any("件号重复" in i for i in issues))

    def test_own_drawing_number_conflict_flagged(self):
        # 企业自编号不同名称仍视为冲突
        comps = [
            BomComponent(part_number="ENG-1", name_zh="活塞"),
            BomComponent(part_number="eng 1", name_zh="活塞环"),
        ]
        issues = validate_components(comps)
        self.assertTrue(any("件号重复" in i for i in issues))


class TestStandardReferences(unittest.TestCase):
    def test_reducer_misreads_flagged(self):
        # 减速器图纸实测出现的 4 处代号错误中的 3 处可确定性拦截
        comps = [
            BomComponent(part_number="GB/T 1276", name_zh="轴承6206"),
            BomComponent(part_number="GB/T 1276", name_zh="轴承6204"),
            BomComponent(part_number="GB/T 15780", name_zh="螺栓M8x30"),
            BomComponent(part_number="GB/T 1117", name_zh="圆锥销6X15"),
        ]
        issues = check_standard_references(comps)
        self.assertEqual(len(issues), 4)
        self.assertTrue(all("标准号引用疑似错误" in i for i in issues))
        self.assertTrue(any("氟化铵" in i for i in issues))
        self.assertTrue(any("铣刀" in i for i in issues))
        self.assertTrue(any("竹材" in i for i in issues))
        # 建议里给出正确标准
        self.assertTrue(any("GB/T 276" in i for i in issues))
        self.assertTrue(any("GB/T 5780" in i for i in issues))
        self.assertTrue(any("GB/T 117" in i for i in issues))

    def test_correct_codes_not_flagged(self):
        comps = [
            BomComponent(part_number="GB/T 276", name_zh="轴承6204"),
            BomComponent(part_number="GB/T 5780", name_zh="螺栓M8X65"),
            BomComponent(part_number="GB/T 41", name_zh="螺母M8"),
            BomComponent(part_number="GB/T 93", name_zh="弹性垫圈8"),
            BomComponent(part_number="GB/T 1096", name_zh="键10X22"),
            BomComponent(part_number="GB/T 13871.1", name_zh="油封28X47X7"),
            BomComponent(part_number="ZD10-001", name_zh="齿轮箱体"),
            BomComponent(name_zh="油标垫片"),  # 无代号
        ]
        self.assertEqual(check_standard_references(comps), [])

    def test_missing_name_skipped(self):
        comps = [BomComponent(part_number="GB/T 1276")]
        self.assertEqual(check_standard_references(comps), [])

    def test_issues_flow_through_validate(self):
        comps = [BomComponent(part_number="GB/T 1276", name_zh="轴承6206", quantity=2)]
        issues = validate_components(comps)
        self.assertTrue(any("标准号引用疑似错误" in i for i in issues))


class TestReviewFlags(unittest.TestCase):
    """行级“待核实”标记由确定性校验驱动（2026-09-28 中期改造）。"""

    def test_flags_attached_on_mismatch(self):
        comps = [
            BomComponent(part_number="GB/T 1276", name_zh="轴承6206", quantity=2),
            BomComponent(part_number="GB/T 276", name_zh="轴承6204", quantity=2),
        ]
        issues = validate_components(comps)
        self.assertTrue(comps[0].needs_review)
        self.assertTrue(any("标准号引用疑似错误" in r for r in comps[0].review_reasons))
        self.assertFalse(comps[1].needs_review)
        self.assertEqual(comps[1].review_reasons, [])

    def test_duplicate_flags_both_rows(self):
        comps = [
            BomComponent(part_number="GB/T 818", name_zh="螺钉M4X10", quantity=4),
            BomComponent(part_number="GB/T 818", name_zh="螺钉M4X10", quantity=4),
        ]
        validate_components(comps)
        self.assertTrue(comps[0].needs_review and comps[1].needs_review)
        self.assertTrue(all(any("件号重复" in r for r in c.review_reasons) for c in comps))

    def test_flags_roundtrip_through_payload(self):
        # 前端保存/导出再导入路径：needs_review/review_reasons 必须保真
        comps = [BomComponent(part_number="GB/T 1276", name_zh="轴承6206", quantity=2)]
        validate_components(comps)
        d = comps[0].to_dict()
        self.assertIn("needs_review", d)
        back, _ = components_from_payload([d])
        self.assertIs(back[0].needs_review, True)
        self.assertEqual(back[0].review_reasons, comps[0].review_reasons)
        # 字符串/中文布尔也能解析
        back2, _ = components_from_payload([{"name_zh": "x", "needs_review": "是", "review_reasons": "a；b"}])
        self.assertIs(back2[0].needs_review, True)
        self.assertEqual(back2[0].review_reasons, ["a；b"])

    def test_review_columns_in_csv(self):
        from engine_bom.schema import BomDocument
        doc = BomDocument(document_id="t")
        c = BomComponent(item_no=1, part_number="GB/T 1276", name_zh="轴承6206", quantity=2)
        c2 = BomComponent(item_no=2, part_number="GB/T 276", name_zh="轴承6204", quantity=2)
        doc.components = [c, c2]
        validate_components(doc.components)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bom.csv")
            write_csv(doc, path)
            with open(path, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        self.assertIn("待核实", rows[0])
        self.assertIn("核实原因", rows[0])
        i_flag = rows[0].index("待核实")
        i_reason = rows[0].index("核实原因")
        self.assertEqual(rows[1][i_flag], "是")
        self.assertIn("标准号引用疑似错误", rows[1][i_reason])
        self.assertEqual(rows[2][i_flag], "")

    def test_clean_rows_not_flagged(self):
        comps = [
            BomComponent(part_number="GB/T 276", name_zh="轴承6204", quantity=2),
            BomComponent(part_number="ZD10-001", name_zh="齿轮箱体", quantity=1),
        ]
        issues = validate_components(comps)
        self.assertEqual(issues, [])
        self.assertFalse(any(c.needs_review for c in comps))


class TestInspectionMerge(unittest.TestCase):
    """rule+vlm 发现合并：VLM 原样复述规则消息（英文字段名）时也必须合并。
    回归场景：qwen3-vl-plus 实测中 designer/date 各出现两条。"""

    def _rule(self, field):
        return {"err_id": "ERR-08", "type": "标题栏/明细栏错误", "severity": "高",
                "message": "标题栏必填字段缺失: %s" % field, "location": "标题栏",
                "suggestion": "按企业制图规范补全标题栏", "origin": "rule", "status": "needs_review",
                "finding_id": "rule-" + field}

    def _vlm_echo(self, field):
        return {"err_id": "ERR-08", "type": "标题栏/明细栏错误", "severity": "高",
                "message": "标题栏必填字段缺失: %s" % field, "location": "标题栏",
                "suggestion": "按企业制图规范补全标题栏", "origin": "vlm", "status": "needs_review",
                "source_page": 1}

    def test_vlm_verbatim_echo_merges(self):
        from engine_bom.hybrid_inspection import merge_findings
        merged = merge_findings([self._rule("designer"), self._rule("date")],
                                [self._vlm_echo("designer"), self._vlm_echo("date")])
        errs = sorted(m["message"] for m in merged if m["err_id"] == "ERR-08")
        self.assertEqual(len([m for m in merged if m["err_id"] == "ERR-08"]), 2)
        for m in merged:
            if m["err_id"] == "ERR-08":
                self.assertEqual(m["origin"], "rule+vlm")
                self.assertEqual(len(m["sources"]), 2)

    def test_chinese_wording_still_merges(self):
        from engine_bom.hybrid_inspection import merge_findings
        vlm = dict(self._vlm_echo("designer"),
                   message="标题栏设计签署栏未填写", location="标题栏")
        merged = merge_findings([self._rule("designer")], [vlm])
        self.assertEqual(len([m for m in merged if m["err_id"] == "ERR-08"]), 1)
        self.assertEqual(merged[0]["origin"], "rule+vlm")


class TestAllowRepeatedRows(unittest.TestCase):
    """preserve_printed_rows 模式下，同码同名的重复行合法（ZPT35 垫圈10×3 误报回归）。"""

    def _rows(self):
        return [
            BomComponent(item_no=4, part_number="GB/T 97.1", name_zh="垫圈10", quantity=6),
            BomComponent(item_no=18, part_number="GB/T 97.1", name_zh="垫圈10", quantity=3),
            BomComponent(item_no=25, part_number="GB/T 97.1", name_zh="垫圈10", quantity=6),
        ]

    def test_repeated_rows_allowed(self):
        issues = validate_components(self._rows(), allow_repeated_rows=True)
        self.assertFalse(any("件号重复" in i for i in issues))

    def test_repeated_rows_allowed_no_flags(self):
        comps = self._rows()
        validate_components(comps, allow_repeated_rows=True)
        self.assertFalse(any(c.needs_review for c in comps))

    def test_repeated_rows_still_flagged_by_default(self):
        issues = validate_components(self._rows())
        self.assertTrue(any("件号重复" in i for i in issues))

    def test_diff_name_conflict_even_when_allowed(self):
        comps = [
            BomComponent(part_number="ENG-1", name_zh="活塞"),
            BomComponent(part_number="ENG-1", name_zh="活塞环"),
        ]
        issues = validate_components(comps, allow_repeated_rows=True)
        self.assertTrue(any("件号重复" in i for i in issues))


class TestBalloonMismatch(unittest.TestCase):
    def test_missing_rows_detected(self):
        from engine_bom.webapp import balloon_bom_mismatch_note
        comps = [{"item_no": i} for i in (1, 2, 3, 4)]
        note = balloon_bom_mismatch_note([1, 2, 3, 4, 5, 6], comps)
        self.assertIsNotNone(note)
        self.assertIn("[5, 6]", note)
        self.assertIn("球标", note)

    def test_consistent_returns_none(self):
        from engine_bom.webapp import balloon_bom_mismatch_note
        comps = [{"item_no": i} for i in (1, 2, 3)]
        self.assertIsNone(balloon_bom_mismatch_note([1, 2, 3], comps))

    def test_insufficient_data_returns_none(self):
        from engine_bom.webapp import balloon_bom_mismatch_note
        self.assertIsNone(balloon_bom_mismatch_note([], [{"item_no": 1}]))

    def test_balloons_without_numbered_rows_hinted(self):
        # 视图页：有球标但明细清单没有序号行（如整页无明细表），应如实提示而不是静默
        from engine_bom.webapp import balloon_bom_mismatch_note
        note = balloon_bom_mismatch_note(list(range(1, 38)), [{"item_no": None, "name_zh": "整机"}])
        self.assertIsNotNone(note)
        self.assertIn("37 个引出序号", note)
        self.assertIn("可能没有明细表", note)
        note2 = balloon_bom_mismatch_note([1, 2], [])
        self.assertIsNotNone(note2)


class TestPlaceholderRows(unittest.TestCase):
    """无明细表页上模型照球标编造的占位行（数量/材料/件号全空）必须被标记。"""

    def test_fabricated_placeholder_rows_flagged(self):
        comps = [BomComponent(item_no=i, name_zh=n, confidence=0.9)
                 for i, n in enumerate(["Frame", "Side Plate", "Hinge Rod"], 1)]
        issues = validate_components(comps)
        self.assertEqual(len([i for i in issues if "占位行" in i]), 3)
        self.assertTrue(all(c.needs_review for c in comps))

    def test_real_rows_not_flagged(self):
        comps = [
            BomComponent(item_no=1, name_zh="泵体", quantity=1, material="HT200"),   # 正常
            BomComponent(item_no=2, name_zh="垫片", quantity=2),                     # 数量有即可
            BomComponent(item_no=3, name_zh="后泵体", quantity=1, material="HT200",
                         part_number="DLYPB1-04"),                                    # 零件图行
            BomComponent(item_no=4, name_zh="连接轴"),                               # 空标题栏零件图：材料无但也不该占位误报? —— 会报，见下
        ]
        issues = validate_components(comps)
        flagged = [c.item_no for c in comps if c.needs_review]
        self.assertEqual(flagged, [4])  # 仅全空的行被标记
        self.assertTrue(any("占位行" in i for i in issues))


if __name__ == "__main__":
    unittest.main()
