# 项目全景与 AI 交接文档

> 2026-10-11 增补：本文主体为 2026-09-16 的历史快照，目录、模型及完成度不能直接当作现状。本轮一维装配公差链、区域定位补边、测试产物及能力边界见 [本轮报告](TOLERANCE_CHAIN_AND_LAYOUT_20261011.md)，操作步骤已补入 USER_MANUAL.md。当前工作目录为 `C:/Users/v10/Documents/ChatGPT/工艺/engine-bom-recognizer`。本轮最终全库测试448项通过；8个合成PNG真实API公差样例符合预期，不能替代独立工程师真值准确率。

> **文档用途**：本文件是整个项目从需求确认到当前实现状态的完整快照，供**其他 AI 助手或新加入的工程师**作为资料库导入阅读。
> 读完本文件，你应当能够：理解项目目标与全部需求、知道每个功能已经做到了什么程度、**准确定位到需要修改的代码文件**、避免重复实现已完成的部分、并避开已经踩过的坑。
>
> **最后更新**：2026-09-16
> **项目根目录**：`C:\Users\v10\.zcode\workspace\default\engine-bom-recognizer`
> **配套文档**：同目录 `README.md`（面向使用者的安装/使用手册）；本文件（面向开发者的全貌与交接）

---

## 目录

1. [项目一句话说明](#1-项目一句话说明)
2. [需求来源与完整需求清单](#2-需求来源与完整需求清单)
3. [硬约束及对架构的强制影响](#3-硬约束及对架构的强制影响)
4. [已完成功能的状态映射表](#4-已完成功能的状态映射表)
5. [系统架构与数据流](#5-系统架构与数据流)
6. [文件索引：改哪里实现什么](#6-文件索引改哪里实现什么)
7. [数据格式规范](#7-数据格式规范)
8. [评测指标体系与口径定义](#8-评测指标体系与口径定义)
9. [Web 界面与 REST API](#9-web-界面与-rest-api)
10. [运行环境与命令速查](#10-运行环境与命令速查)
11. [关键设计决策与理由](#11-关键设计决策与理由)
12. [已踩过的坑与已修复的缺陷（勿重犯）](#12-已踩过的坑与已修复的缺陷勿重犯)
13. [对话历史时间线](#13-对话历史时间线)
14. [待办事项与明确不要重复做的事](#14-待办事项与明确不要重复做的事)
15. [验证基线（当前正确状态）](#15-验证基线当前正确状态)
16. [术语表](#16-术语表)

---

## 1. 项目一句话说明

**构建一套"发动机工程图纸/技术文档 → 结构化 BOM"的智能识别系统**：输入 PDF、图片、Word 图纸或工艺文档，输出结构化 BOM（JSON/CSV/Excel）与提取出的关键要素，附带人工复核界面、图纸错误规则检查、文件版本变更对比与量化评测框架。

系统当前有两条使用路径：

- **Web 界面**（`http://127.0.0.1:8787`，六个功能页）——给工程师日常使用
- **命令行**（`python -m engine_bom.cli ...`）——给批量处理与对照实验使用

视觉模型通过 **Provider 接口插拔**：内置离线 Mock（无网络也能跑通全流程）与 OpenAI 兼容 API 实现（可对接阿里百炼的 Qwen3.8-Max，也可对接**内网私有化部署的 vLLM 服务**跑 Qwen2.5-VL / InternVL 等开源模型）。

### 学术参照

实现思路对齐以下论文的框架（论文原文在用户机器上有缓存副本，路径见 §2.3）：

> Yu-Chi Lin, Jr-Fong Dang. *From product specifications to smart manufacturing: Generative AI-driven process innovation for BOM digitization and its applications.* **Advanced Engineering Informatics** 71 (2026) 104451.
> 核心方法：**LLM + RAG 的 BOM 数字化闭环**——多阶段文档解析 → 知识检索增强 → 约束解码 → JSON-Schema 校验 → 人工复核 → 写回企业系统（x-EDBOM）。论文报告 10 折交叉验证下平均准确率 91%、单件处理时间从 25 分钟降到 2 分钟。

本系统把该框架工程化为**可运行、可评测、可插拔模型**的代码，并额外落地了用户方需求表中的"图纸错误检测"与"文件变更控制"两大块。

---

## 2. 需求来源与完整需求清单

### 2.1 需求文档位置

| 项 | 位置 |
|---|---|
| 需求规格表（Excel，3 个 sheet） | `C:\Users\v10\Desktop\AI工艺项目需求规格表.xlsx` |
| Sheet 1 | `1-项目概述与约束`（项目背景、三个核心需求概述、5 条硬约束、约束影响分析） |
| Sheet 2 | `2-功能需求规格`（18 条子功能，含输入/输出/优先级 P0-P2/难度/验收标准） |
| Sheet 3 | `3-图纸错误检测需求`（10 类图纸错误 ERR-01~ERR-10，含检测逻辑/方式/优先级） |
| 版本 | V1.0，编制日期 2026-09-10 |

### 2.2 三个核心需求（原文）

| 需求编号 | 需求名称 | 一句话描述 | 技术方向 |
|---|---|---|---|
| REQ-01 | 图纸BOM自动构建 | 从复杂产品图纸中自动识别零部件信息、构建多级BOM并导出 | VLM+CV+LLM |
| REQ-02 | 文档关键要素提取 | 从技术/工艺文件中自动提取技术参数、材料、工艺要求、检验标准等结构化信息 | VLM/LLM+信息抽取 |
| REQ-03 | 文件变更智能控制 | 对文件不同版本进行自动对比、变更识别、变更影响分析、变更单辅助生成 | LLM文档对比+知识推理 |

项目背景原文要点：产品图纸复杂（复杂装配图/系统图，标注密集、层级多）；需自动判别图纸错误（尺寸矛盾、缺漏标注、公差错误、视图不一致等）；需从图纸和文件中自动提取结构化信息。

### 2.3 18 条子功能需求（Sheet 2 完整清单）

**需求 1：图纸BOM自动构建（REQ-01）**

| 子功能 | 功能描述摘要 | 输入 | 输出 | 优先级 | 验收标准 | 备注 |
|---|---|---|---|---|---|---|
| 图纸格式解析：多格式图纸接入与预处理 | 支持 CAD 源文件(DWG/DXF)、矢量PDF、扫描件/图片(PNG/JPG)；对扫描件去噪、倾斜校正、二值化；自动识别图框边界 | CAD/矢量PDF/扫描图片 | 标准化图纸图像+元数据 | P0 | 支持 5 种格式；扫描件预处理后文字可识别率≥90% | CAD 优先原生解析，扫描件走 OCR+版面分析 |
| 标题栏信息提取 | 自动定位标题栏，提取图名、图号、材料、比例、重量、设计/审核/批准人员、日期 | 标准化图纸图像 | 结构化标题栏信息(JSON) | P0 | 定位准确率≥95%；关键字段准确率≥90% | 标题栏格式因企业而异，需模板配置+少样本适配 |
| 明细栏/零部件信息提取 | 识别明细栏区域，解析表格结构，提取序号、代号、名称、数量、材料、备注；支持跨页明细栏合并 | 标准化图纸图像 | 零部件信息列表(JSON/表格) | P0 | 明细栏定位≥90%；零部件信息提取准确率≥85% | 复杂装配图明细栏可能跨多页 |
| 装配层级关系识别 | 基于装配图视图、引出序号、明细栏序号对应关系，推理父子件关系，构建多级 BOM 树 | 零部件信息+图纸视图 | 多级BOM树(JSON) | P1 | 一级装配关系≥80%；支持至少 3 级 | **难点**：2D 反推 3D 有不确定性；初期只做一级装配，多级靠规则+人工确认 |
| BOM结构化生成与导出 | 整合为标准 BOM；导出 Excel、CSV、JSON；与 ERP/PLM 导入格式对接 | 多级BOM树 | BOM文件(Excel/CSV/JSON) | P0 | 与客户 ERP/PLM 导入格式一致；导出数据完整无遗漏 | 需提前确认客户 ERP 的 BOM 导入模板 |
| 图纸与BOM一致性校验 | 对比图纸明细栏数量与 BOM 数量；校验物料编码是否符合企业编码规则；标记疑似不一致项 | 明细栏信息+BOM | 一致性校验报告(差异清单) | P1 | 数量不一致检出率≥95%；编码规则违规检出率≥90% | 规则可配置，企业编码规则不同 |

**需求 2：文档关键要素提取（REQ-02）**

| 子功能 | 功能描述摘要 | 输入 | 输出 | 优先级 | 验收标准 | 备注 |
|---|---|---|---|---|---|---|
| 多格式文件解析：多格式接入与版面还原 | 支持 Word(.doc/.docx)、PDF(文本/扫描)、图片；扫描件 OCR；还原版面结构（标题/段落/表格/列表）；表格跨页合并 | Word/PDF/扫描图片 | 结构化文档内容(含版面) | P0 | 支持 4 种格式；OCR 准确率≥90%；表格结构还原≥85% | 建议用开源 Docling/PaddleOCR PP-StructureV3 |
| 技术参数提取 | 提取参数名+数值+单位+适用条件（尺寸/性能/电气参数等）；支持参数表和文本描述两种形式 | 结构化文档内容 | 技术参数列表(JSON) | P0 | 参数名-值-单位三元组准确率≥85%；支持≥20 类参数 | 参数命名因行业而异，需自定义参数字典 |
| 材料与工艺要求提取 | 提取材料牌号、规格、热处理、表面处理、加工工艺要求；识别材料标准引用(如 GB/T 牌号) | 结构化文档内容 | 材料与工艺要求列表(JSON) | P0 | 材料牌号≥90%；工艺要求≥80% | 材料牌号有国标体系，可结合材料知识库校验 |
| 检验标准与质量要求提取 | 提取检验项目、方法、验收标准、公差要求、引用标准编号、不合格处理要求 | 结构化文档内容 | 检验标准列表(JSON) | P1 | 检验项目≥85%；标准编号识别≥90% | 标准编号格式规范，可正则+LLM 结合 |
| 结构化输出与系统对接 | 整合统一 JSON；导出 Excel；提供 REST API 给 PLM/MES/ERP 调用；支持按客户系统定制字段映射 | 各类要素列表 | 结构化数据(JSON/Excel)+API | P0 | JSON schema 稳定可版本化；API 响应≤3 秒/份 | API 需内网部署 |
| 人工复核与修正机制 | Web 界面展示提取结果，高亮原文位置，支持修改/确认/驳回；记录人工修正数据用于模型迭代；支持批量与单条复核 | 提取结果+原文 | 复核确认后的数据+修正记录 | P0 | 复核界面可定位原文；修正记录完整可追溯；支持≥3 级复核权限 | 修正数据是后续微调的重要数据源 |

**需求 3：文件变更智能控制（REQ-03）**

| 子功能 | 功能描述摘要 | 输入 | 输出 | 优先级 | 验收标准 | 备注 |
|---|---|---|---|---|---|---|
| 多版本文件对齐与解析 | 上传变更前后两个版本；按段落/表格/章节语义对齐；处理段落重排、跨页移动、格式变化；支持 Word 和 PDF | 变更前文件+变更后文件 | 对齐后的文档对(含段落映射) | P0 | 段落对齐≥90%；支持段落重排；≤30 秒/百页 | 纯文本 diff 无法处理重排，需句向量+规则混合对齐 |
| 变更内容自动识别与高亮 | 自动识别新增/删除/修改；对比界面用颜色高亮（新增=绿/删除=红/修改=黄）；支持按变更类型筛选和定位 | 对齐后的文档对 | 变更内容清单+高亮对比界面 | P0 | 检出率≥95%；误报率≤10%；支持按章节/页码定位 | **对漏报零容忍，宁可多报不可漏报**；需支持"忽略格式变化" |
| 变更类型分类 | 分类为：技术参数修改、材料替换、工艺调整、标准更新、格式/排版修改、错别字/措辞修改、其他；支持自定义；可人工修正 | 变更内容清单 | 带类型标签的变更清单 | P1 | 分类准确率≥80%；支持≥6 类预定义 | 分类可辅助影响分析和变更单生成 |
| 变更影响范围分析 | 基于变更内容，通过知识图谱/RAG 检索受影响的关联文档、产品BOM、工序、检验项；输出影响清单和程度(高/中/低) | 变更内容+企业知识库/关联索引 | 影响分析报告 | P2 | 影响对象召回率≥70%；程度评估一致率≥60% | **难点**：需企业有完整文档关联关系；初期可只做关键词关联检索 |
| 变更单/ECN自动生成辅助 | 基于变更内容和影响分析，自动生成变更申请单(ECN/ECR)草稿：变更原因、内容摘要、影响范围、建议措施；支持企业模板定制 | 变更内容+影响分析 | 变更申请单草稿(Word/PDF) | P1 | 字段填充完整率≥90%；格式与企业模板一致 | 需提前获取企业变更单模板 |
| 变更历史追溯与查询 | 记录每次变更完整信息（时间、人、内容、类型、审批状态）；支持按文件/时间/类型/人查询 | 变更记录 | 变更历史数据库+查询界面 | P1 | 记录完整可追溯；查询响应≤2 秒 | 可与 PLM 变更流程对接 |

### 2.4 图纸错误检测需求（Sheet 3 完整清单）

检测方式说明：规则引擎=确定性规则；CV识别=计算机视觉；VLM推理=视觉语言模型；混合=多种结合。
需求表实施建议原文：**第一阶段优先实现 P0 且检测方式为"规则引擎"的错误类型（材料不明、标题栏错误、尺寸矛盾中的数值比对），快速见效；VLM 推理类错误作为第二阶段，需积累标注数据。**

| 编号 | 错误类型 | 检测逻辑说明 | 检测方式 | 优先级 | 难度 |
|---|---|---|---|---|---|
| ERR-01 | 尺寸矛盾 | 提取所有尺寸标注及数值，比对同一几何要素在不同视图的标注值；对尺寸链数学计算校验 | 规则引擎+CV尺寸识别 | P0 | 高 |
| ERR-02 | 缺漏标注 | 基于零件类型和视图，检查应标注而未标注的尺寸/公差/粗糙度/技术要求；对照企业制图标准检查完整性 | 规则引擎+VLM推理 | P0 | 高 |
| ERR-03 | 公差错误 | 解析公差标注格式，对照 GB/T 校验格式合法性；结合配合类型（孔/轴）判断公差带合理性 | 规则引擎+CV符号识别 | P1 | 中 |
| ERR-04 | 形位公差错误 | 识别形位公差框格内容，检查基准引用是否存在/对应；公差项目与标注要素是否匹配 | 规则引擎+CV符号识别 | P1 | 高 |
| ERR-05 | 视图不一致 | 比对各视图的对应尺寸和轮廓；基于零件复杂度检查视图数量是否充分 | VLM推理+规则 | P1 | 高 |
| ERR-06 | 材料不明/矛盾 | 提取标题栏材料字段，检查非空和格式规范；比对技术要求中的材料描述；对照材料标准库校验牌号合法性 | 规则引擎+LLM校验 | P0 | 低 |
| ERR-07 | 标准件/通用件错误 | 解析标准件代号，对照标准件库校验规格合法性；检查引用标准时效性 | 规则引擎+标准件知识库 | P2 | 中 |
| ERR-08 | 标题栏/明细栏错误 | 检查标题栏必填字段完整性；比对明细栏序号与图中引出序号；校验数量合理性 | 规则引擎+CV识别 | P0 | 中 |
| ERR-09 | 技术要求缺失/不规范 | 基于零件类型检查应有的技术要求项；解析技术要求中的标准引用，校验时效性 | VLM推理+规则+知识库 | P1 | 中 |
| ERR-10 | 图纸格式/规范错误 | 检查图幅比例是否标准；字体/线型/标注样式是否符合企业模板；图层使用规范 | 规则引擎 | P2 | 低 |

---

## 3. 硬约束及对架构的强制影响

| 编号 | 约束 | 对项目的影响（需求表原文） | 在代码中的落实 |
|---|---|---|---|
| C-01 | **图纸不能拿出厂区**，真实图纸必须在客户内网处理，无法使用外部云 API 或 SaaS，模型推理必须离线/内网部署 | 所有数据本地化 | Web 服务为**纯 Python 标准库实现（零第三方依赖）**，无任何外发请求；上传件、任务产物、复核记录全部落在本机 `data/` 目录；Provider 的 `base_url` 可指向内网地址 |
| C-02 | **模型训练必须在内网完成**，不能用 OpenAI/Anthropic 等外部 API 训练或微调；必须选用可私有化部署的开源模型（Qwen2-VL、InternVL、LayoutLM 等）；需客户提供内网 GPU 服务器 | 技术路线必须开源可私有化 | Provider 走 OpenAI 兼容协议，可直接对接内网 vLLM/LMDeploy 服务（`http://内网IP:8000/v1`）；首页与 README 明确该部署方式 |
| C-03 | **无公开数据集可用**，FUNSD/CORD/DocLayNet 等与复杂工程图纸差异大，必须自建标注数据集 | 不能依赖公开数据 | 系统自带评测框架与标注格式定义（`data/annotations/`），标注即用于评测；Mock 与演示数据用于无数据集阶段验证链路 |
| C-04 | **自建数据集须在内网标注**，标注工具/流程/人员均在内网完成，需业务专家参与，周期预计 2-4 个月 | 数据是关键路径 | 标注格式与系统输出同构，可用系统预测结果做预标注后人工修正（`data/reviewed/` + `review_log.json` 即修正记录来源） |
| C-05 | **图纸复杂度高**，复杂装配图/系统图标注密集、层级多、视图关系复杂，简单 OCR+模板方案无法覆盖，需要版面分析+语义理解+规则引擎结合 | 需要多技术融合 | 采用"VLM 语义识别 + 规则引擎校验 + 人工复核"的组合架构，而非纯 OCR 模板方案 |

其他影响（需求表 Sheet1 区域 D 原文摘要）：必须选用开源可私有化模型；必须采用"合成数据预训练 + 内网真实数据微调 + 少样本 Prompt 工程"的混合策略，**第一阶段 MVP 应优先用零样本/少样本方案降低数据依赖**；数据标注和内网环境搭建是关键路径，预计占项目总周期 30-40%，MVP 应聚焦数据需求最少的功能；数据质量和标注一致性是最大风险。

---

## 4. 已完成功能的状态映射表

图例：✅ 已实现并可运行 ｜ ⏳ 已预留接口/未实现 ｜ ❌ 未开始

### REQ-01 图纸 BOM 自动构建

| 子功能 | 状态 | 实现位置 |
|---|---|---|
| 多格式图纸接入与预处理 | ✅ PDF/PNG/JPG/BMP/TIF/WEBP + 扫描件去噪/倾斜校正/二值化/对比度增强；DWG/DXF 明确报错并提示内网转换方案 | `engine_bom/ingestion.py`、`engine_bom/preprocess.py` |
| 标题栏信息提取 | ✅ VLM 提取 11 个字段 + 必填字段校验 + Web 端键值展示 | `engine_bom/titleblock.py` |
| 明细栏/零部件信息提取 | ✅ 核心功能：逐页识别 + 跨页去重合并 + 14 字段结构化 | `engine_bom/pipeline.py`、`engine_bom/parsing.py`、`engine_bom/schema.py` |
| 装配层级关系识别 | ⏳ 未实现（需求表自身建议初期只做一级装配+人工确认）；引出序号已能抽取，可作为层级推理输入 | `engine_bom/titleblock.py::extract_dims_and_balloons` 已产出 balloons 数据 |
| BOM 结构化生成与导出 | ✅ JSON / CSV(utf-8-sig，Excel 直开) / XLSX；ERP/PLM 字段映射待客户模板 | `engine_bom/export.py` |
| 图纸与 BOM 一致性校验 | ✅ 件号重复、数量缺失/非正数、置信度越界、序号连续性、引出序号与明细栏对应 | `engine_bom/schema.py::validate_components`、`engine_bom/inspect_rules.py` |

### REQ-02 文档关键要素提取

| 子功能 | 状态 | 实现位置 |
|---|---|---|
| 多格式文件解析 | ✅ .docx（标准库 zipfile+XML 解析段落与表格）/ .pdf（PyMuPDF 文本层，文本过薄自动判定为扫描件走 VLM）/ .txt / .md / 图片 | `engine_bom/docextract.py::parse_document` |
| 技术参数提取 | ✅ 参数名/数值/单位/适用条件/来源 五元组 | `engine_bom/docextract.py` |
| 材料与工艺要求提取 | ✅ 名称/牌号/规格/标准/热处理 五元组 + 工艺要求描述 | 同上 |
| 检验标准与质量要求提取 | ✅ 检验项目/方法/验收标准/引用标准 | 同上 |
| 结构化输出与系统对接 | ✅ 统一 JSON + Excel 导出 + REST API（异步任务，避免长请求阻塞） | `engine_bom/webapp.py`、`engine_bom/docextract.py::elements_to_rows` |
| 人工复核与修正机制 | ✅ Web 端表格逐格编辑 + 保存为复核结果 + 修正记录留档（`data/reviewed/`、`data/review_log.json`）；原件位置高亮与 3 级权限未实现 | `static/app.js`、`engine_bom/webapp.py::_api_bom_save/_api_doc_save` |

### REQ-03 文件变更智能控制

| 子功能 | 状态 | 实现位置 |
|---|---|---|
| 多版本文件对齐与解析 | ✅ 段落级对齐（`difflib.SequenceMatcher` + 相似度阈值配对修改项）；句向量对齐为内网升级项 | `engine_bom/changedetect.py::align_and_diff` |
| 变更内容自动识别与高亮 | ✅ 新增/删除/修改三类 + 前端绿/红/黄高亮 + 按类型筛选 + 「忽略纯格式变化」开关 | `changedetect.py`、`static/app.js` |
| 变更类型分类 | ✅ 6 类 + 其他，规则关键词打分（可替换为 LLM 调用） | `changedetect.py::classify_change` |
| 变更影响范围分析 | ⏳ 未实现（P2，需企业知识图谱）；ECN 草稿中已留"影响范围（初评）"占位段落 | `changedetect.py::generate_ecn_md` |
| 变更单/ECN 自动生成辅助 | ✅ Markdown 草稿（单据编号/文件/变更摘要表/影响初评/建议措施），可在 Web 端一键下载 | `changedetect.py::generate_ecn_md` |
| 变更历史追溯与查询 | ✅ 追加式 JSON 记录 + 按文件名/分类过滤 + Web 端表格 | `changedetect.py::append_history/load_history` |

### 图纸错误检测

| 编号 | 状态 | 实现位置与说明 |
|---|---|---|
| ERR-01 尺寸矛盾 | ✅ 数值比对部分 | `inspect_rules.py::check_dimensions`：同标记在不同视图数值不一致即报；尺寸链数学校验未实现 |
| ERR-02 缺漏标注 | ❌ 第二阶段 | 需 VLM 语义推理 + 标注数据 |
| ERR-03 公差错误 | ❌ 第二阶段 | 需 CV 符号识别 + GB/T 公差表 |
| ERR-04 形位公差错误 | ❌ 第二阶段 | 同上 |
| ERR-05 视图不一致 | ❌ 第二阶段 | 需 VLM 推理 |
| ERR-06 材料不明/矛盾 | ✅ | `inspect_rules.py::check_titleblock`：空值检测 + 常见国标牌号正则库校验（`_MATERIAL_BRAND_PATTERNS`） |
| ERR-07 标准件错误 | ❌ 第二阶段 | 需标准件知识库 |
| ERR-08 标题栏/明细栏错误 | ✅ | `inspect_rules.py`：`check_titleblock`（必填字段完整性）、`check_bom_table`（图号重复/数量缺失/序号连续性）、`check_balloon_consistency`（引出序号 vs 明细栏序号双向对应） |
| ERR-09 技术要求缺失 | ❌ 第二阶段 | 需 VLM + 知识库 |
| ERR-10 图纸格式/规范错误 | ❌ 第二阶段 | 需 CAD 图层/线型信息，图片输入不可得 |

### 系统级能力（需求表之外但为支撑上述需求而建）

| 能力 | 位置 |
|---|---|
| 可插拔视觉模型 Provider（Mock / OpenAI 兼容） | `engine_bom/providers/` |
| 提示词版本化管理（可复现实验） | `engine_bom/prompts.py`（当前 v1） |
| 企业命名规则知识库检索注入（RAG 简化版） | `engine_bom/knowledge.py` |
| 数据集评测（检测指标 + 字段指标 + 报告） | `engine_bom/evaluation/` |
| 多 run 对照实验与跨模型对比 | `engine_bom/experiment.py`、`configs/experiment_demo.yaml` |
| 原始模型输出留档（审计/调试/人工复核依据） | `data/predictions/traces/*.trace.json` |
| Web 界面（6 个功能页） | `static/`、`engine_bom/webapp.py` |
| 单元测试（以测试发现结果为准） | `tests/` |

---

## 5. 系统架构与数据流

```
输入：PDF / 图片 / Word / TXT
   │
   ▼
┌──────────────────────────────────────────────────────────────┐
│ Step1 文档解析与预处理                                        │
│  ingestion.py   PDF 按 DPI 渲染为页面图像；图片直载；长边缩放   │
│  preprocess.py  扫描件去噪 / 倾斜校正 / 二值化 / 对比度（OpenCV）│
│  docextract.py::parse_document  docx/pdf/txt 文本抽取         │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Step2 模型识别（Provider 可插拔，提示词带 TASK 标记分流）        │
│  providers/base.py          VisionProvider 抽象接口            │
│  providers/mock.py          离线确定性 Mock（按 TASK 返回样例）  │
│  providers/openai_compat.py ← ★ 视觉模型 API 接入点            │
│  prompts.py                 BOM 识别提示词（v1，中英双语规则）   │
│  titleblock.py              标题栏 + 尺寸标注/引出序号抽取       │
│  docextract.py              技术参数/材料工艺/检验标准提取       │
│  knowledge.py               企业规则检索注入（RAG 简化版，可选）  │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Step3 解析与多层校验                                          │
│  parsing.py      鲁棒 JSON 提取（代码块/尾逗号/智能引号容错）    │
│  schema.py       类型清洗 → 跨页去重合并 → 校验（件号冲突等）    │
│  inspect_rules.py ERR-01/06/08 规则检查（含严重度与整改建议）    │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Step4 装配、导出与复核                                        │
│  export.py   JSON / CSV / XLSX（文件被占用时自动改名）          │
│  webapp.py   REST API + 任务队列 + 复核记录 + 运行时配置        │
│  static/     单页前端（6 个功能页，无构建步骤）                  │
│  traces/     每页模型原始输出留档                              │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
   评测评价  evaluation/  +  experiment.py（多 run 对照）
```

**Web 请求时序**：前端 `fetch` 上传文件 → 服务端创建 job（`data/web_jobs/<job_id>/`）→ 后台线程执行 → 前端每 1.5 秒轮询 `/api/jobs/<id>` → `status=done` 后取 `result` 渲染。任何单任务异常都落到 job 状态里，不影响服务进程。

---

## 6. 文件索引：改哪里实现什么

> 全部路径相对项目根目录 `C:\Users\v10\.zcode\workspace\default\engine-bom-recognizer`

### 6.1 后端核心（`engine_bom/`，共 3617 行）

| 文件 | 行数 | 职责 | 想改什么就改这里 |
|---|---|---|---|
| `schema.py` | 312 | BOM 数据结构、字段别名映射、类型强制、跨页去重合并、校验、文本归一化 | 增加/修改 BOM 字段 → `COMPONENT_FIELDS` 与 `BomComponent`；改去重规则 → `_dedup_key`；改校验规则 → `validate_components`；改数量合并策略 → `merge_components(quantity_policy=...)` |
| `config.py` | 102 | 默认配置、YAML/JSON 加载、深合并、`cfg_get`/`resolve_output_dir` | 新增配置项 → `DEFAULT_CONFIG`；改默认超时/重试/DPI/预处理开关 |
| `ingestion.py` | 106 | PDF 渲染（PyMuPDF）、图片加载、缩放、预处理挂钩、DWG/DXF 报错提示 | 改渲染 DPI/长边限制 → `DEFAULT_CONFIG["ingestion"]`；接入 CAD 原生解析 → `load_document` 的分支 |
| `preprocess.py` | 54 | 扫描件预处理（OpenCV，未安装自动降级） | 调整去噪强度/角度阈值 → `preprocess_image`、`_deskew` |
| `prompts.py` | 79 | 提示词模板与版本注册表（当前 v1） | **调识别质量改这里**：`_RULES`（提取规则）、`_SCHEMA_HINT`（输出结构示例）、发动机功能系统分类列表；新增版本 → `PROMPTS` 加 `v2` 并把配置的 `prompt_version` 升级 |
| `parsing.py` | 84 | 模型输出 → 结构化：JSON 代码块/尾逗号/智能引号容错 | 模型返回格式异常时 → `extract_json_payload`、`_repair_common_issues` |
| `pipeline.py` | 213 | 端到端编排：逐页/整档识别、合并、校验、导出、trace 落盘、批量容错 | 改识别流程 → `process_file`；改 trace 结构 → `_trace_entry` |
| `knowledge.py` | 70 | 企业规则知识库（txt 关键词检索，RAG 简化版） | 换成向量检索 → 实现 `KnowledgeBase` 子类并在 `build_knowledge` 注册 |
| `export.py` | 95 | JSON/CSV/XLSX 导出，文件占用自动改名 | 加导出格式 → `_write_one`；改 CSV 表头 → `CSV_HEADERS` |
| `titleblock.py` | 112 | 标题栏字段提取 + 尺寸标注/引出序号抽取（供规则检查） | 改标题栏字段 → `TITLE_FIELDS`；改必填项 → `REQUIRED_TITLE_FIELDS`；改提示词 → `build_titleblock_prompt`、`_DIMS_PROMPT` |
| `inspect_rules.py` | 165 | 图纸规则检查（ERR-01/06/08）+ 问题清单结构 | 扩充材料牌号库 → `_MATERIAL_BRAND_PATTERNS`；新增错误类型 → `make_issue` + `run_all_checks`；改错误类型元数据 → `_ERR_META` |
| `docextract.py` | 178 | 文档解析 + 四类要素提取 + Excel 行扁平化 | 加要素类别 → `EXTRACT_SCHEMA` 与 `_EXTRACT_PROMPT`；改解析 → `parse_document`/`_parse_docx`/`_parse_pdf` |
| `changedetect.py` | 158 | 版本对齐、变更识别、类型分类、ECN 草稿、历史记录 | 改变更类型 → `CHANGE_CATEGORIES`；换 LLM 分类 → `classify_change`；改 ECN 模板 → `generate_ecn_md`；上句向量 → `align_and_diff` |
| `experiment.py` | 158 | 多 run 实验：批量推理 → 评测 → 报告 → 对比表 | 加实验维度 → `_apply_run_overrides`；改对比表 → `_write_comparison` |
| `cli.py` | ~250 | 命令行入口（process/batch/evaluate/experiment/init-dataset/info） | 加子命令 → `_build_parser` 与 `handlers` |
| `webapp.py` | 694 | 纯标准库 Web 服务：路由、任务队列、上传解析、复核保存、导出、状态、配置、连通性测试 | 加 API → `do_GET`/`do_POST` 路由；改任务实现 → `_job_bom/_job_doc/_job_compare/_job_inspect`；改状态字段 → `_status_payload` |
| `providers/base.py` | 59 | `VisionProvider` 抽象接口 + 异常类型（`ProviderError`/`ProviderTimeout`/`ProviderConfigError`） | **接入新模型从这里继承** |
| `providers/mock.py` | 129 | 离线 Mock：按提示词 TASK 标记返回样例数据（含故意注入的错误） | 改演示数据 → `_MOCK_COMPONENTS`、`_MOCK_TITLEBLOCK`、`_MOCK_DOC_EXTRACT`、`_MOCK_DIMENSIONS` |
| `providers/openai_compat.py` | 170 | OpenAI 兼容 API 实现（多图 base64、重试、超时、密钥来源优先级） | **API 接入参数**：`_init_from_cfg`；请求体构造 → `analyze`；重试策略 → `_post_chat`；错误处理 → `_post_once` |
| `providers/__init__.py` | 26 | Provider 注册表与工厂 | 新 Provider 登记到 `PROVIDERS` |
| `evaluation/dataset.py` | 52 | 数据集发现、标注加载 | 改数据集目录约定 → `discover_documents` |
| `evaluation/metrics.py` | 281 | 配对、字段比对、单文档评测、语料汇总、Markdown 报告 | 改配对策略 → `match_components`；改评测字段 → `EVAL_FIELDS`；改指标口径 → `evaluate_document`/`evaluate_corpus`；改报告样式 → `render_markdown_report` |

### 6.2 前端（`static/`，共 735 行，无构建步骤）

| 文件 | 行数 | 职责 |
|---|---|---|
| `index.html` | 193 | 六个视图的 DOM 骨架（`#view-bom`/`doc`/`compare`/`inspect`/`review`/`settings`）+ 侧边栏导航（`data-view` 属性驱动） |
| `app.js` | 456 | 全部交互逻辑：导航切换、`api()` fetch 封装、`pollJob` 轮询、拖拽上传（`bindDrop`）、BOM 可编辑表格（`renderBomTable`）、要素分组表（`renderDocResult`）、变更高亮渲染（`renderCmpItems`）、问题清单（`renderIssues`）、设置页（`loadStatus`/`cfgPayload`/测试连接）、下载按钮 |
| `style.css` | 86 | 样式（侧边栏、卡片、表格、变更三色、问题严重度色标、进度条动画） |

前端约定：视图切换靠 `.view.active` 类；新增页面 = 在 `index.html` 加 `<section id="view-xxx" class="view">` + 导航加 `<a data-view="xxx">` + `app.js` 导航监听里按需加载数据。

### 6.3 脚本与配置

| 文件 | 作用 |
|---|---|
| `scripts/make_demo_data.py` | 生成演示数据：两页发动机明细表 PDF（中英混排字体处理）+ 图片样本 + 对应人工标注 |
| `scripts/run_experiment.py` | 实验运行薄封装（等价 `python -m engine_bom.cli experiment`） |
| `config.yaml` | 默认配置示例（内含 API 接入注释） |
| `configs/experiment_demo.yaml` | 实验规格示例（两个 mock run + 注释掉的真实模型 run） |
| `requirements.txt` | 依赖：pymupdf / pillow / pyyaml（openpyxl、opencv 可选） |

### 6.4 测试（`tests/`，运行完整测试套件）

| 文件 | 覆盖内容 |
|---|---|
| `test_schema.py` | 类型强制（"4件"→4）、字段别名、去重策略（keep_max/sum）、重复件号校验、归一化 |
| `test_parsing.py` | 代码块 JSON、尾逗号修复、裸数组、垃圾输出、空输出 |
| `test_pipeline.py` | Mock 端到端（per_page/whole_doc）、导出产物、trace 落盘、文件不存在 |
| `test_metrics.py` | 件号归一化匹配、名称模糊匹配、P/R/F1、字段准确率、完全正确率、空语料、报告渲染 |
| `test_new_modules.py` | 变更识别（修改/删除/忽略格式）、总结与 ECN、分类；文档解析与行扁平化；标题栏/明细栏/尺寸/引出序号规则；标题栏解析容错 |

### 6.5 数据目录（`data/`，运行时产物，可随时清理）

| 路径 | 内容 | 是否可删 |
|---|---|---|
| `data/raw/` | 输入文档（演示 PDF/PNG + 用户提供的 `ae1000_assembly.png`） | 演示件可删 |
| `data/annotations/` | 人工标注（与输出同构） | 演示件可删 |
| `data/predictions/` | 单文件识别的 JSON/CSV + `traces/` 原始输出留档 | 可删（会重建） |
| `data/predictions/<实验>/<run>/` | 实验模式的分 run 输出 | 可删 |
| `data/reports/` | 评测报告 `.report.md` / `.report.json` / `comparison.md` | 可删 |
| `data/reviewed/` | 人工复核后的最终数据（模型迭代数据源） | **建议保留** |
| `data/review_log.json` | 人工修正记录（动作/对象/操作人/备注/时间） | **建议保留** |
| `data/change_history.json` | 变更历史（ECN 生成记录） | **建议保留** |
| `data/web_settings.json` | 网页保存的模型配置（含 API Key，**注意限权**） | 可删（回到环境变量/默认） |
| `data/web_jobs/` | Web 任务产物（上传件 + result.json） | 可删 |
| `data/knowledge/engine_rules.txt` | 企业命名/分类规则（开启后注入提示词） | 可替换为企业真实规范 |

---

## 7. 数据格式规范

### 7.1 BOM 输出/标注格式（同一结构，二者可互为参照）

```json
{
  "document_id": "demo_engine_bom",
  "source_file": "demo_engine_bom.pdf",
  "generated_at": "2026-09-16T00:07:14",
  "model_info": {
    "provider": "openai_compat",
    "model": "qwen3.8-max",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key_source": "config",
    "prompt_version": "v1",
    "recognition_mode": "per_page",
    "knowledge_base": {"kind": "NoopKnowledgeBase"},
    "pages": 2
  },
  "components": [
    {
      "item_no": 1,
      "part_number": "ENG-BLK-001",
      "name_zh": "气缸体",
      "name_en": "Cylinder Block",
      "category": "机体与气缸盖",
      "specification": "直列四缸",
      "material": "铸铁 HT250",
      "quantity": 1,
      "unit": "件",
      "position": "发动机主体",
      "supplier": "",
      "remark": "",
      "source_page": 1,
      "confidence": 0.97
    }
  ],
  "summary": {"total_components": 12, "total_quantity": 43},
  "validation_issues": ["..."],
  "process_time_s": 167.4
}
```

字段说明：
- `item_no` 序号（系统输出会重新编号为连续 1..N）
- `quantity` 整数；无法确定时为 `null`（解析阶段支持 "4件"/"4.0"/"4组、每组3件"→12 之类容错）
- `category` 发动机功能系统分类，提示词中给定候选集：机体与气缸盖 / 曲柄连杆机构 / 配气机构 / 燃油供给系统 / 进排气系统 / 增压系统 / 冷却系统 / 润滑系统 / 点火系统 / 起动系统 / 电控系统 / 密封件与标准件 / 其他
- `confidence` 0~1，可配合 `recognition.min_confidence` 过滤
- 标注文件**最少只需 `components` 数组**，其余字段可省略

**标注规范要点（重要）**：人工标注只应填写**文档中真实可见**的字段。系统评测只统计"标注提供了的字段"，若标注包含文档中不存在的信息（例如纯中文表格里标注了英文名），该字段会被系统性判错——这已在演示数据中得到验证（见 §12.6）。

### 7.2 数据集目录约定

```
data/raw/<doc_id>.pdf|.png|.jpg|...      输入文档（doc_id = 文件名去扩展名）
data/annotations/<doc_id>.json           同名人工标注
```

### 7.3 实验规格格式（`configs/*.yaml`）

```yaml
experiment: demo_mock            # 实验名 → 决定输出子目录
dataset:
  raw_dir: data/raw
  annotation_dir: data/annotations
output:
  pred_root: data/predictions    # → <pred_root>/<experiment>/<run_name>/
  report_root: data/reports      # → <report_root>/<experiment>/<run>.report.md
runs:                            # 每个 run = 一次"配置组合 + 全量推理 + 评测"
  - name: mock_per_page
    provider: mock
    mode: per_page               # 覆盖 recognition.mode
    prompt_version: v1           # 覆盖 recognition.prompt_version
  - name: qwen_max
    provider: openai_compat
    provider_options:            # 合并进 provider.openai_compat
      base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
      model: qwen3.8-max
```

**run 的设计原则：每次只变一个因素**（模型 / 提示词版本 / 识别模式 / 知识库开关），这样指标差异才能归因。

### 7.4 关键配置项（`config.yaml` / `DEFAULT_CONFIG`）

| 配置 | 默认 | 说明 |
|---|---|---|
| `provider.name` | `mock` | `mock` / `openai_compat` |
| `provider.openai_compat.base_url` / `model` / `api_key` | 空 | 密钥优先级：配置 > 环境变量 `VISION_API_KEY` |
| `provider.openai_compat.timeout` | 300 | 单次请求读超时（秒），高密度图纸需要 |
| `provider.openai_compat.retries` | 2 | 超时自动重试次数（指数退避 10s/20s） |
| `provider.openai_compat.temperature` | 0.0 | 提取任务建议保持 0 |
| `recognition.mode` | `per_page` | `per_page`（逐页识别后合并，稳） / `whole_doc`（整档一次，省调用） |
| `recognition.prompt_version` | `v1` | 提示词版本 |
| `recognition.duplicate_quantity_policy` | `keep_max` | 跨页重复数量：`keep_max` / `sum` / `keep_first` |
| `recognition.min_confidence` | 0.0 | 低于阈值过滤 |
| `ingestion.dpi` | 200 | PDF 渲染 DPI（扫描件建议 300） |
| `ingestion.preprocess.*` | 关闭 | `enabled`/`deskew`/`denoise`/`binarize`/`contrast` |
| `knowledge.enabled` / `path` / `top_k` | 关闭 | 企业规则注入 |
| `validation.strict` | false | true 时校验失败直接抛错 |
| `output.dir` / `formats` | `data/predictions` / `[json, csv]` | 导出位置与格式 |

---

## 8. 评测指标体系与口径定义

代码位置：`engine_bom/evaluation/metrics.py`。报告样式对齐论文 Table 2（均值 ± 标准差 + 处理时长）。

### 8.1 元器件配对规则（`match_components`）

1. **件号精确匹配**：`normalize_part_number`（全角转半角、去空白与 `-_/\.,:;()（）[]【】`、大写）后相等即配对
2. **名称模糊匹配**：剩余项按 `difflib.SequenceMatcher` 计算 `name_zh/name_en` 两两组合的最大相似度，贪心配对，阈值默认 **0.75**
3. 每项只配对一次（一对一）

### 8.2 检测指标

- `precision = 配对成功数 / 预测总数`
- `recall = 配对成功数 / 标注总数`
- `F1 = 2PR/(P+R)`
- **宏平均**：各文档指标的平均值（报告均值±标准差）
- **微平均**：全部元器件池化后计算（报告总数）

### 8.3 字段级指标（`EVAL_FIELDS`）

字段集：`part_number, name_zh, name_en, category, specification, material, quantity, unit, position, supplier`

- **分母口径**：只统计**标注提供了该字段**（非空）的已配对元器件
- **相等判定**：`quantity` 按整数相等；`part_number` 按归一化后相等；其余按 `normalize_text`（全角转半角、去空白标点、小写）后相等
- `field_accuracy`（单文档）= 所有字段正确数之和 / 所有字段统计数之和

### 8.4 其他指标

- `exact_bom`：预测与标注**一一对应且全部字段一致**（文档级布尔，语料级取平均 = 完全正确率）
- `avg_process_time_s`：平均处理时长
- 报告附：漏检元器件清单（`missed_gt`）、误报清单（`false_positives`）、逐字段错误明细（预测值 vs 标注值）

### 8.5 评测产物

- `<run>.report.md`：人读（含指标表、字段表、分文档明细、漏检/误报/字段错误清单）
- `<run>.report.json`：机读（同样的完整数据，便于画图与统计分析）
- `comparison.md`：跨 run 对比表（P / R / F1 / 字段准确率 / 完全正确率 / 平均耗时）

---

## 9. Web 界面与 REST API

### 9.1 启动与访问

```bash
python -X utf8 -m engine_bom.webapp                     # 默认 http://127.0.0.1:8787
python -X utf8 -m engine_bom.webapp --host 0.0.0.0      # 内网共享（同事可访问）
python -X utf8 -m engine_bom.webapp --port 9000         # 换端口
```

实现：`http.server.ThreadingHTTPServer` + 纯标准库（**零第三方依赖**）；上传解析用 `cgi.FieldStorage`；任务在守护线程执行；结果落 `data/web_jobs/<job_id>/`。

### 9.2 六个功能页

| 视图 | 功能 | 关键交互 |
|---|---|---|
| 图纸 BOM 识别 | 上传图纸 → 标题栏 + 可编辑 BOM 表 + 规则检查问题清单 | 模型下拉（默认配置/Mock/视觉模型API）、预处理勾选框、逐格编辑、确认复核、导出 JSON/CSV/Excel |
| 文档要素提取 | 上传 docx/pdf/txt/图片 → 四类要素分组表 | 同上，导出 JSON/Excel |
| 文件变更对比 | 上传两版 → 变更概览 + 三色高亮清单 | 忽略格式开关、按类型筛选、生成 ECN 草稿 |
| 图纸规则检查 | 上传图纸 → 标题栏 + 尺寸表 + 问题清单 | 问题按严重度色标显示，含整改建议 |
| 复核与历史 | 人工修正记录表 + 变更历史表 | 自动加载 |
| 系统设置 | Provider / Base URL / 模型名 / API Key + 测试连接 | 保存后全局生效；测试连接用输入框当前值发一次极短真实请求 |

### 9.3 API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/jobs/bom` | 上传图纸（字段 `file`，可选 `options` JSON：`provider`、`preprocess`）→ 返回 `{job_id}` |
| POST | `/api/jobs/doc` | 上传文档（`file`，可选 `provider`） |
| POST | `/api/jobs/compare` | 上传两版（`before`、`after`，`ignore_format`） |
| POST | `/api/jobs/inspect` | 上传图纸（`file`，可选 `provider`） |
| GET | `/api/jobs` | 任务列表（最近 100） |
| GET | `/api/jobs/<id>` | `{status: running\|done\|failed, result, error}` |
| POST | `/api/bom/save` | `{document_id, components, editor, comment}` → 写 `data/reviewed/` + 修正记录 |
| POST | `/api/doc/save` | `{file_name, extraction, comment}` |
| GET | `/api/export/bom/<id>?fmt=json\|csv\|xlsx` | BOM 下载（CSV 带 BOM 头，Excel 直开不乱码） |
| GET | `/api/export/doc/<id>?fmt=json\|xlsx` | 要素提取下载 |
| GET | `/api/compare/<id>/ecn.md` | ECN 变更单草稿（下载同时写入变更历史） |
| GET | `/api/history` | 变更历史（支持 `file_name`、`category` 过滤） |
| GET | `/api/reviewlog` | 人工修正记录 |
| GET | `/api/status` | 模型/密钥来源/预处理可用性（不返回密钥本身） |
| POST | `/api/config` | 保存 Provider / base_url / model / api_key；`{"clear_api_key": true}` 清除 |
| POST | `/api/test-connection` | 用请求中的（未保存）配置发一次 `max_tokens=32` 请求验证连通性 |

任务结果 JSON 结构（BOM 任务）：`{document_id, bom, title_block, missing_required, dimensions, balloons, issues, outputs, model_info}`。

---

## 10. 运行环境与命令速查

### 10.1 环境事实（重要，不要假设可联网安装）

| 项 | 值 |
|---|---|
| Python | 3.8.5，`C:\Users\v10\AppData\Local\Programs\Python\Python38\python.exe`（代码需兼容 3.8 语法） |
| 已安装可用 | PyMuPDF 1.24.11、Pillow 10.4.0、PyYAML 6.0.3、openpyxl 3.1.5、numpy 1.24.4、opencv-python 4.13.0 |
| **未安装且装不上** | flask、fastapi、uvicorn、python-docx、ezdxf —— **pip 走代理失败（ProxyError），完全无法联网安装** |
| 应对方式 | Web 服务用标准库自写；docx 用 `zipfile`+`xml.etree` 解析；Cad 解析留待内网部署时接入 |
| Shell | Windows + PowerShell（用户日常）；本机 Git Bash 亦可 |
| 中文控制台 | 命令统一加 `-X utf8`；`cli.py` 内已对 stdout/stderr 做 UTF-8 重配置 |

### 10.2 常用命令

```bash
# Web 服务
python -X utf8 -m engine_bom.webapp [--host 0.0.0.0] [--port 8787]

# 单文件识别（默认 Mock 离线跑通）
python -X utf8 -m engine_bom.cli process data/raw/demo_engine_bom.pdf [--provider openai_compat] [-o 输出前缀] [--formats json,csv,xlsx] [--mode per_page|whole_doc] [--prompt-version v1]

# 批量识别目录
python -X utf8 -m engine_bom.cli batch data/raw [--out 输出目录]

# 评测（预测目录 vs 标注目录）
python -X utf8 -m engine_bom.cli evaluate data/predictions data/annotations [-o 报告前缀]

# 多 run 实验（推理+评测+对比）
python -X utf8 -m engine_bom.cli experiment configs/experiment_demo.yaml

# 初始化数据集目录与示例
python -X utf8 -m engine_bom.cli init-dataset

# 查看配置/依赖/密钥状态
python -X utf8 -m engine_bom.cli info

# 生成演示数据（PDF + 图片 + 标注）
python -X utf8 scripts/make_demo_data.py

# 单元测试
python -X utf8 -m unittest discover -s tests -v
```

> CLI 的覆盖参数（`--provider/--mode/--prompt-version/--formats/-c`）**挂在子命令上**，写法是 `engine-bom process 文件 --provider xxx`。

### 10.3 API 接入方式（两条路径，已在代码中实现）

**路径 A：网页设置（推荐日常使用）**——「系统设置」页填 Provider / Base URL / 模型名 / API Key → 点「测试连接」验证 → 「保存设置」。配置写入 `data/web_settings.json`，优先级高于环境变量。

**路径 B：环境变量（适合命令行/批量/CI）**

```powershell
$env:VISION_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:VISION_MODEL="qwen3.8-max"
$env:VISION_API_KEY="sk-..."
```

**已验证可用的真实端点**：阿里百炼 OpenAI 兼容模式（`https://dashscope.aliyuncs.com/compatible-mode/v1` + `qwen3.8-max`）。
**内网部署**：`vllm serve Qwen/Qwen2.5-VL-72B-Instruct --port 8000` 后把 Base URL 指向 `http://内网IP:8000/v1`。

**接入非 OpenAI 兼容接口**：新建 `engine_bom/providers/<name>.py` 继承 `VisionProvider`，实现 `analyze(images, prompt) -> ProviderResponse`，在 `providers/__init__.py::PROVIDERS` 登记。

---

## 11. 关键设计决策与理由

| 决策 | 理由 | 影响/代价 |
|---|---|---|
| 视觉模型走 Provider 抽象而非直接写死调用 | 需求 C-01/C-02 要求最终必须内网私有化；同时开发期需要无网络也能验证流程 | 换模型/换端点零业务代码改动；代价是多一层接口 |
| 内置 Mock Provider（确定性数据 + **故意注入错误**） | 无数据集、无 API 阶段必须能验证整条链路与评测口径是否正确 | Mock 故意漏检"水泵"、错识"活塞"数量，使评测指标呈现非平凡值（P=1.0/R=0.9167），证明评测能反映差距 |
| 保留 `prompt_version` 并写入输出 meta | 提示词优化是本项目主要提升手段，必须可复现、可归因 | 每次输出记录版本，实验报告自动区分 |
| 跨页重复元器件数量默认 `keep_max` 而非累加 | 真实图纸中"明细表页 + 装配图页引用同一批零件"极常见，累加会翻倍计数（演示数据中曾观察到气缸体 x2、活塞 x12 的错误结果） | 拆表场景可切回 `sum`；三种策略都可配置 |
| 逐页识别（per_page）为默认模式 | 单次请求图像更少、失败影响面小、可定位到页；整档模式作为省调用选项保留 | 多页文档调用次数增加；`whole_doc` 可切换 |
| 原始模型输出全部留档到 `traces/*.trace.json` | 对应论文的 human-in-the-loop 审计要求；也是"模型没识别对 vs 解析出错"的唯一可靠区分手段 | 磁盘占用小，收益大 |
| Web 服务用标准库自写 | pip 完全不可用（代理失败）且内网部署希望零依赖 | 无框架生态支持，需自行处理路由/上传/线程；换来部署零负担 |
| 任务异步 + 前端轮询 | 高密度图纸单页推理需 40~170 秒，同步请求会超时且界面卡死 | 前端 1.5s 轮询，单任务异常不影响服务 |
| 评测只统计"标注提供了的字段" | 不同文档包含的字段不同，强行要求全字段一致会掩盖真实差距 | 必须在标注规范中强调"只标文档中真实可见的信息" |
| CSV 使用 `utf-8-sig` | Excel 直接双击不乱码（中文环境刚需） | 非 Excel 工具读取时需容忍 BOM 头 |
| 变更对比"宁可多报不可漏报" | 需求表明确要求（漏报零容忍） | 分类用规则打分，未达阈值一律归"其他"而不丢弃 |

---

## 12. 已踩过的坑与已修复的缺陷（勿重犯）

> 以下问题都已修复并有测试覆盖或验证记录，**新改动时请注意不要回退**。

### 12.1 跨页重复元器件数量被累加翻倍
- **现象**：演示 PDF 两页（明细表页 + 装配图页）识别后，气缸体数量变成 x2、活塞 x12。
- **原因**：去重合并时无条件累加数量。
- **修复**：`merge_components` 增加 `quantity_policy`，默认 `keep_max`，可配置 `sum`/`keep_first`；`recognition.duplicate_quantity_policy` 暴露给用户。

### 12.2 Python 3.8 下 `socket.timeout` 不是 `TimeoutError` 的子类
- **现象**：API 超时抛出裸 traceback（`socket.timeout: The read operation timed out`），而不是友好的失败提示。
- **原因**：`except (urllib.error.URLError, TimeoutError)` 未覆盖 `socket.timeout`（3.10+ 才统一）。
- **修复**：`openai_compat._post_once` 单独捕获 `socket.timeout` → 抛 `ProviderTimeout`；`_post_chat` 实现重试（默认 2 次，退避 10s/20s）。

### 12.3 API Key 末尾换行导致 `Invalid header value`
- **现象**：`Invalid header value b'Bearer sk-...\n'`。
- **原因**：PowerShell 里设置环境变量时引号换行，值里混入 `\n`。
- **修复**：`openai_compat` 对 `api_key`、`base_url`、`model` 统一 `.strip()`；`base_url` 额外 `rstrip("/")`。

### 12.4 导出文件被 Excel 占用导致整个任务崩溃
- **现象**：`PermissionError: [Errno 13] Permission denied: ...csv`（用户开着 Excel）。
- **修复**：`export.py::export_bom` 捕获 `PermissionError` → 自动改用带时间戳备用文件名并提示；单格式失败不影响其他格式；`OSError` 兜底。

### 12.5 CLI 参数只能写在子命令之前
- **现象**：`process 文件 --provider openai_compat` 报 `unrecognized arguments`。
- **原因**：`--provider` 定义在主 parser 上（argparse 要求写在子命令前）。
- **修复**：把公共覆盖参数放入 `common` parent parser 并挂到每个子命令上（写法统一为"跟在子命令后"）。

### 12.6 演示标注包含文档中不存在的字段，导致指标被低估
- **现象**：真实模型识别结果 P=R=F1=1.0（12/12 全对），但字段准确率只有 0.7736。
- **原因**：演示 PDF 表格只有 8 列（无英文名、无装配位置列），而生成的标注里写了 `name_en` 与 `position`；模型看不到自然提取不出（提示词还明确要求"不要自行翻译编造"），却被判错。
- **结论（写进标注规范）**：标注只填文档中真实可见的字段；系统只统计标注提供的字段。

### 12.7 变更对比的段落配对错位（真 bug，被测试抓到）
- **现象**：`align_and_diff` 把"转速范围 0~10000→12000"识别成与"新增表面处理要求"配对。
- **原因**：用段落序号 `j` 去索引 `added` **列表**（列表下标 ≠ 段落序号，当 indel 发生时错位）。
- **修复**：建立 `added_text = {j: text}` 映射后按段落序号取值；`test_new_modules.py::test_diff_modified` 覆盖。

### 12.8 `elements_to_rows` 运算符优先级
- **现象**：`AttributeError: 'tuple' object has no attribute 'strip'`（导出 Excel 时）。
- **原因**：`"%s %s" % (a, b).strip()` 中 `.strip()` 作用于元组。
- **修复**：先格式化再 `strip`，加括号。

### 12.9 生成中文 PDF 时西文被渲染成全角（演示数据）
- **现象**：用 PyMuPDF 的 `china-s` 字体插入所有文本，导致图号被提取为 `E N G - W T P - 0 1 2`（字母间被插入空格），既难看也不像真实图纸。
- **修复**：`make_demo_data.py::insert_mixed` 按字符类型分段——中文用 `china-s`，西文/数字用 `helv`，并按字体实际宽度推进 x 坐标。

### 12.10 git bash 里 curl 传 JSON 中文会破坏请求体
- **现象**：`curl -d '{"...":"活塞"}'` 发出的 body 被 shell 转义破坏，服务端收到空 body（表现为"保存了 unnamed/0 条"）。
- **结论**：验证 API 时优先用 Python `urllib` 客户端或浏览器；不要把 curl 的异常结果误判为服务端 bug。

### 12.11 浏览器标签页 claim + reload 后点击超时（工具环境问题，非页面缺陷）
- **现象**：IAB 中 `claimTab` 后再 `reload`，随后 `locator.click()` 全部超时（元素可见、坐标在视口内）。
- **结论**：这是该浏览器会话的指针路由问题；新建标签页 `goto` 后点击正常（实测导航切换与视图渲染均通过）。**不要因此改动前端代码。**

### 12.12 pip 完全不可用
- **现象**：`pip install flask` → `ProxyError('Cannot connect to proxy')`，绕过代理与换清华镜像同样失败。
- **结论**：本机无法新增第三方依赖。**要加功能先看标准库与已装库（§10.1）能否实现**；确实需要新依赖时，让用户在有网环境安装或走内网源。

---

## 13. 对话历史时间线

按阶段记录用户诉求与产出，便于理解"为什么是现在这个样子"。

| 阶段 | 用户诉求 | 主要产出 |
|---|---|---|
| 1. 起点 | 想做"发动机元器件识别系统"（PDF/图片 → BOM），**暂无数据集**，要求先搭系统，数据集到位即可实验，**视觉模型 API 留出接入位置**；附参考论文 PDF | 读完论文（LLM+RAG 的 BOM 数字化闭环）；搭建完整项目骨架：schema/ingestion/prompts/parsing/pipeline/export/providers(Mock+OpenAI兼容模板)/knowledge/evaluation/experiment/cli；生成演示数据；30 个单测；README |
| 2. 教程化 | "我该怎么使用" / "什么是 run" / "怎么测试图片" | 分阶段使用指南；解释 run = 一次"配置组合+全量推理+评测"；给出 process/batch/evaluate/experiment 命令范式 |
| 3. 接入真实模型 | 询问能否接 Qwen3.8-Max | 确认其为多模态旗舰、走百炼 OpenAI 兼容端点；给出环境变量与 PowerShell 写法 |
| 4. 联调排错 | 连续遇到：`--provider` 参数位置错误、Key 尾换行 `Invalid header value`、`socket.timeout` 裸 traceback、Excel 占用导致 `PermissionError` | 逐项修复（见 §12.2/12.3/12.4/12.5）并复测 |
| 5. 真实识别验证 | 首次用 Qwen3.8-Max 识别演示图；随后提供自有的**涡扇发动机总装图**询问"放到 raw 里能识别对吗" | 实测：演示图 12/12 全对（41s）；AE-1000 总装图提取 18 个元器件、总数量 82、167s；并指出 `name_en/position` 低分源于标注与文档不一致（§12.6） |
| 6. 需求规格表导入 | 提供 `AI工艺项目需求规格表.xlsx`，要求：**做符合直觉的前端**，并**把需求表里还没做的后端需求补上** | 读完三张表；新增 5 个后端模块（预处理/标题栏/规则检查/文档要素提取/变更对比）；实现纯标准库 Web 服务与六页前端；当时建立 46 个单测，后续持续增加 |
| 7. 前端接入位 | "前端没有我可以接入 API 的地方" | 设置页补齐 **API Key 输入** + **测试连接**按钮 + 清除 Key；Provider 支持从配置读 Key（优先级高于环境变量）；用假 Key 实测返回 DashScope 官方 401，证明链路打通 |
| 8. 本文件 | 要求导出**极其详细的 README 文档**，作为资料库导入，让其他 AI 理解目标、需求、已完成内容的位置，避免重复造轮子 | 本文件 |

---

## 14. 待办事项与明确不要重复做的事

### 14.1 明确「已经做完，不要重做」的清单

- ❌ 不要再实现一遍 BOM 识别流水线（`pipeline.py` 已有：逐页/整档、跨页合并、校验、导出、trace）
- ❌ 不要再写 JSON 容错解析（`parsing.py` 已覆盖代码块/尾逗号/智能引号/裸数组）
- ❌ 不要再写 Provider 抽象与 OpenAI 兼容调用（`providers/` 已含重试、超时、多图 base64、密钥来源优先级）
- ❌ 不要再写评测指标（`evaluation/metrics.py` 已含配对/字段/宏微平均/报告渲染）
- ❌ 不要再写实验运行器（`experiment.py` 已含多 run 合并、评测、对比表）
- ❌ 不要再选 Flask/FastAPI 搭 Web（标准库实现已完成且满足零依赖约束；且本机装不上）
- ❌ 不要再写变更对比的段落对齐（`changedetect.py` 已有对齐+分类+ECN+历史）
- ❌ 不要再写标题栏/规则检查/文档要素提取（`titleblock.py`/`inspect_rules.py`/`docextract.py`）

### 14.2 建议的下一步（按需求表优先级排序）

| 优先级 | 任务 | 建议入口 | 依赖/前提 |
|---|---|---|---|
| P1 | **装配层级关系识别（REQ-01-4）** | 扩充 `schema.py` 字段（如 `parent_item`）+ `prompts.py` 提示词要求输出父件 + `merge_components` 后建树 | 需求表建议初期只做一级装配、人工确认；引出序号数据已可从 `titleblock.py` 获取 |
| P1 | **人工复核界面增强（REQ-02-6）** | `static/app.js` + `webapp.py`：原文位置高亮（按 `source_page` 显示页面缩略图）、3 级复核权限、驳回流程 | 需要页面缩略图接口 |
| P1 | **变更类型分类升级为 LLM** | `changedetect.py::classify_change` 替换为 provider 调用（文本即可） | 现规则版已可用，LLM 版可提升准确率 |
| P1 | **句向量语义对齐**（替代 difflib，处理段落重排更稳） | `changedetect.py::align_and_diff` | 需内网 embedding 模型服务 |
| P2 | **变更影响范围分析（REQ-03-4）** | 新增模块 + `knowledge.py` 扩展为文档关联索引 | 需求表注明需企业有较完整的文档关联关系 |
| P2 | **ERR-02/03/04/05/09 等 VLM 推理类检查** | `inspect_rules.py` 增加规则 + `titleblock.py` 增加符号/公差抽取提示词 | 需 CV 符号识别与标注数据积累（需求表归为第二阶段） |
| P2 | **DWG/DXF 原生解析** | `ingestion.py` 的 CAD 分支 | 需内网安装 ODA File Converter 或 ezdxf（本机装不上） |
| P2 | **10 折交叉验证** | `experiment.py` 增加折数切分与均值±标准差汇总 | 论文用 10 折报告；当前为全量单次评测 |
| P2 | **ERP/PLM 字段映射配置** | `export.py` 增加模板映射层 | 需客户提供导入模板 |
| P3 | **图片标注重定位/框选辅助**（论文 Fig.11 的框选引导） | Web 端画框 + `pipeline` 支持 ROI 传入 | 需前端画布交互 |

### 14.3 内网交付时需要做的事（代码之外）

1. 内网 GPU 服务器部署 vLLM（或 LMDeploy）并加载开源多模态模型
2. 把 Base URL / 模型名填入网页「系统设置」，API Key 若内网无鉴权可留空
3. 将 `data/knowledge/engine_rules.txt` 替换为企业真实命名/分类规范，并开启 `knowledge.enabled`
4. 交付 `data/reviewed/` 与 `review_log.json` 的累积机制给业务专家做标注（预测结果可作预标注）
5. 确认客户 ERP/PLM 的 BOM 导入模板，映射到 `export.py` 的导出列

---

## 15. 验证基线（当前正确状态）

任何改动后，可用以下基线判断是否破坏了既有功能。

### 15.1 单元测试

```bash
python -X utf8 -m unittest discover -s tests
# 期望：全部测试执行完成并显示 OK
```

### 15.2 离线端到端（Mock）

```bash
python -X utf8 scripts/make_demo_data.py     # 重新生成演示数据
python -X utf8 -m engine_bom.cli process data/raw/demo_engine_bom.pdf
# 期望：11 个元器件（故意漏检"水泵"）、总数量 40、活塞 x6（故意错识）
python -X utf8 -m engine_bom.cli experiment configs/experiment_demo.yaml
# 期望：data/reports/demo_mock/{mock_per_page,mock_whole_doc}.report.md + comparison.md
```

演示基线指标（`mock_per_page`，2 个文档）：

| 指标 | 值 |
|---|---|
| Precision | 1.0000 |
| Recall | 0.9167 |
| F1 | 0.9565 |
| 字段准确率 | 0.9897 |
| 完全正确率 | 0 |
| 数量字段准确率 | 20/22（90.91%） |
| 漏检 | demo_engine_bom / demo_engine_parts_page 均漏"水泵" |
| 平均处理时长 | 约 0.17 s |

### 15.3 真实模型端到端（需配置 API）

| 输入 | 结果 |
|---|---|
| `data/raw/demo_engine_parts_page.png`（演示明细表图） | 12 个元器件，与标注 **完全一致**：P=R=F1=1.0，41.1 s |
| `data/raw/ae1000_assembly.png`（用户提供的涡扇发动机总装图） | 18 个元器件、总数量 82，与图纸明细表逐项一致（含 GB/T 5782 螺栓 x8、GB/T 97.1 垫圈 x12），167.4 s |

### 15.4 Web 端验证要点

- `curl http://127.0.0.1:8787/api/status` 返回版本/Provider/模型/密钥来源/预处理可用性
- 页面零 JS 报错；六个导航项切换正常；设置页状态回填正确
- 四个任务端点（bom/doc/compare/inspect）均能跑通并返回结构化结果
- 「测试连接」用假 Key 应显示 API 返回的真实错误（如 DashScope `HTTP 401 Incorrect API key provided`）

---

## 16. 术语表

| 术语 | 含义 |
|---|---|
| BOM | Bill of Materials，物料清单。本系统的核心输出 |
| 明细栏 / 明细表 | 图纸上列出全部零部件的表格（序号/图号/名称/数量/材料/备注） |
| 标题栏 | 图纸右下角的工程信息栏（图名/图号/材料/比例/重量/设计/审核/批准/日期） |
| 引出序号 / 球标 | 装配图上指向零件的圆圈编号，与明细栏序号对应 |
| Provider | 视觉模型的抽象接口实现，系统通过它调用模型（Mock / openai_compat 可互换） |
| run | 实验中的一次"配置组合 + 全量推理 + 评测"，是实验对比的最小单位 |
| trace | 每次识别的原始模型输出留档（`data/predictions/traces/*.trace.json`） |
| 宏平均 / 微平均 | 宏=各文档指标的平均；微=全部元器件池化后统一计算 |
| x-EDBOM | 论文中的"可执行电子数字 BOM"，作为 PLM/ERP/MES 的统一数据源 |
| RAG | Retrieval-Augmented Generation，检索增强生成。本系统以 `knowledge.py` 提供简化实现 |
| VLM | Vision-Language Model，视觉语言模型（如 Qwen2.5-VL、Qwen3.8-Max） |
| ECN / ECR | Engineering Change Notice / Request，工程变更单/申请单 |
| P0/P1/P2 | 需求优先级：必须做 / 应该做 / 可延后 |

---

## 附：一句话交接提示

> 这是一个**已经能跑通全流程**的"图纸/文档 → BOM"系统（Mock 可离线演示，真实模型已用 Qwen3.8-Max 验证通过），
> 需求来自用户方的《AI工艺项目需求规格表》18 条子功能 + 10 类图纸错误检测，其中 **REQ-01/02 基本完成、REQ-03 完成 5/6、错误检测完成 P0 中 3 项**；
> 代码按 `engine_bom/`（后端）、`static/`（前端）、`tests/`（测试）、`data/`（数据与产物）组织，每个文件的职责与修改点见 §6；
> 改动前请先跑 `python -X utf8 -m unittest discover -s tests`（应全部通过），并阅读 §11 设计理由与 §12 已修复缺陷，避免重复实现与回退修复。
