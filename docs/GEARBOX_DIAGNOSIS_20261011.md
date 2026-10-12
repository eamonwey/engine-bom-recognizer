# 减速器图纸重复检测、父子关系与 Φ62→Φ60 诊断

本报告依据四份真实历史结果、保存的模型原始回复、两张源图和当前源码。只进行了离线重放，没有再次调用付费 API，没有改动模型设置、服务或历史检测结果。本次任务是定位责任与原因，尚未完成生产修复。

## 结论

模型抽取/推理和系统算法两方面都有问题。模型给出的尺寸身份、零件名称、安装关系及 JSON 结构不稳定；程序的同要素归组、适用性判断、失败隔离和关系语义核验不足，把这些问题放大成不同的误报或空关系树。不能只归因于 GLM，也不能认为换模型就能解决。

用户说明原图主体正确，本报告将其作为测试预期；本次独立核对了下面列出的局部，并未据此宣称整张图已通过全部制图标准审核。

## 1. 三次原图检测确实来自同一个文件

源文件：`02_712a3b83a79032e5692f7796127137f55438bcdca7d0e74fff3ae21a56140380.png`。

不仅比对记录中的 SHA-256，还重新计算了各任务保存的源文件哈希，三份均为：

`712a3b83a79032e5692f7796127137f55438bcdca7d0e74fff3ae21a56140380`。

| 任务编号 | 模型标识 | BOM 行数 | 尺寸数量 | 进入关系树的节点 | 保留的未确认节点 | 最终图纸问题数量 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 20261011203652-87494f | GLM-5.3-Flash | 32 | 35 | 24 | 7 | 2 |
| 20261011223236-10deaf | GLM-5.3-Flash | 32 | 31 | 0 | 0 | 4 |
| 20261011224735-08bb53 | GLM-5.3-Flash | 32 | 38 | 23 | 9 | 2 |

三次关系推理的 inference_status 都为 needs_review，节点数量不能解释为“已由工程师认证的关系数量”。BOM 总行数相同也不等于各字段全部一致。

历史结果未固化完整请求、有效配置、提示词和代码版本的哈希。可以确认同一图和同一模型标识得到不同输出；不能证明三次 API 请求逐字相同，也不能计算其中多少差异纯粹来自模型随机性。当前配置 temperature=0、max_tokens=16384、reasoning_effort=low；这不是三次历史请求的完整配置证明。

## 2. 为什么其中一次没有父子关系

对任务 20261011223236-10deaf 保存的三个原始回复，通过真正的 infer_assembly/AgentLoop/validate_tree 路径重放，得到同样的零节点结果。

| 尝试 | 实际失败原因 |
| --- | --- |
| 1 | JSON 中出现 `"parent_id":n0`，n0 没有引号；JSON 解码在偏移 397 处失败。不能据此归因于输出 token 截断。 |
| 2 | 节点 n14 的 component_name 与 component_index=19 引用的 BOM 行不一致。 |
| 3 | 节点 n27 的 parent_component_index 与 parent_id 指向的节点身份不一致。 |

模型输出是直接触发因素。程序的放大因素是：一个节点存在结构错误就使整次候选树不通过；stash 只保留整棵结构校验成功的树。本次三轮均未通过，所以既没有可采纳树，也没有逐节点保留下来的可供用户确认的候选集合。

不能自动把错索引改成猜测的索引。正确的改进方向是保留原始候选、隔离身份不明或依赖错误父节点的关系，并明确展示阶段失败及原因；可靠部分只有在身份、路径、证据均可核验后才进入结果。

源码：[assembly.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/assembly.py:69)、[infer_assembly](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/assembly.py:312)、[agent_loop.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/agent_loop.py:22)。

## 3. 原图为什么会被误报空间/尺寸关系

### 3.1 把 174 和 178 当作同一总体高度

第二次原图检测把两个尺寸都标成 tag=总高、part_id=ZD100-00。程序按 `(part_id, feature_id 或 tag)` 分组，feature_id 为空时退回 tag，因此产生“174mm / 178mm 不一致”。随后 VLM 对这个错误归组给出附和解释，被合并为 rule+vlm。

图面上 174 位于上部侧向视图，178 位于水平 A-A 剖视图右边。它们表示不同投影方向上的尺寸；两条尺寸线在纸面上均竖直，不证明它们在三维实体中是同一方向、同一要素。记录甚至把 174 的视图写成“D-D（俯视图）”，而图中的 D-D 是右侧的轴截面局部。

这里既有模型视图/要素身份识别错误，也有规则缺少几何身份约束的问题。当前跨视图检查主要校验视图名称是否出现，不能证明实际比较的是同一要素。重复让同一模型复核，并不是独立的几何验证。

### 3.2 把两个不同轴的尺寸混在一起

修改图的结果把 C-C 的 Φ24h7 和 D-D 的 Φ18h7 都命名为“轴伸直径”，并当作同一标记矛盾。图中两处属于不同轴，数值不同本身合理。

同样，它把 8、6 和 Φ12H8h7 归为“键槽宽”，又把 Φ47、Φ60、Φ62 都归为“轴承座孔直径”。这是不同部位或不同种类尺寸被相同语义名称归组。

最小反例重放：仅输入两个不同轴的 Φ18h7/Φ24h7，共享 tag 时规则报矛盾；保持数值不变，赋予不同 feature_id 后不再报矛盾。这证明该规则本身存在误报入口，不能全部归咎于模型数值读错。

还有“Φ52h9 / Φ52mm 不一致”：名义直径都是 52。当前规范化函数会把带配合代号的标注保留为字符串，而把纯数值归一化成带 mm 的字符串。配合信息缺失是否应报告需要另行判断，不能把它描述为名义数值不一致。

源码：[check_dimensions](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/inspect_rules.py:157)、[_canonical_dimension](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/inspect_rules.py:185)、[hybrid_inspection.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/hybrid_inspection.py:111)、[merge_findings](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/hybrid_inspection.py:287)。

### 3.3 油封父件错误没有被复核拦住

按本系统当前“直接安装承载对象”的安装关系语义，件21油封20×35×7应归到件20输入轴透盖。油封唇口接触齿轮轴，不等于轴是它的直接安装父件。

第一次原图结果：件21 → 输入轴透盖。第三次原图结果：件21 → 齿轮轴；后者 verification_evidence 仍明确写着“油封20×35×7嵌入输入轴透盖(20)孔内，唇口贴齿轮轴轴颈”。证据描述的安装对象与实际 parent_id 不一致，却仍通过复核。

当前验证器检查索引、无环、字段齐全、视图/配合特征文字存在，并不验证这些文字与图像接触、容纳关系或具体父件一致。模型的 confident/support/keep 不能充当人工认证。

源码：[installation_review.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/installation_review.py:52)、[validate_tree](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/engine_bom/assembly.py:140)。

## 4. Φ62 改 Φ60 到底有没有被读取

修改任务：20261011221848-19b051，文件 `齿轮减速器工程蓝图剖视图.png`。

查看保存图像后，修改处在 A-A 剖视左下方输出轴端盖定位配合尺寸：原图为 Φ62H9/h9，修改图为 Φ60H9/h9。严格说这里是带直径符号的配合标注，不是一般线性长度尺寸链。

原图局部：

![原图输出端配合62](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_diagnosis_20261011/20261011203652-87494f_output_end_fit.png)

修改图局部：

![修改图输出端配合60](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_diagnosis_20261011/20261011221848-19b051_output_end_fit.png)

历史 dimensions 中确实存在 value=`Ø 60H9/h9`。因此“模型完全没有看到60”不符合这份记录。

实际失败是：记录没有完整抽取上端的另一处 Φ62H9/h9，且修改尺寸的 bbox=null、feature_id为空、part_id仅为总成图号。规则把它与输入轴一侧的 Φ47H9/h9、轴承座的 Φ62J7 混组，只给出一组值不一致，不能准确定位和解释你修改的端盖配合。

该次主视觉检查连续三轮未通过输出协议：先缺 ERR-01～ERR-10 coverage，最后连 issues 数组也缺失。visual_status=needs_review，focus_sweep=not_run。最终问题列表是规则输出，没有成功的第二层视觉结果来准确定位这一处。

所以要区分三个指标：读到60（本次做到）；发现一组有差异（本次有模糊报警）；准确定位并说明这个端盖配合为何异常（本次未做到）。不能把三者混成“成功检出”。

当前源码已含 check_bearing_fits，文件修改时间22:56:33晚于上述检测。现在对同一份保存尺寸重放，会额外输出“60与6206对应62疑似不符”；这条精准一些的消息不在历史记录中，不能算当时成功。该规则仍按 tag 含“轴承”和近似值筛选，没有验证具体配合对象，不能直接用它证明端盖尺寸必须等于轴承外径。更可靠的依据是读清尺寸界线及端盖定位面与箱体孔的对应关系。

原图5887×3854，修改图1550×1014；两者不是严格保持图像采样一致的单变量测试。当前图像入口默认把长边限制为2240，后续裁切通常来自已缩小图像；它会损失密集小字信息，是潜在放大因素，但本次60已经读到，不能把这次定位失败完全归因于分辨率。

## 5. 标题栏材料误报

三次同一装配图的 material_applicable 分别为 false、true、null。第二次因此触发“材料字段为空”，其余两次没有触发。模型给出适用性变化，规则直接把声明为true当作适用依据，缺少装配图范围及图框字段的交叉约束。按用户指定原图预期，材料空白不能无条件算设计错误。标题签署和日期空白可保留为用户认可的格式检查范围。

## 6. 修复优先级与验收方式

1. **阻止不同要素混比**：先建立视图方向、零件身份、几何要素与尺寸界线/位置，再关联尺寸；只有语义名称时不生成确认矛盾，保留未核实观察。名义值、配合、公差分开比较。
2. **补全局部证据**：保留原始高分辨率图像，整页用于上下文，尺寸与引线区域单独裁切重读；关键异常必须能定位到具体尺寸和配合对象。失败时不能显示该类别已经完整检查。
3. **加固安装关系**：区别直接安装、轴唇接触、成员归属；针对“证据中的安装对象与parent_id不同”进行约束。格式正确不能升级为工程上正确；不明关系保留候选和理由。
4. **逐节点隔离结构错误**：保留可审查的候选与失败来源，限制错误依赖的传播，不因为一处引用失败丢掉整个候选集合，也不猜测修正索引。
5. **固定重复测试条件**：记录配置、代码/提示词版本、原图与裁切哈希、实际请求参数、响应结束原因，分别统计抽取准确率、关系正确率、误报率、漏报率和重复一致率。

局部验收基准至少包含：原图174/178不误报；两个轴Φ24/Φ18和键槽8/6不混比；件21油封直接安装父件为件20输入轴透盖；原图输出端盖配合Φ62不误报；修改图左下Φ60正确定位且不掺入右侧Φ47；格式错误时保留待审候选并明确失败状态。

先做保持原图分辨率和内容不变、只改目标62→60的受控测试图；再对相同有效配置多次运行。测试该局部的配合关联，不把任意改数都当作必然的工程错误。现有四次记录不足以给模型或整个系统一个可靠的总体准确率。

## 7. 可复现证据

运行：

```powershell
cd "C:\Users\v10\Documents\ChatGPT\工艺\engine-bom-recognizer"
python -X utf8 scripts\diagnose_gearbox_records.py
```

脚本没有网络请求。对原检测记录一致性检查，预期退出码为1：同文件哈希检查通过，关系树缺失、尺寸数量和关系不稳定检查失败。这是诊断复现，不能作为修复后通过报告。

原始记录汇总：[record_audit.json](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_diagnosis_20261011/record_audit.json)。

实际代码路径重放和最小归组反例：[stage_replay.json](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/data/acceptance/gearbox_diagnosis_20261011/stage_replay.json)。

脚本：[diagnose_gearbox_records.py](C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer/scripts/diagnose_gearbox_records.py)。

本报告只完成诊断；生产修复、API端到端复测和蓝框持久化编辑仍待完成。此前单次最佳输出或合成图测试，不能代替这次真实图纸重复一致性验证。
