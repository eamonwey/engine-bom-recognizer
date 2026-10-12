# 减速器图纸问题修复与测试报告

日期：2026-10-11 至 2026-10-12。项目目录：`C:\Users\v10\Documents\ChatGPT\工艺\engine-bom-recognizer`。

## 当前结论

规则误归组、失败导致候选关系丢失、安装证据与父件矛盾、检查失败被误解为通过等问题已做代码修复，本地回归通过。**尚不能宣布用户提出的全部问题已经解决。** 恢复千问后已经真实上传原图和改图测试：原图的 32 行及逐项数量读取正确，选定名称与油封父件检查通过；低分辨率改图仍有名称错误及错误父件，完整流水线尚未检出目标 60/62 冲突。本地 OCR 已分别准确读到原图 `62H9/h9` 和改图 `60H9/h9`，但文字读取不等于已证明两圆柱面直接配合或孔壁连续。

已保存新的百炼配置，当前模型为 **`qwen3.7-plus-2026-05-26`**，使用百炼兼容接口，实际图片连接测试通过。最初 qwen3.7-plus 连接和两份真实图纸完整任务均已完成，随后它的免费额度耗尽；通过模型列表及[百炼视觉模型官方文档](https://help.aliyun.com/zh/model-studio/vision-model)确认快照模型，再实际测试可用后切换。qwen3.7-flash、qwen3.8-flash、qwen3-vl-plus、qwen3.8-max 的测试也返回免费额度耗尽；两个此前测试的 Max 版本返回 HTTP 400，未据此断言具体原因。连接记录只保留模型、状态等安全摘要，不包含密钥。没有把 GLM 密钥发送给千问，也没有关闭免费额度限制。

## 依据与预期

保留原诊断报告及历史结果，没有重写旧检测记录。本次修复针对以下真实记录：

| 数据 | 任务编号 | 已知预期 |
| --- | --- | --- |
| 同一原图的三次检测 | 20261011203652-87494f、20261011223236-10deaf、20261011224735-08bb53 | 不应把不同方向的 174/178 判为同一高度矛盾；不应因一个坏节点无声丢掉全部候选；同图不同输出应提示差异 |
| 修改图 | 20261011221848-19b051 | 左下 A-A 输出端盖配合文字从 62H9/h9 改为 60H9/h9，应读取改后文字；证明配合对象及几何对应后才能报名义值冲突 |

原图尺寸为 5887×3854，修改图为 1550×1014，两者分辨率不同，不能把识别差异全部归因于模型随机性。原图主体正确是用户提供的测试预期；完整 BOM 和装配树尚没有独立工程师逐项认证的真值。

## 修复内容与源码

| 问题 | 当前处理 | 源码 |
| --- | --- | --- |
| “总高”等语义标签误归组 | 通用中文描述不再成为同一尺寸身份；使用明确要素 ID 或实际标注符号；去除配合后缀后比较名义值，52h9 与 52 不构成数值冲突 | [inspect_rules.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/inspect_rules.py) |
| 轴承尺寸靠数字接近盲配 | 必须有明确轴承对象、内外径角色和关联证据，缺少依据时不产生确定性错误 | 同上 |
| 装配图空材料误报 | 装配图上的模型自报适用布尔值不能单独证明整体材料必填；零件图仍检查材料 | 同上 |
| 原图缩小后局部标注模糊 | 保留原始像素图；全页识别与原像素局部裁切结合；提示词明确裁切坐标到整页的映射 | [ingestion.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/ingestion.py)、[titleblock.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/titleblock.py)、[installation_review.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/installation_review.py) |
| 明细表名称被功能别名替换 | BOM 首次调用增加原像素重叠局部，明确按表中原文字段逐行转写、不能按功能改名；真实低分辨率图仍有错误，尚不能认为解决 | [pipeline.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/pipeline.py) |
| 60/62 读取和对应关系混成一次判断 | 分开读取文字、提出对应候选、遮住数字核查几何、独立回读文字与对象，再由规则计算名义值差异；连续孔候选增加两侧原图边界像素支持检查 | [dimension_links.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/dimension_links.py) |
| API 失败时缺少本地文字依据 | 新增可选 CPU OCR，仅提供严格原文和文字框；不根据预期改数字、不自动补直径符号、不把 OCR 当配合关系真值 | [dimension_text.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/dimension_text.py)、[requirements-ocr.txt](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/requirements-ocr.txt) |
| OCR 的 627 不能可靠理解为尺寸 | 仅对实际未解码邻近原文做紧裁切独立视觉转写，不发送期望数字；必须看见直径符号；公差字母不清则原样保留，不能把 627 改成 62J7 | [dimension_microtext.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/dimension_microtext.py) |
| 局部读到尺寸却在全局消失或错定位 | 已定位微文字必须在同处解释对象，或者明确保存 unmapped_text 原因；高重合不同 CPU 文字框隔离；未映射项显示待核实 | [dimension_links.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/dimension_links.py)、[app.js](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/static/app.js) |
| 数值不同被模型误当作“不是同一对象”的依据 | 同页同视图的 same_feature 孔径候选也要进入遮数几何复核，不能因为它已在初次结果中声明对应就跳过；原图墨线坐标只辅助定位，不能单独证明孔壁归属 | [dimension_links.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/dimension_links.py) |
| 把轴承内外两种接口比较为直接配合 | 独立复核证据明确存在轴承或衬套等中间件时，规则否决直接名义值比较，保存未确认原因 | 同上 |
| 单个坏节点使整树为空 | 保留原始候选，隔离错身份、重复 ID、重复父子实例、循环及受影响的后代；安全子图必须独立视觉复核后才采纳 | [assembly.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/assembly.py) |
| 油封错挂到轴 | 区分外圆安装于透盖与唇口接触轴；证据指向的安装对象与父件矛盾时改为未确认，不猜父件 | 同上、[installation_review.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/installation_review.py) |
| 复核后局部结构冲突拖垮整树 | 单独隔离冲突分支，其他经复核的有效分支保留；状态标记 partial | 同上 |
| 部分结构化事实无效导致全部失败 | 隔离不合规事实，保留有效事实，明确显示部分完成和拒绝原因 | [hybrid_inspection.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/hybrid_inspection.py)、[engineering_checks.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/engineering_checks.py) |
| 失败显示不清楚 | 按主视觉、工程事实、尺寸对应、补充扫查分别显示状态；显示未确认候选、局部原文和位置；未知不能解释为无问题 | 同上、[app.js](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/static/app.js) |
| 同图重复输出不一致不可追查 | 按源文件哈希比较历史 BOM 字段、父子关系、尺寸数量及错误类型；提示差异，不复用旧预测作为真值 | [run_consistency.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/run_consistency.py)、[webapp.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/webapp.py) |
| 截断回复与额度错误处理不当 | 长度截断在结果校验前拦截；记录请求摘要、图像尺寸、实际 usage 与 finish_reason，不记录认证头；额度耗尽不当作超时反复重试 | [agent_loop.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/agent_loop.py)、[openai_compat.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/providers/openai_compat.py) |
| 标准 CSV 导出 HTTP 500 | 补齐 HTTP 导出处理器缺少的 CSV_HEADERS 导入，并加入实际处理器回归 | [webapp.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/webapp.py)、[test_web_bom_export.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/tests/test_web_bom_export.py) |

本地 OCR 包安装在忽略的 `.runtime/ocr` 中，没有替换系统 Python 依赖。迁移机器时需按 requirements-ocr.txt 安装；缺少组件时会显示不可用，并非虚构识别成功。该 OCR 是端侧文字读取组件，尚不是完成端侧部署的视觉推理模型。

## 已执行测试

以下命令在项目目录执行。

| 测试 | 结果 | 证据和限制 |
| --- | --- | --- |
| `python -X utf8 -m unittest discover -s tests -v` | **525 项通过** | [最终日志](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/unit-test-run-final.txt)，包括真实故障模式的最小化回归；不是所有代码行/分支覆盖证明 |
| `node --check static/app.js`；三个现有 Node 前端测试 | 全部通过 | frontend_interactions、frontend_selection、assembly_installation_ui；不等于模型准确率测试 |
| `python -X utf8 scripts/verify_gearbox_fix.py` | **7 项通过** | [历史离线重放](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/offline_replay.json)：错误维度归组消除、盲配消除、空材料误报消除、候选保留、油封矛盾隔离、旧跨视图问题转未确认 |
| `python -X utf8 scripts/verify_gearbox_ui.py --port 8793` | **11 项通过** | 真实无头 Edge 渲染受控回归数据，验证失败/部分完成、转义、原文位置、云失败后本地 OCR、微文字未确认公差等；[结果](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/browser_regression.json) |
| `python -X utf8 scripts/verify_gearbox_api.py --port 8793` | **8 项通过** | 已重启 8793 专用测试服务并复测，显式 Mock 上传：任务完成、源哈希及差异报告保存、JSON/CSV 导出、预览、全局千问配置未被 Mock 改写；[结果](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/api_regression.json)。白图 Mock 不作为 BOM/纠错精度证据 |
| 原图/改图本地 OCR 实测 | **2 项通过** | [结果](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/local_text_acceptance.json)：分别读取 62H9/h9、60H9/h9；原文及整页框保存于 original_local_text.json、modified_local_text.json |
| 真实历史复核纠正引起的重复分支重放 | **28 个节点保留，5 个隔离，partial** | [重放结果](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/duplicate_branch_historical_replay.json)。这些节点是保存的模型复核结果，不是新增的人工工程真值 |

浏览器截图：[检查状态与尺寸依据](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/ui_inspection_coverage.png)、[候选隔离](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/ui_candidate_isolation.png)。截图中的配合问题来自受控 UI 测试数据，不能作为修改图实测成功截图。

## 千问真实复测结果

恢复可用配置后完整真实任务为：原图 **20261012090101-9aa3a0**，改图 **20261012090101-9b6d71**，模型均为 qwen3.7-plus。结果保存在同目录 qwen37plus_full_1_original_result.json、qwen37plus_full_1_modified_result.json；没有重写旧检测记录。

| 实测项目 | 原图 | 改图 |
| --- | --- | --- |
| 32 个明细行、序号 1—32 | 通过 | 通过 |
| 每项数量按原表核对，合计 52 | 通过 | 通过 |
| 选定的 4、5、11、12、20 原文名称 | 通过 | 4、5、12、20 错误 |
| 油封 21 的直接安装父件 20 | 本次通过 | 错挂到 11 |
| 装配结果 | 31 个采纳节点；仍漏 31 号螺母 | 30 个采纳、4 个未确认，不能视为正确树 |
| 装配展开数量 | 有螺母、垫圈数量矛盾待复核 | 有未确认关系，不能视为数量全正确 |
| 工程事实与补充检查 | partial / needs_review | partial / needs_review |
| 目标尺寸纠错 | 未报确定性尺寸错误，但不代表几何全面通过 | 完整流水线未检出 60/62；验收失败 |

原图中的 M8 螺母、弹簧垫圈模型装配展开数量各为 16，但表中各 5；10 号垫圈展开 1，表中 2。报告把这些视为候选树与明细表不一致，需要复核，不能当作图纸本身数量错误。

本轮自行看明细表还发现：旧 GLM 对 #4/#5 以及 #11/#20 的名称曾混淆，而模型安装对象会随错误名称继续错挂。纸面 #4 是“输出轴透盖”、#5“油封28×47×7”、#11“输入轴端盖”、#12“齿轮轴”、#20“输入轴透盖”。**先纠正读表身份，才能评价父件推理。** 这些是自行按原图核对的选定字段，不是工程师认证的完整装配真值。

最初测试参考把 #11 写成“输入轴闷盖”，随后查看原像素表证实是“输入轴端盖”，因此保存原失败 summary，并另存 original_source_review / modified_source_review 的纠正说明；未修改模型原始输出。审查依据见 [明细表原像素](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/bom_table_source_review.png)。

真实阶段测试的 iteration2 至 iteration10 等文件均保留，包括失败结果。iteration5 改图曾把隔着轴承的孔、轴报成直接配合，已加规则否决，iteration6 没有继续报这两个假冲突，但仍漏目标。iteration7 局部已回读 Ø62J7，却在全局漏掉该位置；iteration8 已保留该观察，却以数值不同否定 same_feature，促成新增的遮数复核修订。阶段测试使用原图刚识别的 BOM 作为同图控制上下文，**不能代替改图的完整 BOM 验收**。

iteration9 一度输出了 60/62 冲突，但自行核查测试产物发现：62 框实际位于上面的另一根轴，并非目标下方相邻的 62 标注；且独立回读明确 continuous_profile_confirmed=false，程序却被另一阶段的墨线支持覆盖。**这不是目标检出成功。** 原 acceptance_passed=true 文件保留，另存 source_audit 否决记录以说明原测试断言也有不足。代码现要求两阶段都确认轮廓；轴名不同还必须独立确认实际同轴；验收脚本同时限定目标 60 与相邻 62 的原图位置。525 项回归包含这种“有墨线但另一阶段否定”的真实故障模式，以及复核失败不能抹去先前拒绝原因。iteration9 原图因定位遗漏校验未通过，状态 needs_review，不能解读为原图正确性测试通过。

未完成最新代码的三次完整重复运行，未报告模型准确率，也未声称所有代码行、分支覆盖。必须逐项查看最后阶段状态、原文位置和实体证据；无问题列表不等于通过。

最终 iteration10_cross_stage_veto_modified 实测耗时和完整证据见 [结果 JSON](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/iteration10_cross_stage_veto_modified.json)：**needs_review、issues=[]、acceptance_passed=false**。规则不再因相互矛盾的几何证据输出 iteration9 那类冲突，但目标 60/62 仍没有可靠检出。这轮阶段测试失败已经保留；报告没有用受控 UI 中的冲突样例代替实测。

iteration10 后还修复了候选分组边界漏项：旧列分组受第三个错位框影响，会把几乎对齐的两个目标标注分开；现在逐处寻找局部邻近候选，位置接近仍只是待复核提议。525 项回归包含此最小化故障；重放中已生成目标 d5→d7 候选。首次几何重放遭到 qwen3.7-plus 额度耗尽，结果另存 iteration11_quota_failed.json，随后切换已通过图像测试的 2026-05-26 快照继续验证。此重放沿用 iteration10 的真实读数，只重新调用几何和独立文本复核，不能称为新的完整流水线测试。

快照模型的 iteration11 几何重放已完成，耗时 121.55 秒，**needs_review、issues=[]、acceptance_passed=false**。目标 d5→d7 已进入核查，62 与 60 两处原文及位置都保留，但文字回读仍以“数值不同说明存在台阶”为理由拒绝几何对应，而遮数阶段提供的墨线支持不能独立证明这些线是对应孔壁。因此继续保留未确认，没有强制制造 ERR-01。最新结果见 [iteration11 重放](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_fix_20261011/iteration11_neighbor_geometry_replay.json)。这明确表明剩余缺陷同时涉及 VLM 对象解释与算法缺乏尺寸界线/箭头归属验证，换模型本身没有解决。

下一步必须优先解决两个相互依赖的问题：逐行建立低分辨率明细表文字的可核对依据，避免名称错误污染安装对象；从尺寸界线、箭头及实际零件轮廓建立对象对应，避免单靠 VLM 声明或连续墨线比较不同轴。最终再在原图及同分辨率改图上进行三次完整重复验收。密钥有效与具体模型额度是两个问题；在有额度时完成的真实测试已经暴露的识别缺陷，不能归因于额度不足。

## 如何审查与后续验收

1. 先查看上述最终日志和离线重放，确认原来的 174/178 假冲突不再被规则直接判错，油封证据与父件矛盾被保留为未确认，坏节点不是直接删除。
2. 百炼配置已经可用；在系统设置核对模型 qwen3.7-plus-2026-05-26 和连接状态。如撤换聊天中暴露的密钥，只在设置页面填写、保存和测试。
3. 8788 原服务还运行旧的后端模块；模型设置会热更新，但代码修改需要重启。先在运行原服务的终端按 Ctrl+C，再运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_local_server.ps1`。启动脚本发现端口已有服务时会直接返回，不会替你重启。刷新网页以加载新前端。
4. 分别重新上传原图和改图。每张至少三次，保存新任务编号，检查源哈希、模型信息、阶段状态、BOM 行与字段、已采纳和未确认父子关系、尺寸对的原文与整页定位。历史差异提醒不能当作准确率。
5. 改图的必要验收条件：读到 60H9/h9；独立证明它与相关 62 尺寸的实体配合或连续孔关系；ERR-01 给出两处原文、原图位置、对应证据和计算依据。只有读到 60、只提示未确认、只给笼统 VLM 结论，均不算纠错检出通过。
6. 原图必要条件：不能再把 174/178 当作同一方向的同一尺寸；不能以“装配图无整体材料”作为确定性材料缺失；油封直接安装父件应由外圆所在安装孔确认，不能用唇口接触轴来替代。
7. 人工应回图确认几何关系及改值依据。系统只建议复核，不自动把尺寸改成 62；工程师尚未认证的完整装配关系仍不能标成真值。

自动测试范围针对这次缺陷及既有测试集，未声称测试了每一行或每一个分支。低分辨率 BOM 身份读取、独立几何关系识别、装配展开数量仍是主要剩余问题；需继续真实数据验收，不能靠把预期数字写入提示词“修复”。

## 配置与数据保护说明

测试没有改写四份原检测结果。测试服务与显式 Mock 任务单独标识。一次配置检查的工具输出曾意外显示旧密钥，后续输出已改为安全摘要，本报告及测试结果不包含密钥；如要分享本次完整会话，应先撤换暴露的密钥。
