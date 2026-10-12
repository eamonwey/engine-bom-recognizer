"""Regression: a shared standard number is not a duplicate drawing number."""
import unittest

from engine_bom.inspect_rules import check_bom_table
from engine_bom.hybrid_inspection import inspect


class StandardReferenceTests(unittest.TestCase):
    def test_printed_names_and_missing_specifications(self):
        for standard, names in [
            ("GB/T 70.1-2008", ["内六角圆柱头螺钉M6×16", "内六角圆柱头螺钉M6×30"]),
            ("GB/T 13871.1-2007", ["端盖处油封", "小油封"]),
            ("GB/T 3452.1-2005", ["大O形圈", "小O形圈"]),
            ("GB/T 119.1-2000", ["斜盘定位销钉", "小销钉"]),
        ]:
            with self.subTest(standard=standard):
                rows = [dict(item_no=i, part_number=standard, name_zh=name,
                             specification="", quantity=1)
                        for i, name in enumerate(names, 1)]
                self.assertEqual(check_bom_table(rows), [])

    def test_standard_formats_do_not_imply_part_identity(self):
        for standard in ["GB / T 70.1-2008", "ＧＢ／Ｔ ７０.１－２００８",
                         "GBT70.1-2008", "GB70.1", "JB/T 7940.1",
                         "DIN EN ISO 4762", "ISO 4762", "ASTM A193", "JIS B1176"]:
            with self.subTest(standard=standard):
                rows = [dict(item_no=1, part_number=standard, quantity=1),
                        dict(item_no=2, part_number=standard, quantity=2)]
                self.assertEqual(check_bom_table(rows), [])

    def test_equal_size_does_not_prove_equal_grade_or_material(self):
        rows = [dict(item_no=i, part_number="GB/T 70.1-2008",
                     specification="M6×16", material=material, quantity=1)
                for i, material in enumerate(["45钢", "不锈钢"], 1)]
        self.assertEqual(check_bom_table(rows), [])

    def test_real_drawing_duplicates_still_reported(self):
        for part_number in ["ZXZSB-014", "GB-HOUSING-01"]:
            rows = [dict(item_no=i, part_number=part_number, quantity=1)
                    for i in (1, 2)]
            issues = check_bom_table(rows)
            self.assertEqual(len(issues), 1)
            self.assertIn("图号重复", issues[0]["message"])

    def test_other_checks_still_apply_to_standard_parts(self):
        rows = [dict(item_no=1, part_number="GB/T 70.1-2008", quantity=0),
                dict(item_no=1, part_number="GB/T 70.1-2008", quantity=None)]
        messages = [i["message"] for i in check_bom_table(rows)]
        self.assertEqual(len(messages), 3)
        for expected in ["数量非正数", "数量缺失", "序号重复"]:
            self.assertTrue(any(expected in m for m in messages))

    def test_hybrid_rule_path_preserves_both_rows(self):
        rows = [dict(item_no=i, part_number="GB/T 70.1-2008", quantity=1)
                for i in (1, 2)]
        provider = type("MockProvider", (), {"name": "mock"})()
        result = inspect(provider, [], {}, rows, [], [], {"check_balloons": False})
        self.assertFalse(any("图号重复" in i["message"] for i in result["issues"]))
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
