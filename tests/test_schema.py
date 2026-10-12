# -*- coding: utf-8 -*-
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_bom.schema import (BomComponent, components_from_payload, merge_components,
                               normalize_part_number, normalize_text, validate_components)


class TestCoercion(unittest.TestCase):
    def test_quantity_from_text(self):
        comp, warnings = components_from_payload([{"quantity": "4件", "name_zh": "活塞"}])
        self.assertEqual(comp[0].quantity, 4)
        self.assertTrue(warnings)

    def test_quantity_float_integral(self):
        comp, _ = components_from_payload([{"quantity": 4.0}])
        self.assertEqual(comp[0].quantity, 4)

    def test_alias_keys(self):
        comp, _ = components_from_payload([{"序号": 3, "名称": "活塞", "材质": "铝合金"}])
        self.assertEqual(comp[0].item_no, 3)
        self.assertEqual(comp[0].name_zh, "活塞")
        self.assertEqual(comp[0].material, "铝合金")

    def test_confidence_range(self):
        comp, _ = components_from_payload([{"name_zh": "x", "confidence": 1.5}])
        issues = validate_components(comp)
        self.assertTrue(any("置信度" in i for i in issues))


class TestMerge(unittest.TestCase):
    def test_merge_default_keep_max(self):
        page1 = [BomComponent(part_number="ENG-1", name_zh="活塞", quantity=2, unit="件", source_page=1)]
        page2 = [BomComponent(part_number="ENG-1", name_zh="活塞", quantity=6, unit="件", source_page=3)]
        merged, _ = merge_components([page1, page2])  # 默认 keep_max，防跨页重复计数
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].quantity, 6)
        self.assertEqual(merged[0].source_page, 1)
        self.assertEqual(merged[0].item_no, 1)

    def test_merge_policy_sum(self):
        page1 = [BomComponent(part_number="ENG-1", name_zh="活塞", quantity=2, unit="件", source_page=1)]
        page2 = [BomComponent(part_number="ENG-1", name_zh="活塞", quantity=2, unit="件", source_page=3)]
        merged, _ = merge_components([page1, page2], quantity_policy="sum")
        self.assertEqual(merged[0].quantity, 4)

    def test_keep_different_specs(self):
        page1 = [BomComponent(part_number="ENG-1", name_zh="螺栓", specification="M6", quantity=4)]
        page2 = [BomComponent(part_number="ENG-1", name_zh="螺栓", specification="M8", quantity=2)]
        merged, _ = merge_components([page1, page2])
        self.assertEqual(len(merged), 2)


class TestValidation(unittest.TestCase):
    def test_duplicate_part_number(self):
        comps = [BomComponent(part_number="ENG-1", name_zh="活塞"),
                 BomComponent(part_number="eng 1", name_zh="活塞环")]
        issues = validate_components(comps)
        self.assertTrue(any("件号重复" in i for i in issues))

    def test_strict_raises(self):
        with self.assertRaises(ValueError):
            validate_components([BomComponent()], strict=True)


class TestNormalize(unittest.TestCase):
    def test_part_number(self):
        self.assertEqual(normalize_part_number("eng - blk_001"), "ENGBLK001")

    def test_text(self):
        self.assertEqual(normalize_text("Ａｌ合金 4032"), "al合金4032")

    def test_roundtrip(self):
        comp = BomComponent(part_number="P1", name_zh="活塞", quantity=1)
        payload = {"components": [comp.to_dict()]}
        comps, warns = components_from_payload(json.loads(json.dumps(payload, ensure_ascii=False)))
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].name_zh, "活塞")
        self.assertEqual(warns, [])


if __name__ == "__main__":
    unittest.main()
