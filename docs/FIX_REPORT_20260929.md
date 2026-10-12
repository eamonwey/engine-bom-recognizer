# 2026-09-29 装配识别与评测缺陷修复

对应 CODE_REVIEW_20260929.md 的 7 项问题，已修改业务源码并完成针对性复现、全量单元回归和隔离浏览器验证。

## 修复对应关系

| 问题 | 当前行为 | 主要位置 |
|---|---|---|
| 猜测下标基数导致零件错挂 | 严格使用 0 基引用；越界拒绝，不再整体平移，也不修改输入 nodes | engine_bom/assembly.py / validate_tree |
| 自纠删节点隐藏冲突 | 按 BOM 行构成的完整装配路径与用量核对重试前后结果；删除、降级、改用量不能消除旧冲突，回退保留树和证据；允许相同路径/用量的重复出现合并 | engine_bom/assembly.py / infer_assembly |
| 明细少印数量导致空树 | 数量矛盾交给对账，不当作结构错误；每父 3、明细 2 的树保留并报告 ERR-08 | engine_bom/assembly.py / validate_tree、reconcile_quantities |
| 未知用量使准确率虚高 | 分母包含全部标准已标注用量，预测未知或漏边计错；重复边用量按多重集匹配 | engine_bom/evaluation/tree_metrics.py / compare_edges |
| 人工保存丢失数量冲突 | 自动识别、人工层级保存和 BOM 编辑统一刷新对账；同步更新结构化冲突和 BOM 提示；保留其他检查提示 | engine_bom/assembly.py / update_quantity_checks；webapp.py；pipeline.py |
| 重试 API 失败丢弃已有结果 | 保留最近有效树、数量冲突、之前调用事件及失败事件，并标记 provider_failed | engine_bom/agent_loop.py；assembly.py |
| 多余根节点仍显示全部通过 | 统一验收检查根多重集、节点数、深度、用量错误、缺失/多余边、待核实项和预期发现；输出 acceptance_status 与 acceptance_issues | engine_bom/evaluation/tree_metrics.py |

人工确认但仍有数量矛盾时，状态为 reviewed_with_conflicts；quantity_status 分为 conflict、incomplete、consistent。前端显示冲突内容，修改后保存会清除已解决的装配数量提示。已复核关系不等于图纸数量正确。

模型自纠采用保守策略：已有冲突树上的路径或用量变化不能自动被视为正确修复，保留候选供人工核查；重复节点合并仍可通过。模型节点 ID 改名不会破坏匹配。

## 实际验证结果

- 全部单元测试：**237 项通过**。新增 12 项测试方法，其中删除、降级、未知用量、改数、错挂父件等使用子用例验证。
- 两项原测试明确断言旧错误行为，已更新为“拒绝猜测下标”和“保留少印数量的关系并报告冲突”。没有移除对应覆盖。
- 昨天的保存一致性、编辑审计、层级版本绑定等回归仍通过。
- 浏览器：Edge 无头模式、临时数据目录和独立 HTTP 服务。验证非法数值拒绝、旧树清空、版本同步；新增验证人工保存后 ERR-08 在层级面板和 BOM 提示中同时出现，修正每父用量后两处同时清除。
- app.js、extensions.js 均通过语法检查；浏览器无 JavaScript 运行异常。
- 修复前的 7 场景复现脚本已重新执行：根索引不再改写；删除重试保留 4 节点及冲突；少印数量保留 2 节点及冲突；API 失败保留 4 节点、2 条事件；人工保存保留冲突；未知用量准确率为 0.5；多余根节点不再显示全部通过。

可复核命令：

```powershell
python -m unittest discover -s tests -q
python scripts/test_review_fix_browser.py
python -X utf8 scripts/review_repro_20260929.py
node --check static/app.js
node --check static/extensions.js
```

新增回归：tests/test_review_fixes_20260929.py。

## 服务与限制

检查时 8788 没有监听服务，已启动当前代码，PID 30108。首页 HTTP 200、状态接口正常，首页引用 20260929-1 前端脚本。地址：http://127.0.0.1:8788/ 。

测试未调用收费视觉 API；结果证明上述逻辑缺陷的修复和已测流程通过，不代表真实图纸识别准确率已达到验收指标，也不代表全部分支覆盖。新的用量评测分母比旧版严格，历史准确率不能直接与新结果对比，应重新评测。

此次未实现历史任务重启恢复或 PDF 视觉变更识别；它们不属于本次 7 项修复。
