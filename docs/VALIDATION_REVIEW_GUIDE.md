# 验证与审查说明

审查入口：http://127.0.0.1:8788/static/validation/index.html 。主程序“复核与历史”页也有链接。

## 本轮交付

- 30份真实维修手册零件图及配套表格，655条参考零件行。输入为原图组成的PDF，TSV标签不送给模型。这不是30个独立制造项目，也没有完整材料和工艺标签。
- 40份生成的二维回归图：10正常、30错误，覆盖序号不对应、零数量、同一尺寸矛盾。标签来自生成参数，只对这三类错误有完整标注，不代表全图符合所有制造规范。
- 额外公开硬件资料的URL、许可和哈希在 `data/public/validation_sources.json`。7份只有交互3D注释的PDF已排除；系统现在提示先导出二维图。
- 修复了重复件号被提前合并、原始序号被重排、零数量被当作模型格式错误的问题。图纸中的错误保留给检查模块，不提前猜测改正。
- 上传一次，同时得到BOM与规则/VLM检查候选。确认文字修改后生成副本和源文件哈希审计。当前不修改CAD几何，也不保证制造可行性。

## 数据来源与真值状态

外部数据来自 [Enginuity作者仓库](https://huggingface.co/datasets/enginuity2025/enginuity-bench)，DOI 10.57967/hf/8702，固定提交 `c079c44f602c227109793cf2fdb3919ea8a99331`。逐样本来源URL、输入和标签SHA256在 `data/validation/manifest.json`。作者说明原文保存在 `data/public/enginuity/README.md` 与 `audit_README.md`。

作者明确说明TSV由Claude Sonnet 4.5生成；目录名audit_set不能证明已经经过工程师复核。当前两名独立实际人一致批准为 **0/30**。外部成绩只能叫“作者参考标签匹配”，不能叫已确认的工程真值准确率。

已发现 enginuity_01 的原始 table_1 第8行写WASHER，而作者TSV写LOCKER。建议保存在 `data/validation/label_correction_proposals.json`，未经人审批准，没有改动原始标签或提高成绩。多张表、重复件号、未知数量及UOC处理也有审查提示。

额外资料来自 Foundation-Devices/passport-assembly、guansk/ArcBlue-HMT-Lite、openAMRobot/openamr-platform-hw 的固定提交，许可文件随下载保留。Enginuity不同说明文件的许可和范围存在不同表述，原文均保留，不能以一个目录名推断许可或标签质量。

## 如何审查程序

1. 主程序上传 `data/validation/synthetic/inputs` 下的clean、item_mismatch、quantity_zero和dimension_conflict各一份。检查同页出现BOM和纠错项；正常样本也要看，不能只选有错误的。选一项有明确位置的文字修改，下载副本，核对源文件未改变、审计中有源SHA256。
2. 打开审查台，先看原始PDF/图像，再显示“参考标签”和“模型结果”。优先检查enginuity_01第8行、enginuity_14/17多张表、正常/零数量/矛盾尺寸图。逐行核对件号、名称、数量、序号和页码。对照审查我的输出，不算独立真值标注。
3. 阅读 `data/reports/validation/REPORT.md` 与各运行的report.json。逐样本result.json包含状态、耗时、计分和问题；predictions保留BOM与agent trace；freeze.json记录配置和哈希，source_snapshot保留当时源码。失败和漏检也在分母中。

## 如何取得可验收的人审标签

两名具备图纸阅读能力的实际人分别用独立浏览器环境，从原图逐行录入，不能提前看模型、参考标签或互相复制。页面显示对照信息后，该浏览器的该样本不能再勾独立；不要清除记录来伪装独立。

行示例：`{"item_no":8,"part_number":"704190","name_en":"WASHER PART OF KIT P/N 5704052","quantity":2,"source_page":2}`。未知数量明确填null，source_page为正整数；重复件号分行保留，整数序号保持印刷值；字母/脚注序号在当前整数schema中item_no填null，原文放remark。完成后批准并下载JSON。姓名及独立性是审查人的声明，系统不认证身份，资格由项目负责人确认。

在项目目录执行，用实际下载文件路径替换示例：

```powershell
python -X utf8 scripts/check_reviews.py reviewer_A.json reviewer_B.json --out data/validation/review_consensus_v1.json
```

同一输入哈希、两名不同实际人独立批准、逐行内容一致才通过。分歧必须由实际人重新读图解决，程序不猜、不平均。全部通过后用新目录评测：

```powershell
python -X utf8 scripts/run_validation.py --reviews reviewer_A.json reviewer_B.json --out data/reports/validation/human_reviewed_v1 --workers 3 --direct
```

已查看或用来调参的样本不能再声称盲测；将来验收应另留未见项目和来源。当前外部数据整个来源按同一group隔离，防止同源数据跨训练/测试泄漏。

## 成绩口径与复现

精确件号匹配，没有件号才精确名称；不靠模糊配对补分。漏检行的标注字段算错，未知数量不当成已知数量评分。材料和工艺未标注，不能据此断言已准确识别。报告包含完整BOM正确率及字段分子/分母。

纠错成绩仅涉及三类生成错误。重复提示会降低逐项精度；40份规则报告的20项额外提示来自同一序号问题的重复报告，不是20份正常图报错。位置另计页码和框重叠，规则没有图像定位时定位得分为0。4份云端结果是小样本联通及回归验证，不等于全40份云端或真实工厂错误准确率。未限定范围的旧云端结果保留，用于审查VLM的额外意见和误报。

旧external_reference_v1因重复件号误触发循环而中断，只作诊断，不能作为完整30份成绩；external_reference_v3_direct为修复前完整基线，external_reference_v4_direct为最终代码重新跑全部30份的参考匹配。不是人审真值或盲测。显式enable_thinking:false与默认长推理的成绩不能混合。费用不凭token或耗时猜测。仍是云端测试；本地兼容接口和离线检查脚本存在，但没有宣称端侧模型部署完成。

```powershell
python -X utf8 -m unittest discover -s tests -q
python -X utf8 scripts/smoke_web.py
python -X utf8 scripts/run_validation.py --reference-only --out data/reports/validation/reproduction_NEW --workers 3 --direct
```

复跑使用新目录，核对配置、manifest及源码哈希，原报告不覆盖。API有随机性，不能保证逐字相同。密钥仅使用既有本地配置，报告与静态审查包不含密钥。

## 模型切换与历史恢复点

最终版本全量复测external_reference_v4_direct成功13/30，后17份API返回AllocationQuota.FreeTierOnly（免费额度耗尽）。这次含服务失败的成绩不能作为最终模型精度。修复前完整基线和两份单图修复诊断均保留，不拼接。

用户随后授权自由选择其他千问视觉模型，现已自动切换到qwen3.7-max-2026-06-08，用真实图纸图片读出图号验证成功；无需再手动更换密钥。模型选择记录在data/reports/validation/model_selection_2026-09-17.json。该型号支持图像输入及1M上下文，依据：https://help.aliyun.com/zh/model-studio/vision-model 。新模型完整评测为qwen37_max_reference_v1，四份云端纠错为qwen37_max_defects_v1，与旧成绩分开。

当前未更改计费模式。程序已补充额度耗尽的明确提示及批量停止新调用，不反复重试不可恢复的403。当前结果以REPORT.md为准，旧额度阻塞记录保留用于审计。
