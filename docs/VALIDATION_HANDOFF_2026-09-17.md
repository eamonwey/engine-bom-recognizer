# 本轮验证交接

主项目在 `C:\Users\v10\Documents\ChatGPT\工艺\engine-bom-recognizer`，前任原目录未修改。先读 `VALIDATION_REVIEW_GUIDE.md`，不要把旧交接的46个测试或单图27/27当作当前外部成绩。

来源获取脚本：fetch_validation_sources.py、fetch_enginuity.py；生成纠错图：build_defect_suite.py。输入/标签manifest冻结，修改必须新版本，不能覆盖后继续声称相同基线。

评测：run_validation.py、check_reviews.py、summarize_validation.py。网页审查包：build_validation_review.py；前端在static/validation；检查包访问：smoke_validation_review.py。主流程HTTP检查：smoke_web.py。

修复点：保留印刷行/序号/异常数量；合法重复件号与非正数量不触发结构修复循环；只含3D注释且渲染为空的PDF拒绝；Qwen可显式关闭thinking，通用端点默认不传私有参数；APIusage留存；静态子目录使用realpath/commonpath保护；VLM不得仅凭一般意见断言缺项，可配置明确检查范围。

新结果以data/reports/validation/REPORT.md和各运行freeze为准。旧中断运行只是诊断，不能补算成完整基线。限定三类纠错的云端复测是开发回归而非盲测。逐项分数惩罚重复检查项；定位首匹配偏向先出现规则项，需看原始VLM框，不能声称已精准定位全部错误。

待实际人工作：30份外部标签两名独立实际人批准当前0/30；需要真实工程师完成，AI不能代签。身份与资格没有自动认证。当前数据仅修理零件表，没有工艺/材料完整真值，也不是独立30个制造项目。未来需要来源隔离的真实制造图盲测。

未完成的长期目标：端侧模型权重/性能验收、可靠缺陷根因归并、校准VLM证据框、CAD几何修正。现在只实现确认后的定位文字副本，不可声称自主解决工程设计错误。

外部病例23的字母序号a暴露整数schema限制，已保留原始字母到remark并将item_no留空，避免丢掉整表。修复后的单病例诊断单独保存在case23_itemlabel_diagnostic，不能替换原30份冻结成绩；仍有行漏检需人审。
