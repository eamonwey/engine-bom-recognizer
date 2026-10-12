"""Build human-readable report without changing frozen run outputs."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"data/reports/validation"
latest = json.loads((OUT/"external_reference_v4_direct/report.json").read_text(encoding="utf-8"))
external = json.loads((OUT/"external_reference_v3_direct/report.json").read_text(encoding="utf-8"))
rules = json.loads((OUT/"synthetic_rules_v1/report.json").read_text(encoding="utf-8"))
cloud = json.loads((OUT/"synthetic_cloud_v4_scoped/report.json").read_text(encoding="utf-8"))
s = external["summary"]
lines = ["# 本轮验证结果", "", "外部成绩是作者机器生成标签的匹配度，人审一致批准0/30；不能解释为已确认的工程真值准确率或工厂验收。",
    "", "## 已完成30份的参考基线（修复前版本）", "",
    "- 来源：Enginuity固定提交c079c44f602c227109793cf2fdb3919ea8a99331；30份真实维修手册图及表格、655条参考行，全部同源分组隔离。",
    "- 作者TSV由Claude生成；本次Qwen只接收图像，不接收TSV。病例01第8行已发现作者标签错误，原标签未改。",
    "- 成功/总数：{}/{}，失败：{}。配置：v3、保留印刷行/序号，Qwen3.8-max、enable_thinking:false。".format(external["n_cases"]-external["failures"],external["n_cases"],external["failures"]),
    "- 汇总原始数据：`external_reference_v3_direct/report.json`。本批已用于排错，不能称盲测，也不代表最终修复版本。", "", "```json", json.dumps({k:v for k,v in s.items() if k != "documents"},ensure_ascii=False,indent=2), "```",
    "", "## 三类生成错误回归", "",
    "只标注尺寸矛盾、序号不对应、非正数量。其余制图完整性/标准符合性没有全图标签；不能声称全图真实错误精度。", "",
    "| 运行 | 样本数 | TP | 额外/重复项 | FN | 逐项精度 | 召回 | 正常图报警 | 首匹配定位TP |",
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
for label,run in [("规则已知输入（不测视觉）",rules),("限定三类云端（开发回归）",cloud)]:
    v=run["summary"]
    lines.append("| {} | {} | {} | {} | {} | {:.2%} | {:.2%} | {}/{} | {} |".format(label,run["n_cases"],v["tp"],v["fp"],v["fn"],v["precision"],v["recall"],sum(r["scores"]["negative_false_alarm"] for r in run["results"]),v["negative_cases"],v["localized_tp"]))
lines += ["", "规则中的20项额外报告来自序号问题的重复提示，不是正常图误报；云端也有同一问题的规则/VLM重复项，尚未做可靠根因归并。正常云端只有1份，0次报警不能推断稳定低误报率。定位匹配按首个同类型报告选取，先出现的规则项无bbox会导致0分；原始VLM框另留在逐样本inspection.json，需要人工核对，不能把该0分解读为所有VLM框都错。",
    "", "未限定范围的旧direct云端结果：4份中原定正常1份出现额外建议；按三类标签机械计算23.08%的数值不能当作全图纠错精度，因为范围外问题没有完整标注。明确适用要求和合同范围后得到上表成绩。保留旧结果在`synthetic_cloud_v3_direct`，没有覆盖或混分。限定范围复测属于开发回归，不是盲测。",
    "", "## 修复前与单图诊断", "",
    "修复前30份external_reference_v3_direct：28成功、2失败，P=91.21%、R=68.09%、字段匹配67.44%。94行大表输出截断，字母序号a导致整表拒绝。修复后单图14提取94行、92精确件号匹配；单图23不再结构失败但仍有漏检。没有拼接单图成绩。每次源码哈希均保留。",
    "", "## 最终全量复测：API额度阻塞", "",
    "最终external_reference_v4_direct成功13/30，后17份API返回HTTP403 AllocationQuota.FreeTierOnly，免费额度耗尽。结果没有删除，不能据此给出最终版本全量模型精度。恢复额度后必须新目录重跑；当前未更改计费模式。",
    "服务失败计入30份分母的运行表现：字段匹配30.27%、召回30.08%，用于说明服务不可用对流程的影响，不能当作模型读取图纸能力的准确率。原始结果在external_reference_v4_direct/report.json；对应逐图表在case_metrics_final_blocked.csv。",
    "", "## 审查证据和限制", "",
    "- `case_metrics.csv`列出外部逐图分子/分母、状态、耗时；各运行保留freeze.json、manifest.snapshot.json、source_snapshot和逐样本结果。",
    "- 旧external_reference_v1与旧长推理云端运行已中断，保留部分诊断结果，不能当作完整基线。修复了合法重复件号误触发循环、零数量提前改写、静态审查子目录不能访问。",
    "- 77项单元测试通过；HTTP测试通过上传到BOM/检查、预览、修正、下载；70份审查PDF/图像全部可访问，路径穿越被阻止；JS语法检查通过。使用独立无界面Edge/Playwright完成样本切换、展开结果、曝光保护、未批准测试记录导出、手机布局及页面异常检查。",
    "- 当前仍是云端测试，不宣称端侧权重已部署。自动修正只支持经确认的已定位文字，几何/制造正确性需实际工程师判断。",
    "", "审查步骤和双人标签流程见 [审查指南](../../../docs/VALIDATION_REVIEW_GUIDE.md)。"]
(OUT/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
with (OUT/"case_metrics.csv").open("w",encoding="utf-8-sig",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=["case_id","status","elapsed_s","n_gt","n_pred","tp","fp","fn","field_correct","field_total","field_accuracy","exact_bom","error"])
    writer.writeheader()
    for r in external["results"]:
        v=r["scores"]; fields=v["fields"]
        writer.writerow(dict(case_id=r["case_id"],status=r["status"],elapsed_s=r["elapsed_s"],error=r["error"],
            **{k:v[k] for k in ["n_gt","n_pred","tp","fp","fn","exact_bom"]},
            field_correct=sum(x["correct"] for x in fields.values()),field_total=sum(x["total"] for x in fields.values()),field_accuracy=v["end_to_end_field_accuracy"]))
print(json.dumps({"external":{k:v for k,v in s.items() if k != "documents"},"synthetic":cloud["summary"]},ensure_ascii=False))
with (OUT/"case_metrics_final_blocked.csv").open("w",encoding="utf-8-sig",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=["case_id","status","elapsed_s","quota_blocked","n_gt","n_pred","tp","fp","fn","error"])
    writer.writeheader()
    for record in latest["results"]:
        writer.writerow({"case_id":record["case_id"],"status":record["status"],"elapsed_s":record["elapsed_s"],
            "quota_blocked":"AllocationQuota.FreeTierOnly" in (record.get("error") or ""),"error":record["error"],
            **{k:record["scores"][k] for k in ["n_gt","n_pred","tp","fp","fn"]}})
