"""Present current model results separately from earlier Qwen3.8 experiments."""
import csv
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/reports/validation'
bom=json.loads((OUT/'qwen37_max_reference_v1/report.json').read_text(encoding='utf-8'))
defects=json.loads((OUT/'qwen37_max_defects_v1/report.json').read_text(encoding='utf-8'))
s=bom['summary']; d=defects['summary']
lines=['# 当前模型：qwen3.7-max-2026-06-08','',
 '官方支持图像输入，现有API实图读图探测成功；默认配置已切换。没有改变服务端免费额度/计费限制。选择依据和探测响应见model_selection_2026-09-17.json。','',
 '## 完整30份作者参考标签匹配','',
 '来源：Enginuity固定提交；655条参考零件行。作者标签由Claude生成，工程师独立一致批准仍为0/30；这不是已确认的工程真值或盲测。', '',
 '- 成功：{}/30；未完成：{}。'.format(bom['n_cases']-bom['failures'],bom['failures']),
 '- 精确率：{:.2%}；召回率：{:.2%}；F1：{:.2%}。'.format(s['precision'],s['recall'],s['f1']),
 '- 端到端标注字段匹配：{:.2%}；完整BOM正确率：{:.2%}。'.format(s['end_to_end_field_accuracy'],s['exact_bom_rate']),
 '- 逐图表：qwen37_case_metrics.csv；原始结果：qwen37_max_reference_v1/report.json。漏检及失败计入分母，未知字段不补造。','',
 '## 四份指定范围纠错回归','',
 '只检查尺寸矛盾、序号不对应、非正数量，不代表所有制图标准都已验证。正常图仅1份；重复报告按额外项惩罚。','',
 '```json',json.dumps(d,ensure_ascii=False,indent=2),'```','',
 '原始问题/证据/框：qwen37_max_defects_v1/*.inspection.json。定位按首个同类型报告匹配，规则项先出现而无框会得到0分；应另外核对VLM原始框，不推断已精准定位。', '',
 '## 审查与历史','',
 '审查台：http://127.0.0.1:8788/static/validation/index.html；逐图模型结果中选择qwen37_max_reference_v1或qwen37_max_defects_v1。',
 '77项单元测试、上传/预览/修订/下载HTTP流程、70份源资产访问及独立无界面浏览器检查已通过。模型切换用真实图片与实际API评测验证。',
 '此前qwen3.8-max额度耗尽的运行保留在external_reference_v4_direct；不得混入本模型成绩。端侧权重尚未部署，自动修订范围仍限人工确认的定位文字。', '',
 '[完整审查流程](../../../docs/VALIDATION_REVIEW_GUIDE.md)；[此前运行说明](REPORT_PREVIOUS.md)。']
report=OUT/'REPORT.md'
if not (OUT/'REPORT_PREVIOUS.md').exists():
    (OUT/'REPORT_PREVIOUS.md').write_bytes(report.read_bytes())
report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
with (OUT/'qwen37_case_metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=['case_id','status','elapsed_s','n_gt','n_pred','tp','fp','fn','field_accuracy','exact_bom','error']);writer.writeheader()
    for r in bom['results']:
        v=r['scores'];writer.writerow(dict(case_id=r['case_id'],status=r['status'],elapsed_s=r['elapsed_s'],error=r['error'],field_accuracy=v['end_to_end_field_accuracy'],**{k:v[k] for k in ['n_gt','n_pred','tp','fp','fn','exact_bom']}))
print(json.dumps({'bom_success':bom['n_cases']-bom['failures'],'bom_failures':bom['failures'],'precision':s['precision'],'recall':s['recall'],'field_accuracy':s['end_to_end_field_accuracy'],'defects':d},ensure_ascii=False))
