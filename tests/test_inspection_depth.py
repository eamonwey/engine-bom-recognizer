# -*- coding: utf-8 -*-
"""三项审图深度改进的回归测试：
① 跨视图检查强制先建立视图清单（view_inventory）；
② 第二遍聚焦巡检（focus_sweep）合并放大分区发现；
③ 装配树机械一致性软告警（同轴盖件/紧固件配对）。
"""
import json
import unittest

from PIL import Image

from engine_bom.assembly import validate_tree
from engine_bom.hybrid_inspection import inspect
from engine_bom.providers import ProviderResponse


def _coverage():
    return {'ERR-%02d' % n: {'status': 'uncertain', 'evidence': '测试占位：未执行该类检查'}
            for n in range(1, 11)}


def _issue(err_id, message, location, check_kind=None):
    issue = {"err_id": err_id, "message": message, "evidence": "图面可见",
             "source_page": 1, "bbox": None, "location": location, "severity": "中"}
    if check_kind:
        issue["check_kind"] = check_kind
    return issue


class SequenceProvider:
    name = "test"

    def __init__(self, values):
        self.values = iter(values)
        self.calls = []

    def analyze(self, images, prompt):
        self.calls.append((len(images), prompt))
        value = next(self.values)
        return ProviderResponse(value, "test")


def _primary(issues, inventory=None):
    payload = {"issues": issues, "coverage": _coverage()}
    if inventory is not None:
        payload["view_inventory"] = inventory
    return json.dumps(payload)


class TestViewInventory(unittest.TestCase):
    DIMS = [{"value": "70±0.025", "view": "主视图"}, {"value": "174", "view": "左视图"}]

    def test_cross_view_without_inventory_triggers_retry(self):
        bad = _primary([_issue("ERR-05", "两视图轮廓不一致", "主视图 vs 左视图")])
        good = _primary([_issue("ERR-05", "两视图轮廓不一致", "主视图 vs 左视图")],
                        inventory=[{"view": "主视图", "dimension_indices": [0], "balloons": []},
                                   {"view": "左视图", "dimension_indices": [1], "balloons": []}])
        provider = SequenceProvider([bad, good])
        result = inspect(provider, [Image.new("RGB", (1200, 1200))], {}, [], [], [],
                         {"focus_sweep": False})
        self.assertEqual(len(provider.calls), 2)  # 缺清单被打回重试了一次
        self.assertEqual(result["visual_status"], "validated")
        self.assertEqual(len(result["view_inventory"]), 2)

    def test_cross_view_with_inventory_passes(self):
        good = _primary([_issue("ERR-05", "两视图轮廓不一致", "主视图 vs 左视图")],
                        inventory=[{"view": "主视图", "dimension_indices": [0], "balloons": []},
                                   {"view": "左视图", "dimension_indices": [1], "balloons": []}])
        provider = SequenceProvider([good])
        result = inspect(provider, [Image.new("RGB", (1200, 1200))], {}, [], [], [],
                         {"focus_sweep": False})
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(len(result["view_inventory"]), 2)
        # ERR-05 属语义判断类：无专项规则佐证时按设计降级为 unverified 观察，
        # 但必须保留在 issues 或 unverified_findings 之一中供人工核实
        self.assertTrue(any(i["err_id"] == "ERR-05"
                            for i in result["issues"] + result["unverified_findings"]))

    def test_non_cross_view_issues_need_no_inventory(self):
        provider = SequenceProvider([_primary([_issue("ERR-06", "标题栏材料为空", "标题栏")])])
        result = inspect(provider, [Image.new("RGB", (1200, 1200))], {}, [], [], [],
                         {"focus_sweep": False})
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["view_inventory"], [])


class TestFocusSweep(unittest.TestCase):
    def test_sweep_merges_extra_findings(self):
        primary = _primary([_issue("ERR-06", "标题栏材料为空", "标题栏")])
        sweep = json.dumps({"issues": [_issue("ERR-02", "输出轴缺少直径标注", "放大块2·左下区")]})
        provider = SequenceProvider([primary, sweep])
        result = inspect(provider, [Image.new("RGB", (2000, 2000))], {}, [], [], [],
                         {"focus_sweep": True})
        self.assertEqual(result["focus_sweep"]["status"], "validated")
        self.assertEqual(result["focus_sweep"]["findings"], 1)
        swept = [i for i in result["issues"] if i.get("origin") == "vlm_sweep"]
        self.assertEqual(len(swept), 1)
        self.assertEqual(swept[0]["err_id"], "ERR-02")
        # 第二遍调用收到的是 4 个放大分区，而不是整页
        self.assertEqual(provider.calls[1][0], 4)

    def test_sweep_can_be_disabled(self):
        provider = SequenceProvider([_primary([])])
        result = inspect(provider, [Image.new("RGB", (2000, 2000))], {}, [], [], [],
                         {"focus_sweep": False})
        self.assertEqual(result["focus_sweep"]["status"], "not_run")
        self.assertEqual(len(provider.calls), 1)


class TestAssemblyConsistencyWarnings(unittest.TestCase):
    COMPS = [{"name_zh": "齿轮箱体"}, {"name_zh": "输出轴端盖"}, {"name_zh": "输出轴透盖"},
             {"name_zh": "螺栓M8"}, {"name_zh": "螺母M8"}]

    def _tree(self, cover2_parent, nut_parent):
        return {"nodes": [
            {"id": "n1", "component_index": 0, "parent_id": None, "evidence": "基体", "source_page": 1},
            {"id": "n2", "component_index": 1, "parent_id": "n1", "evidence": "x", "source_page": 1},
            {"id": "n3", "component_index": 2, "parent_id": cover2_parent, "evidence": "x", "source_page": 1},
            {"id": "n4", "component_index": 3, "parent_id": "n1", "evidence": "x", "source_page": 1},
            {"id": "n5", "component_index": 4, "parent_id": nut_parent, "evidence": "x", "source_page": 1},
        ]}

    def test_mismatched_cover_and_fastener_parents_warn(self):
        result = validate_tree(self._tree("n2", "n2"), self.COMPS)
        warnings = result.get("warnings") or []
        self.assertTrue(any('同属“输出轴”的盖件父件不一致' in w for w in warnings))
        self.assertTrue(any('M8 紧固件组父件不一致' in w for w in warnings))

    def test_consistent_parents_produce_no_warning(self):
        result = validate_tree(self._tree("n1", "n1"), self.COMPS)
        self.assertEqual(result.get("warnings") or [], [])


if __name__ == "__main__":
    unittest.main()
