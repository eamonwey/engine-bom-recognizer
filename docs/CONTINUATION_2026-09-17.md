# 2026-09-17 续建记录与使用说明

工作区：`C:\Users\v10\Documents\ChatGPT\工艺\engine-bom-recognizer`。从原项目复制复用，原项目未改动。

## 输入资料与落实方式

- 需求表三张表：18项功能、10类审图需求。提取文本在 `requirements-extracted.txt`。
- 交接文档：保留在 `PROJECT_HANDOFF.md`。原来的流水线、解析器、Provider、RAG、导出、复核、文档提取和变更检测继续复用。
- 9月16日会话：最后一次“可以，请你开始”后的执行因502失败，未把历史建议当作已经实现的功能。
- Lin/Dang论文：重点采用解析、知识约束、校验、复核、受控写回。论文第12页的100个验证实例与第13页10折91%成绩属于电子制造企业物料主数据案例，不是本项目的机械装配图精度。论文没有提供可直接下载的本项目BOM标准答案。

本次指令允许测试阶段云API，故复用配置只对公开图纸做Qwen测试。本次任务未发送客户图纸到外部服务。

## 本次实现

1. `engine_bom/agent_loop.py`：抽取—解析—字段校验—带反馈重读闭环，默认最多3次，最多允许配置5次。BOM第2次增加对比度，第3次提供整页加四个局部图像。输出错误不会静默生成空BOM。合法空BOM仍允许，因为零件图可能没有明细表。
2. `pipeline.py`：逐页/整档接入loop。事件、原始回复、策略、页码和输入SHA256写入trace。耗尽时返回failed，另写 `.failed.json`。validated只表示格式/字段规则通过，不表示内容与设计意图已获证明。
3. `hybrid_inspection.py`：复用ERR-01/06/08规则，增加VLM对ERR-01..10的候选审查。VLM输出要求证据、合法页码和可选归一化bbox，校验失败触发重读；未通过的发现不当作有效问题。Mock不调用VLM。输出标明来源、复核状态和检查覆盖。
4. `corrections.py`：经过复核的文字修订生成新的PNG/PDF版本。PDF移除框内原文字再写入正确值；图片覆盖框选区域并写入正确值。记录复核人、修订内容、源/结果哈希与时间，支持检查预期源哈希。禁止覆盖源文件和已有输出。旋转PDF目前须先归一化方向。
5. 网页审图页面：原图分页预览、拖动框选、复核人、原文字、修正值、修订下载。保留高级批量JSON输入。新文件选择会清除旧的框选状态，避免用旧位置修订新文件。
6. `evaluation/strict.py`：精确件号匹配（GT无件号才用精确名称），漏检字段计入分母，同时保留旧版口径用于对照。CLI缺失预测会计入漏检；实验只使用本次ProcessResult，防止失败后读到上次结果。
7. Provider增加429/5xx/连接错误有限重试，401/403不重试；移除固定1600像素的二次压缩，长边上限可配置（默认2240）。
8. 旧规则修复：字符串负数不会被解析成正数；支持40Cr/42CrMo/GCr15/TC4等常见牌号模式；数量非正数报告；10mm与1cm等价不误报；明确不适用材料的装配图不因空材料报告错误。材料模式仍是候选筛查，不是国家标准合法性证明。

## 已落地公开数据和GT

| 数据 | 已落地内容 | 适用指标 | GT性质 |
|---|---|---|---|
| Mill Work Stop，Damon Donner / WA Open ProfTech / SBCTC | 1张装配图，9行BOM，27个可见字段 | 件号/描述/数量，P/R/F1，完整BOM | 推理前独立看图录入，尚未由客户工程师批准 |
| javvi51/edocr2 | 7张图、原始LabelMe标注、70处尺寸文字与框 | 尺寸文字与位置识别 | 作者提供的标签，尚未做客户专家审核 |

Mill Work Stop来源：[LibreTexts教材与明确CC BY 4.0署名](https://workforce.libretexts.org/Sandboxes/a072766d-16cb-4dbc-9dd2-2f3c784c59e6/Introduction_to_Machining/03%3A_Technical_Drawings/3.03%3A_3.3_Drawing_Views)。下载文件、URL和SHA256在 `data/public/libretexts/source.json`。全部9行标准答案在 `data/public/libretexts/annotations/mill_stop.json`。仅标源图能看到的字段，没有补造材料、英文翻译、层级或错误。

eDOCr2来源：[作者仓库](https://github.com/javvi51/edocr2)，固定提交 `f6f96517a531021ac946f6fc45063bdb77440085`，文件哈希在 `data/public/edocr2/dataset_manifest.json`，复现下载用 `python scripts/fetch_public_data.py`。仓库MIT许可已保存，训练前仍应核查原始图片权属。它没有完整BOM标注，不能用于声称BOM准确率。

其他公开候选（已查作者/托管页，尚未落地下载）：

- [TriView-CAD V1](https://data.mendeley.com/datasets/ynyjsmcjd6/1)，CC BY 4.0，三视图一致性二分类，有固定按零件划分的训练/验证/测试集。适合ERR-05专项；不提供BOM或批准后的修正几何。负例由不同零件视图组合生成，有真实设计错误的域差异。
- [ViewConsNet V1](https://data.mendeley.com/datasets/n5w53gtj2r/1)，工程图、标注与视图一致性相关代码，可进一步检查具体标注口径。
- [AutoXtractor](https://github.com/djdhairya/AutoXtractor)提供[约1.26GB数据包](https://huggingface.co/datasets/djDhairya/AutoXtractor/blob/main/data.zip)，作者说明用于BOM表格YOLO检测。不能把表格区域标签当作表内字段GT，尚未下载。

## 真实Qwen结果

| 本次调用 | P/R/F1 | 件号 | 数量 | 完整描述 | 全部标注字段 | 耗时 |
|---|---|---|---|---|---|---|
| 首次旧v1 | 1/1/1 | 9/9 | 9/9 | 5/9 | 23/27 = 85.19% | 59.135秒 |
| 改进v2 | 1/1/1 | 9/9 | 9/9 | 9/9 | 27/27 = 100% | 58.537秒 |

v1报告：`data/reports/public/v1/mill_stop.report.json`；v2：`data/reports/public/v2/mill_stop.report.json`；汇总：`data/reports/public/v2/corpus.report.md`。

标准答案没有送入识别模型。看到v1失败之后把描述保真要求补进通用v2提示词，因此该图现在是开发/回归样本，v2不是盲测。单张图不能推断总体精度，材料、层级和错误检出精度仍没有可报告的真实统计。

真实规则+VLM调用在 `data/reports/public/hybrid_inspection.json`，包含原始回复与证据框。模型输出校验通过；标题栏设计人/日期缺失是待复核候选，没有独立错误GT，不能报告误报率/召回率。原调用启动后规则又修复了装配图材料不适用判断，报告注明当前规则重验证，保留原视觉调用trace。

## 使用

现有Python环境：`C:\Users\v10\AppData\Local\Programs\Python\Python38\python.exe`，有PyYAML、PyMuPDF、Pillow、OpenCV。Codex文档运行时缺少PyYAML，不能直接拿它运行本项目YAML配置。

在项目目录执行：

```powershell
.\start.ps1
# 网页 http://127.0.0.1:8788/，避免与原项目8787冲突
python -X utf8 -m unittest discover -s tests
python -X utf8 scripts/benchmark_public.py --prompt-version v2
python -X utf8 -m engine_bom.cli evaluate data/reports/public/v2/predictions data/public/libretexts/annotations -o data/reports/public/v2/corpus
```

网页版使用原复制项目的API设置，测试公开图纸可以直接选择视觉API。命令行`process`若需要与网页版相同的持久设置，请显式传入配置或使用环境变量；CLI不会自动读取web_settings。密钥保存在本机原系统配置中，不要提交配置到仓库。

纠错命令：

```powershell
python -X utf8 -m engine_bom.cli correct 原图.pdf reviewed.json 修订版.pdf
```

`reviewed.json`示例（坐标需按实际原图框选，以下不能直接套用）：

```json
{"reviewer":"工程师姓名","patches":[{"approved":true,"source_page":1,"bbox":[0.1,0.1,0.2,0.15],"old_text":"41","new_text":"42","err_id":"ERR-01"}]}
```

新增API：`POST /api/jobs/correct`（file+reviewed multipart），`GET /api/corrections/<job_id>`下载修订，`GET /api/pages/<inspect_job_id>?page=1`读取原图。

## 端侧路径与尚未完成的部分

`configs/edge.json`固定127.0.0.1视觉服务、独立密钥变量和v2。网页启动：

```powershell
python -X utf8 -m engine_bom.webapp --port 8788 --config configs/edge.json
```

指定该配置时不加载web_settings云端配置。`scripts/serve_edge.sh`用于Linux/WSL2中已安装vLLM、已下载本地权重的模型服务，设置离线环境变量，不自动下载模型。候选小模型：[官方Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)，官方说明支持OpenAI兼容vLLM服务。仍需针对目标设备显存、视觉token和上下文测量，不能保证小模型达到云端精度。

本机只读检测显示RTX3060 Laptop、Intel Iris Xe、约15.7GB内存。Windows CIM的显存字段不可靠，尚未确认准确GPU显存，也未获知最终设备是否是这台机器。**本次未安装/部署端侧权重，未做端侧真实推理。**

当前修订是文字标注修订，不重建CAD几何，也不自动决定冲突尺寸哪个正确。多级装配树、完整GD&T/ISO配合标准库、真实复杂图纸几何纠错、3级复核权限和企业ERP模板仍沿用原交接中未完成状态，不能宣称18项需求已全部验收。

下一阶段验收数据必须按产品/图号分组冻结，源图和增强变体属于同一组，禁止跨集合泄漏。BOM由两名工程师独立标注、分歧裁决，明确空值/未知/不适用；错误标签须有ERR类型、证据页/框、无错负样本和批准修正值。先建立至少30份代表性装配图与各P0错误正负样本，再报告带样本量的精度和不确定性。

## 验证

原46测试保持通过；新增后62测试通过。包含非法JSON重读、耗尽退出、认证错误不盲重试、证据/页码校验、漏检字段分母、缺失预测计入漏检、材料不适用、单位等价、负数量，以及PNG/PDF修订副本和审计。JS通过Node语法检查。HTTP mock审图、修订生成和下载通过。真实Qwen BOM两次和一次hybrid审图已运行，均仅用公开图纸。

## 统一入口更新

按用户界面反馈，将菜单合并为“BOM 与图纸纠错”。一次上传同时显示BOM、标题栏、规则与VLM问题、尺寸抽取和原图修订控件；原图预览和修订直接复用本次BOM任务。独立的文档提取、对比模块保留代码，已移除其主导航入口。联合HTTP测试覆盖BOM与审图结果、源哈希、原图预览、修订与下载。
