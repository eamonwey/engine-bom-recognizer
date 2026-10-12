# -*- coding: utf-8 -*-
"""infer_assembly 展开数量对账的闭环行为测试（离线假 provider，不消耗配额）。

场景对准验收包的两次实测教训：
  * H02 式重复节点：第一轮拆散重复节点 → 对账反馈后模型第二轮自纠 → 树干净；
  * H04 式明细栏印错：树正确但展开量≠印数 → 重试必须原样保留树（不得删节点/降级），
    最终树带着 quantity_conflicts 被接受，由流水线转 ERR-08 发现。
"""
import json
import unittest

from engine_bom.assembly import infer_assembly
from engine_bom.providers.base import ProviderResponse

CFG = {"enabled": True, "max_attempts": 3}


def occurrence(key, index, parent=None, parent_index=None, qty=None):
    return dict(id=key, component_index=index, parent_id=parent,
                parent_component_index=parent_index, source_page=1,
                quantity_per_parent=qty,
                evidence='A-A剖面显示配合位置', relation_status='supported',
                visual_evidence=dict(kind='attachment' if parent else 'installation_base',
                                     view='A-A', feature='配合特征'))


def _payload(nodes):
    return json.dumps({"nodes": nodes}, ensure_ascii=False)


def _comps_h02():
    return [
        {"part_number": "A200", "name_zh": "双夹紧单元", "quantity": 1},
        {"part_number": "S210", "name_zh": "夹紧子总成", "quantity": 2},
        {"part_number": "P220", "name_zh": "安装板", "quantity": 1},
        {"part_number": "P211", "name_zh": "夹爪", "quantity": 4},
        {"part_number": "B212", "name_zh": "内六角螺钉", "quantity": 6},
    ]


def _tree_h02(duplicated):
    nodes = [
        occurrence("root", 0),
        occurrence("n1", 1, "root", 0, 2),
        occurrence("n2", 2, "root", 0, 1),
        occurrence("n3", 3, "n1", 1, 2),
        occurrence("n5", 4, "n1", 1, 3),
    ]
    if duplicated:
        nodes += [occurrence("n4", 3, "n1", 1, 2),
                  occurrence("n6", 4, "n1", 1, 3)]
    for node in nodes:
        node['component_name'] = _comps_h02()[node['component_index']]['name_zh']
    return nodes


def _comps_h04():
    return [
        {"part_number": "A400", "name_zh": "三夹紧单元", "quantity": 1},
        {"part_number": "S410", "name_zh": "夹紧子总成", "quantity": 3},
        {"part_number": "P411", "name_zh": "夹爪", "quantity": 6},
        {"part_number": "B412", "name_zh": "内六角螺钉", "quantity": 11},
    ]


def _tree_h04():
    """树正确: B412 展开 3×4=12，明细栏印 11。"""
    nodes = [
        occurrence("root", 0),
        occurrence("n1", 1, "root", 0, 3),
        occurrence("n2", 2, "n1", 1, 2),
        occurrence("n3", 3, "n1", 1, 4),
    ]
    for node in nodes:
        node['component_name'] = _comps_h04()[node['component_index']]['name_zh']
    return nodes


class ScriptedProvider(object):
    name = "scripted"

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def analyze(self, images, prompt):
        self.calls += 1
        return ProviderResponse(raw_text=self.payloads[min(self.calls, len(self.payloads)) - 1],
                                model="scripted")

    def describe(self):
        return {"provider": "scripted", "model": "scripted"}


class ReconcileLoopTest(unittest.TestCase):
    def test_duplicate_nodes_self_correct_on_retry(self):
        """第一轮重复节点触发对账反馈，第二轮自纠 → 干净树、零冲突。"""
        provider = ScriptedProvider([_payload(_tree_h02(duplicated=True)),
                                     _payload(_tree_h02(duplicated=False))])
        result = infer_assembly(provider, [object()], _comps_h02(), CFG)
        self.assertEqual(result["inference_status"], "validated")
        self.assertEqual(len(result["nodes"]), 5)
        self.assertEqual(result["quantity_conflicts"], [])
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result["unresolved_component_indices"], [])

    def test_printed_mismatch_keeps_tree_and_flags_conflict(self):
        """树正确、明细栏印错：重试后必须原样保留（不删节点），树带 ERR-08 冲突被接受。"""
        provider = ScriptedProvider([_payload(_tree_h04())])
        result = infer_assembly(provider, [object()], _comps_h04(), CFG)
        self.assertEqual(result["inference_status"], "validated")
        self.assertEqual(len(result["nodes"]), 4)          # B412 没被删
        self.assertEqual(result["unresolved_component_indices"], [])
        conflicts = result["quantity_conflicts"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["err_id"], "ERR-08")
        self.assertEqual(conflicts[0]["part_number"], "B412")
        self.assertEqual(conflicts[0]["printed_quantity"], 11)
        self.assertEqual(conflicts[0]["exploded_quantity"], 12)
        self.assertEqual(provider.calls, 3)                # 两次自纠重试 + 最终接受

    def test_first_attempt_clean_uses_single_call(self):
        provider = ScriptedProvider([_payload(_tree_h02(duplicated=False))])
        result = infer_assembly(provider, [object()], _comps_h02(), CFG)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(result["quantity_conflicts"], [])


class IndexShiftTest(unittest.TestCase):
    """1 基明细序号误用为 0 基下标的确定性修复（H03 实测失败模式）。"""

    def test_one_based_tree_requires_explicit_correction(self):
        from engine_bom.assembly import validate_tree
        comps = [{"part_number": "A300"}, {"part_number": "S310"}, {"part_number": "P311"}]
        nodes = [dict(id="root", component_index=1, parent_component_index=None,
                      parent_id=None, source_page=1, evidence="标题"),
                 dict(id="n1", component_index=2, parent_component_index=1,
                      parent_id="root", source_page=1,
                      evidence="A300 每套包含 S310", quantity_per_parent=2),
                 dict(id="n2", component_index=3, parent_component_index=2,
                      parent_id="n1", source_page=1,
                      evidence="S310 每套包含 P311", quantity_per_parent=1)]
        with self.assertRaisesRegex(ValueError, '引用不存在'):
            validate_tree({"nodes": nodes}, comps)
        self.assertEqual([n['component_index'] for n in nodes], [1, 2, 3])
        self.assertEqual(nodes[1]['parent_component_index'], 1)

    def test_valid_zero_based_tree_untouched(self):
        from engine_bom.assembly import validate_tree
        comps = [{}, {}, {}]
        nodes = [dict(id="root", component_index=0, parent_id=None, source_page=1,
                      evidence="标题"),
                 dict(id="n1", component_index=2, parent_id="root", source_page=1,
                      evidence="配合", quantity_per_parent=1)]
        tree = validate_tree({"nodes": nodes}, comps)
        self.assertEqual([n["component_index"] for n in tree["nodes"]], [0, 2])

    def test_mixed_base_still_rejected(self):
        from engine_bom.assembly import validate_tree
        comps = [{}, {}]
        nodes = [dict(id="root", component_index=0, parent_id=None, source_page=1,
                      evidence="标题"),
                 dict(id="n1", component_index=2, parent_id="root", source_page=1,
                      evidence="配合")]
        with self.assertRaisesRegex(ValueError, "引用不存在"):
            validate_tree({"nodes": nodes}, comps)


    def test_last_valid_tree_survives_final_parse_failure(self):
        """末轮解析失败时，回退到最近一次结构合法的树（带冲突标记），不整体丢弃。"""
        provider = ScriptedProvider([_payload(_tree_h04()),
                                     "这一轮输出不是JSON", "{\"nodes\": [截断"])
        result = infer_assembly(provider, [object()], _comps_h04(), CFG)
        self.assertEqual(len(result["nodes"]), 4)
        self.assertEqual(len(result.get("quantity_conflicts") or []), 1)
        self.assertEqual(result["inference_status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
