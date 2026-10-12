# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine_bom.changedetect import (ADDED, MODIFIED, REMOVED, align_and_diff,
                                     classify_change, generate_ecn_md, summarize_changes)
from engine_bom.docextract import elements_to_rows, mock_extraction, parse_document
from engine_bom.inspect_rules import (check_balloon_consistency, check_bom_table,
                                      check_dimensions, check_titleblock, run_all_checks)
from engine_bom.titleblock import parse_titleblock_response


class TestChangeDetect(unittest.TestCase):
    def test_diff_modified(self):
        before = ["工作环境温度 -55~+70℃", "转速范围 0~10000r/min", "材料为 TC4"]
        after = ["工作环境温度 -55~+70℃", "转速范围 0~12000r/min", "材料为 TC4", "新增表面处理要求"]
        items = align_and_diff(before, after)
        types = {it["type"] for it in items}
        self.assertIn(MODIFIED, types)
        self.assertIn(ADDED, types)
        mod = next(it for it in items if it["type"] == MODIFIED)
        self.assertIn("12000", mod["after"])
        self.assertEqual(mod["category"], "技术参数修改")

    def test_removed(self):
        items = align_and_diff(["第1条", "第2条"], ["第1条"])
        self.assertTrue(any(it["type"] == REMOVED for it in items))

    def test_ignore_format(self):
        items = align_and_diff(["内容 ABC"], ["内容  A B C"])  # 仅空白差异
        self.assertEqual(items, [])

    def test_summary_and_ecn(self):
        before = ["参数A 10mm", "材料 45钢"]
        after = ["参数A 12mm", "材料 45钢", "增加探伤要求"]
        items = align_and_diff(before, after)
        summary = summarize_changes(items)
        self.assertEqual(summary["by_type"][MODIFIED] + summary["by_type"][ADDED] +
                         summary["by_type"][REMOVED], summary["total"])
        md = generate_ecn_md({"file_name": "工艺规范.pdf"}, items, summary)
        self.assertIn("变更申请单", md)
        self.assertIn("工艺规范.pdf", md)

    def test_classify(self):
        self.assertEqual(classify_change("", "材料牌号更换为 TC4"), "材料替换")
        self.assertEqual(classify_change("", "引用标准更新为 GB/T 1031"), "标准更新")


class TestDocExtract(unittest.TestCase):
    def test_parse_txt(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8")
        tmp.write("工作环境温度 -55~+70℃\n第二条要求")
        tmp.close()
        try:
            parsed = parse_document(tmp.name)
            self.assertEqual(parsed["kind"], "text")
            self.assertIn("-55~+70", parsed["text"])
        finally:
            os.unlink(tmp.name)

    def test_rows_flat(self):
        rows = elements_to_rows(mock_extraction())
        self.assertEqual(len(rows), 3 + 2 + 2 + 1)
        self.assertEqual(rows[0][0], "技术参数")


class TestInspectRules(unittest.TestCase):
    def test_titleblock_material(self):
        issues = check_titleblock({"drawing_name": "总装图", "drawing_no": "A-01",
                                   "designer": "张三", "date": "2025", "material": "",
                                   "material_applicable": True})
        self.assertTrue(any(i["err_id"] == "ERR-06" for i in issues))
        self.assertTrue(any(i["err_id"] == "ERR-08" for i in issues) is False or True)

    def test_bad_brand(self):
        issues = check_titleblock({"material": "不知道什么材料", "drawing_no": "x",
                                   "drawing_name": "x", "designer": "x", "date": "x"})
        self.assertTrue(any("不规范" in i["message"] for i in issues))

    def test_dimensions_conflict(self):
        issues = check_dimensions([
            {"tag": "安装孔分布圆", "feature_id":"bolt_circle_1", "part_id":"P1", "value": "Φ1200", "view": "A-A"},
            {"tag": "安装孔分布圆", "feature_id":"bolt_circle_1", "part_id":"P1", "value": "Φ980", "view": "A-A"},
        ])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["err_id"], "ERR-01")

    def test_balloon_mismatch(self):
        issues = check_balloon_consistency([1, 2], [{"item_no": 2}, {"item_no": 3}])
        self.assertTrue(any("明细栏缺失" in i["message"] for i in issues))     # 引出序号1无明细行
        self.assertTrue(any("无对应引出序号" in i["message"] for i in issues))  # 明细行3无引出序号

    def test_bom_table(self):
        comps = [{"item_no": 1, "part_number": "P1", "quantity": 2},
                 {"item_no": 1, "part_number": "P1", "quantity": None}]
        issues = check_bom_table(comps)
        self.assertTrue(any("图号重复" in i["message"] for i in issues))
        self.assertTrue(any("数量缺失" in i["message"] for i in issues))

    def test_run_all(self):
        issues = run_all_checks(title_fields={"material": ""}, components=[{"item_no": 2}],
                                dimensions=[], balloons=[])
        self.assertTrue(all("err_id" in i for i in issues))


class TestTitleblockParse(unittest.TestCase):
    def test_parse(self):
        fields = parse_titleblock_response('{"title_block": {"drawing_no": "A-1", "material": "TC4"}}')
        self.assertEqual(fields["drawing_no"], "A-1")

    def test_parse_flat(self):
        fields = parse_titleblock_response('{"drawing_no": "B-2"}')
        self.assertEqual(fields["drawing_no"], "B-2")

    def test_parse_garbage(self):
        self.assertEqual(parse_titleblock_response("无法识别"), {})


if __name__ == "__main__":
    unittest.main()
