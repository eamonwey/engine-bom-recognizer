# -*- coding: utf-8 -*-
"""检测历史（history.py）单元测试：记录构建、存储往返、汇总与详情。"""
import json
import os
import tempfile
import unittest

from engine_bom.history import (append_record, build_record, load_detail,
                                load_records, summarize)


def _fake_result():
    return {
        "document_id": "ZD100-00",
        "source_sha256": "a" * 64,
        "model_info": {"model": "qwen3-vl-plus", "prompt_version": "v4",
                       "recognition_mode": "per_page", "pages": 1,
                       "knowledge_base": {"entries": 5},
                       "agent_loop": {"status": "validated"}},
        "bom": {
            "process_time_s": 41.8,
            "components": [
                {"part_number": "A100", "name_zh": "轴承支座组件", "material": "组合件",
                 "quantity": 1, "category": "机体箱架类", "confidence": 0.95},
                {"part_number": "P102", "name_zh": "轴承", "material": "GCr15",
                 "quantity": 2, "category": "轴系件", "confidence": 0.9,
                 "needs_review": True, "review_reasons": ["材料待核实"]},
                {"part_number": "", "name_zh": "", "quantity": 4, "confidence": 0.8},
            ],
            "validation_issues": ["ERR-08 数量不一致: B412 展开 12 明细 11"],
            "assembly": {
                "inference_status": "validated",
                "nodes": [{"id": "root"}, {"id": "n1"}, {"id": "n2"}, {"id": "n3"}],
                "unverified_nodes": [{"id": "n9"}],
                "unresolved_component_indices": [2],
                "max_depth": 3,
                "quantity_conflicts": [{"part_number": "B412", "printed_quantity": 11,
                                        "exploded_quantity": 12}],
            },
        },
        "title_block": {"fields": {"drawing_no": "ZD100-00", "designer": ""}},
        "missing_required": ["designer"],
        "balloons": [1, 2, 3, 4],
        "dimensions": [1, 2, 3],
        "issues": [
            {"err_id": "ERR-08", "severity": "高", "message": "数量不一致", "origin": "rule"},
            {"err_id": "ERR-06", "severity": "中", "message": "材料缺失", "origin": "vlm"},
        ],
        "outputs": ["/x/ZD100-00.json", "/x/ZD100-00.csv"],
        "inspection": {"process_time_s": 99.4,
                       "dimension_extraction": {"status": "ok"}},
    }


class BuildRecordTest(unittest.TestCase):
    def test_ok_record_metrics(self):
        r = build_record("job1", "bom", r"C:\uploads\ZD100-00.png", result=_fake_result(),
                         finished_at="2026-10-11T12:00:00")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["file_name"], "ZD100-00.png")
        self.assertEqual(r["model"]["model"], "qwen3-vl-plus")
        self.assertEqual(r["model"]["knowledge_base"], 5)
        bom = r["bom"]
        self.assertEqual(bom["n_components"], 3)
        self.assertEqual(bom["total_quantity"], 7)
        # 件号 2/3、材料 2/3、名称 2/3
        self.assertEqual(bom["field_fill"]["part_number"]["filled"], 2)
        self.assertEqual(bom["field_fill"]["weight"]["filled"], 0)
        self.assertEqual(bom["confidence"]["mean"], round((0.95 + 0.9 + 0.8) / 3, 3))
        self.assertEqual(bom["needs_review"]["count"], 1)
        self.assertEqual(bom["categories"], {"机体箱架类": 1, "轴系件": 1})
        self.assertEqual(bom["n_validation_issues"], 1)
        asm = r["assembly"]
        self.assertEqual(asm["n_nodes"], 4)
        self.assertEqual(asm["n_unverified"], 1)
        self.assertEqual(asm["unresolved_component_indices"], [2])
        self.assertEqual(asm["max_depth"], 3)
        self.assertEqual(asm["n_quantity_conflicts"], 1)
        self.assertEqual(asm["quantity_conflicts"][0]["printed_quantity"], 11)
        self.assertEqual(r["annotations"]["balloon_count"], 4)
        self.assertEqual(r["annotations"]["dimension_status"], "ok")
        insp = r["inspection"]
        self.assertEqual(insp["n_findings"], 2)
        self.assertEqual(insp["by_severity"], {"高": 1, "中": 1})
        self.assertEqual(insp["by_err_id"], {"ERR-08": 1, "ERR-06": 1})
        self.assertEqual(insp["by_source"], {"rule": 1, "vlm": 1})
        self.assertEqual(r["timings"], {"bom_process_time_s": 41.8,
                                        "inspection_process_time_s": 99.4})
        self.assertEqual(r["outputs"], ["ZD100-00.json", "ZD100-00.csv"])
        self.assertEqual(r["title_block"]["missing_required"], ["designer"])

    def test_failed_record(self):
        r = build_record("job2", "bom", r"C:\x\a.png", error="ProviderError: 403 免费额度已耗尽")
        self.assertEqual(r["status"], "failed")
        self.assertIn("403", r["error"])
        self.assertNotIn("bom", r)

    def test_minimal_result_no_crash(self):
        r = build_record("job3", "bom", None, result={})
        self.assertEqual(r["bom"]["n_components"], 0)
        self.assertIsNone(r["assembly"]["max_depth"])


class StoreRoundTripTest(unittest.TestCase):
    def test_append_load_summary_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            r1 = build_record("job1", "bom", "a.png", result=_fake_result())
            append_record(tmp, r1, full_result=_fake_result())
            r2 = build_record("job2", "bom", "b.png", error="403 配额")
            append_record(tmp, r2)
            r3 = build_record("job3", "bom", "a.png", result=_fake_result(),
                              finished_at="2026-10-11T13:00:00")
            append_record(tmp, r3, full_result=_fake_result())

            records, summary = load_records(tmp)
            self.assertEqual([r["job_id"] for r in records], ["job3", "job2", "job1"])  # 最新在前
            self.assertEqual(summary["total"], 3)
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(summary["ok"], 2)
            self.assertEqual(summary["success_rate"], round(2 / 3, 3))
            self.assertEqual(summary["total_components"], 6)
            self.assertEqual(summary["total_findings"], 4)
            self.assertEqual(summary["distinct_files"], 2)
            self.assertEqual(summary["latest_model"], "qwen3-vl-plus")
            self.assertEqual(summary["avg_bom_time_s"], 41.8)

            records, _ = load_records(tmp, file_name="A.PNG")  # 大小写不敏感
            self.assertEqual(len(records), 2)
            records, _ = load_records(tmp, status="failed")
            self.assertEqual([r["job_id"] for r in records], ["job2"])

            detail = load_detail(tmp, "job1")
            self.assertEqual(detail["result"]["bom"]["components"][0]["part_number"], "A100")
            self.assertIsNone(load_detail(tmp, "nope"))
            self.assertIsNone(load_detail(tmp, "../escape"))  # 路径穿越防护

    def test_append_replaces_same_job(self):
        """编辑后同步：同 job_id 再写入时覆盖索引行与快照，不产生重复记录。"""
        with tempfile.TemporaryDirectory() as tmp:
            first = build_record("job1", "bom", "a.png", result=_fake_result())
            append_record(tmp, first, full_result=_fake_result())
            edited = _fake_result()
            edited["bom"]["components"][0]["name_zh"] = "轴承支座组件(已改)"
            second = build_record("job1", "bom", "a.png", result=edited,
                                  finished_at="2026-10-11T14:00:00")
            append_record(tmp, second, full_result=edited)
            records, summary = load_records(tmp)
            self.assertEqual([r["job_id"] for r in records], ["job1"])
            self.assertEqual(summary["total"], 1)
            self.assertEqual(records[0]["finished_at"], "2026-10-11T14:00:00")
            detail = load_detail(tmp, "job1")
            self.assertEqual(detail["result"]["bom"]["components"][0]["name_zh"],
                             "轴承支座组件(已改)")


if __name__ == "__main__":
    unittest.main()
