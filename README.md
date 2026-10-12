# 公开源码版：快速运行

此仓库包含系统源码、网页界面、离线测试及人工构造示例。Python 3.10 或以上版本推荐用于新安装环境。

```bash
git clone https://github.com/eamonwey/engine-bom-recognizer.git
cd engine-bom-recognizer
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install openpyxl  # 可选：Excel 导出
```

把 `config.example.yaml` 复制为 `config.yaml`，然后启动：

```bash
python -X utf8 scripts/make_demo_data.py
python -X utf8 -m engine_bom.webapp
```

打开 http://127.0.0.1:8787/ ，上传刚生成的 `data/raw/demo_engine_bom.pdf`。
默认 Mock 模型返回固定演示结果，不代表真实图纸识别效果。启用真实识别时，在网页“系统设置”配置 OpenAI 兼容视觉模型，并按需要启用装配识别与工程检查。

本公开版本不包含个人 API 密钥、原始上传图纸、运行结果、审核账号/令牌、数据库或外部数据集镜像。需要的演示输入可以通过上述脚本重新生成；四个装配单元测试标签是人工构造测试数据。

离线测试：`python -X utf8 -m unittest discover -s tests -q`。浏览器回归脚本需要另装 Playwright 及浏览器。

GitHub 仓库用于分享源码；运行 Python 后端后才能使用网页功能。

---

# 发动机元器件识别与 BOM 生成系统

> 📗 **最终用户、工艺工程师和系统管理员请先看 [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md)** —— 包含安装启动、页面操作、模型配置、BOM 与图纸纠错、文档提取、变更影响、三角色审核、API、数据管理和故障处理。
>
> 📘 **开发者/新接手者请看 [`docs/PROJECT_HANDOFF.md`](docs/PROJECT_HANDOFF.md)** —— 项目全景与 AI 交接文档：完整需求清单（18 条子功能 + 10 类图纸错误检测 + 5 条硬约束）、每个功能的实现状态与代码位置、设计决策理由、已修复缺陷清单、待办事项。把它整份导入即可作为资料库使用，避免重复造轮子。
>
> 本文件（README）面向使用者，讲安装、启动与操作。

输入发动机工程文档（PDF / 图片 / Word / 扫描件），输出结构化 BOM（JSON / CSV / Excel），
并提供 Web 界面完成 **BOM 识别 → 文档要素提取 → 文件变更对比 → 图纸规则检查 → 人工复核** 全流程。
视觉模型通过 **Provider 接口** 插拔：当前内置离线 Mock 与 OpenAI 兼容 API 模板（含内网 vLLM 部署），
接入模型**不需要改动业务代码**。

架构参考：Lin & Dang (2026) *From product specifications to smart manufacturing: Generative AI-driven process innovation for BOM digitization and its applications*（LLM+RAG 的 BOM 数字化闭环）。

## 功能对照（AI工艺项目需求规格表 V1.0）

| 需求 | 子功能 | 状态 |
|---|---|---|
| REQ-01 | 多格式图纸接入与预处理（PDF/图片 + 去噪/倾斜校正/二值化） | ✅ 已实现（DWG/DXF 需内网转换，见下文） |
| REQ-01 | 标题栏信息提取 | ✅ 已实现（VLM + 字段必填校验） |
| REQ-01 | 明细栏/零部件信息提取（含跨页合并） | ✅ 已实现 |
| REQ-01 | 装配层级关系识别（多级 BOM 树） | ⏳ 预留（P1，需求表建议初期一级装配+人工确认） |
| REQ-01 | BOM 结构化生成与导出（Excel/CSV/JSON） | ✅ 已实现 |
| REQ-01 | 图纸与 BOM 一致性校验 | ✅ 已实现（件号重复/数量/编码规则校验 + 检查报告） |
| REQ-02 | 多格式文件解析（docx/pdf/txt/图片 + 版面还原） | ✅ 已实现（docx 标准库解析，扫描页走 VLM） |
| REQ-02 | 技术参数 / 材料工艺 / 检验标准提取 | ✅ 已实现（四类要素统一 JSON） |
| REQ-02 | 结构化输出与系统对接（REST API） | ✅ 已实现（REST API + JSON/Excel 导出） |
| REQ-02 | 人工复核与修正机制 | ✅ 已实现（Web 复核编辑 + 修正记录留档） |
| REQ-03 | 多版本文档对齐与解析 | ✅ 已实现（段落级 difflib 对齐，句向量对齐为内网升级项） |
| REQ-03 | 变更自动识别与高亮（新增/删除/修改） | ✅ 已实现（绿/红/黄高亮 + 筛选 + 忽略格式） |
| REQ-03 | 变更类型分类 | ✅ 已实现（规则分类，可替换为 LLM） |
| REQ-03 | 变更影响范围分析 | ⏳ 预留（P2，需企业知识库关联） |
| REQ-03 | ECN 变更单自动生成 | ✅ 已实现（Markdown 草稿，企业模板可替换） |
| REQ-03 | 变更历史追溯与查询 | ✅ 已实现 |
| Sheet3 | ERR-01 尺寸矛盾（数值比对） | ✅ 规则实现（需 VLM 抽取尺寸列表） |
| Sheet3 | ERR-06 材料不明/矛盾 | ✅ 规则实现 |
| Sheet3 | ERR-08 标题栏/明细栏错误（含引出序号对应） | ✅ 规则实现 |
| Sheet3 | ERR-02/03/04/05/07/09/10（缺漏标注/公差/形位公差/视图一致性/标准件/技术要求/格式） | ⏳ 第二阶段（需 CV 符号识别 + 标注数据积累） |

## 架构

```
输入 PDF/图片/Word/文档
   │
   ▼
┌─────────────────────┐   Step1 文档解析结构化
│ ingestion.py        │   PDF 按 DPI 渲染；图片直载；preprocess.py 去噪/倾斜校正/二值化
│ docextract.py       │   docx（标准库解析）/pdf/txt 文本抽取
└─────────┬───────────┘
          ▼
┌─────────────────────┐   Step2 模型识别（可插拔）
│ providers/          │   per_page 逐页 | whole_doc 整档；openai_compat 支持内网 vLLM
│  ├ base.py   接口    │   knowledge.py 注入企业命名/分类规则（RAG 检索）
│  ├ mock.py   离线Mock│
│  └ openai_compat.py │   ← 【视觉模型 API 接入点】
├─────────────────────┤
│ titleblock.py       │   标题栏字段提取        （REQ-01-2）
│ docextract.py       │   技术参数/材料/工艺/检验（REQ-02）
│ changedetect.py     │   版本对齐/变更识别/ECN  （REQ-03）
└─────────┬───────────┘
          ▼
┌─────────────────────┐   Step3 解析与多层校验
│ parsing.py          │   鲁棒 JSON 提取（代码块/尾逗号/智能引号容错）
│ schema.py           │   类型清洗 → 跨页去重合并 → 件号冲突检测
│ inspect_rules.py    │   ERR-01/06/08 规则检查（报告含严重度与整改建议）
└─────────┬───────────┘
          ▼
┌─────────────────────┐   Step4 装配、导出与复核
│ export.py           │   JSON / CSV(utf-8-sig) / XLSX；文件被占用时自动改名
│ webapp.py + static/ │   Web 界面（识别/提取/对比/检查/复核/设置）
│ traces/*.json       │   原始模型输出留档（human-in-the-loop 审计）
└─────────┬───────────┘
          ▼
     评测 evaluation/    P/R/F1 + 字段准确率 + 完全正确率（宏/微平均）
```

## 安装与启动

```bash
cd engine-bom-recognizer
pip install -r requirements.txt        # pymupdf / pillow / pyyaml（openpyxl、opencv 可选）

# 启动 Web 服务（纯标准库实现，无额外依赖）
python -X utf8 -m engine_bom.webapp                    # 默认 http://127.0.0.1:8787
python -X utf8 -m engine_bom.webapp --host 0.0.0.0     # 内网部署（同事可访问）
```

浏览器打开 `http://127.0.0.1:8787/`，左侧六个功能区：图纸 BOM 识别 / 文档要素提取 / 文件变更对比 / 图纸规则检查 / 复核与历史 / 系统设置。

## ★ 接入视觉模型 API（两种方式，任选）

**方式一：网页设置（推荐，无需重启）**

进入「系统设置」页填写四项后点「保存设置」：

| 字段 | 示例 |
|---|---|
| Provider | `openai_compat` |
| Base URL | `https://dashscope.aliyuncs.com/compatible-mode/v1`（阿里百炼）/ `http://10.0.0.5:8000/v1`（内网 vLLM） |
| 模型名 | `qwen3.8-max` / `Qwen2.5-VL-72B-Instruct` |
| API Key | `sk-...`（留空则沿用已保存值或环境变量） |

点「🔌 测试连接」可**在保存前**验证连通性——它会用当前输入框里的值发一次极短请求（max_tokens=32），
成功显示模型回复与耗时，失败直接显示 API 返回的错误原因（如 401 密钥错误、模型名不存在）。
配置保存在 `data/web_settings.json`，优先级高于环境变量；「清除已保存的 Key」可随时删除。
设置好后各功能页的「模型」下拉框选「默认配置」即走该模型。

**方式二：环境变量（适合命令行/批量实验与 CI）**

```bash
# Linux/macOS
export VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
export VISION_MODEL=qwen3.8-max
export VISION_API_KEY=sk-你的key
```
```powershell
# Windows PowerShell
$env:VISION_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:VISION_MODEL="qwen3.8-max"
$env:VISION_API_KEY="sk-你的key"
```

**非 OpenAI 兼容的 API**：新建 `providers/my_model.py` 继承 `VisionProvider`，实现
`analyze(images, prompt) -> ProviderResponse`，在 `providers/__init__.py` 的 `PROVIDERS` 登记，
然后网页设置页 Provider 选它（或 `--provider my_model`）。详见 `providers/base.py` 顶部注释。

命令行同样可用（适合批量与实验）：

```bash
python -X utf8 scripts/make_demo_data.py                        # 生成演示数据
python -X utf8 -m engine_bom.cli process data/raw/demo_engine_bom.pdf
python -X utf8 -m engine_bom.cli experiment configs/experiment_demo.yaml
```

## 内网部署（约束 C-01/C-02：图纸不出厂区）

1. 内网 GPU 服务器部署开源多模态模型，开启 OpenAI 兼容接口，例如 vLLM：
   ```bash
   vllm serve Qwen/Qwen2.5-VL-72B-Instruct --port 8000
   ```
   （也可用 InternVL + LMDeploy 等，只要暴露 `/v1/chat/completions`）
2. 在网页「系统设置」中把 Provider 设为 `openai_compat`、Base URL 填 `http://内网IP:8000/v1`、模型名填服务加载的模型名；
   或在服务端设环境变量 `VISION_BASE_URL` / `VISION_MODEL` / `VISION_API_KEY`。
3. 全部数据（上传件、任务产物、复核记录）都落在本机 `data/` 目录，无外发请求。

模型接口扩展点见 `providers/base.py`；企业命名规则可放 `data/knowledge/engine_rules.txt`（开启 `knowledge.enabled`）。

## 数据集规范（拿到数据集后按此放置）

```
data/raw/<doc_id>.pdf|.png|.jpg...      # 输入文档
data/annotations/<doc_id>.json          # 人工标注 BOM，与系统输出同构
```

```bash
python -X utf8 -m engine_bom.cli experiment configs/experiment_demo.yaml
```

## REST API（供 PLM/MES/ERP 对接）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/jobs/bom` | 上传图纸 → BOM 识别 + 标题栏 + 规则检查（异步） |
| POST | `/api/jobs/doc` | 上传文档 → 关键要素提取（异步） |
| POST | `/api/jobs/compare` | 上传两版文件 → 变更对比（异步） |
| POST | `/api/jobs/inspect` | 上传图纸 → 规则检查（异步） |
| GET | `/api/jobs/<id>` | 任务状态与结果（前端每 1.5s 轮询） |
| POST | `/api/bom/save`、`/api/doc/save` | 人工复核结果保存 + 修正记录 |
| GET | `/api/export/bom/<id>?fmt=json\|csv\|xlsx` | BOM 下载 |
| GET | `/api/export/doc/<id>?fmt=json\|xlsx` | 要素提取下载 |
| GET | `/api/compare/<id>/ecn.md` | 变更单（ECN）草稿 |
| GET | `/api/history`、`/api/reviewlog` | 变更历史 / 人工修正记录 |
| GET | `/api/status`、POST `/api/config` | 模型配置状态与运行时修改 |

## 关键配置（config.yaml）

| 配置 | 说明 |
|---|---|
| `provider.name` | `mock` / `openai_compat` |
| `recognition.mode` | `per_page`（逐页合并，稳）/ `whole_doc`（整档一次，省调用） |
| `recognition.duplicate_quantity_policy` | 跨页重复数量策略：`keep_max`（默认）/ `sum` / `keep_first` |
| `ingestion.preprocess` | 扫描件预处理开关：倾斜校正 / 去噪 / 二值化 / 对比度 |
| `knowledge.enabled` | 企业规则检索注入提示词（RAG 简化版） |
| `output.formats` | json / csv / xlsx |
| `ENGINE_BOM_API_TOKEN` | Web POST 请求令牌；未设置时每次启动自动生成页面会话令牌 |
| `ENGINE_BOM_MAX_UPLOAD_MB` | 单次请求上限，默认 100 MB |
| `ENGINE_BOM_JOB_TTL_HOURS` | 已完成任务及文件保留时间，默认 24 小时 |
| `ENGINE_BOM_MAX_JOBS` | 内存中最多保留的任务数，默认 200 |

## 与参考论文的对应关系

| 论文模块 | 本系统实现 |
|---|---|
| Step1 文档解析与结构化 | `ingestion.py` + `preprocess.py` + `docextract.py` |
| Step2 RAG-LLM 协同生成 | `providers/` + `knowledge.py` + `prompts.py`（双语提示词） |
| Step3 工程师校验 | Web 复核界面 + `data/reviewed/` + `data/review_log.json` |
| Step4 约束解码与多层校验 | `parsing.py` JSON 容错 + `schema.py` 校验 + `inspect_rules.py` 规则检查 |
| 10 折交叉验证评测 | `evaluation/`（宏/微平均、均值±标准差）+ `experiment.py` 多 run 对比 |

## 待实现（按需求表优先级）

- 装配层级关系识别（REQ-01-4，P1）：需从引出序号 + 视图反推父子关系，建议一级装配先行、人工确认
- 变更影响范围分析（REQ-03-4，P2）：需企业文档关联关系/知识图谱支撑
- ERR-02/03/04/05 等 VLM 推理类图纸检查：需 CV 符号识别 + 标注数据积累（第二阶段）
- DWG/DXF 原生解析：内网安装 ODA File Converter 或 ezdxf 渲染后接入
- 句向量段落对齐（替代 difflib）、10 折交叉验证

## 运行测试

```bash
python -X utf8 -m unittest discover -s tests -v     # 运行全部回归测试
```


## ★ 视觉模型 API 接入指南（拿到 API 后 3 分钟切换）

系统通过 `VisionProvider` 抽象调用视觉模型，`openai_compat.py` 已实现
OpenAI 兼容 `/chat/completions` 协议（自动把页面图像转 base64 data-uri 多图传入），
适配 GPT-4o / Qwen-VL（DashScope 兼容模式，即论文所用 Qwen2.5-VL）/ GLM-4V / vLLM 本地部署等。

**推荐：环境变量方式（不动代码、不进 git）**

```bash
set VISION_BASE_URL=https://open.bigmodel.cn/api/paas/v4     # 例：智谱 GLM-4V
set VISION_MODEL=glm-4v-plus
set VISION_API_KEY=你的key
python -X utf8 -m engine_bom.cli process 某图纸.pdf --provider openai_compat
```

或写入 `config.yaml`（`provider.openai_compat.base_url / model`），再在实验规格里加 run：

```yaml
runs:
  - name: glm4v_per_page
    provider: openai_compat
    provider_options:
      base_url: https://open.bigmodel.cn/api/paas/v4
      model: glm-4v-plus
```

常见端点：OpenAI `https://api.openai.com/v1`；阿里 DashScope
`https://dashscope.aliyuncs.com/compatible-mode/v1`；本地 vLLM `http://localhost:8000/v1`。

**如果你的 API 不是 OpenAI 兼容协议**：新建 `providers/my_model.py` 继承
`VisionProvider`，实现 `analyze(images, prompt) -> ProviderResponse`，在
`providers/__init__.py` 的 `PROVIDERS` 登记，然后 `--provider my_model` 即可。
详见 `providers/base.py` 顶部注释。

## 数据集规范（拿到数据后按此放置，即可直接实验）

```
data/raw/demo_engine_bom.pdf        # 输入文档，文件名 = doc_id
data/annotations/demo_engine_bom.json   # 人工标注，与 doc_id 同名
```

标注 JSON 与系统输出同构（最少只需 `components` 数组，字段可缺省）：

```json
{
  "document_id": "demo_engine_bom",
  "components": [
    {"item_no": 1, "part_number": "ENG-BLK-001", "name_zh": "气缸体", "name_en": "Cylinder Block",
     "category": "机体与气缸盖", "specification": "直列四缸", "material": "铸铁 HT250",
     "quantity": 1, "unit": "件", "position": "发动机主体"}
  ]
}
```

一条命令完成"推理 → 评测 → 跨模型对比"：

```bash
python -X utf8 -m engine_bom.cli experiment configs/experiment_demo.yaml
```

## 评测指标（对齐论文 Table 2 的报告方式）

| 指标 | 含义 |
|---|---|
| Precision / Recall / F1 | 元器件级检测：件号精确匹配（归一化）+ 名称模糊匹配（相似度≥0.75）配对 |
| 字段准确率 | 配对成功的元器件逐字段比对（件号/名称/规格/材料/数量/单位/分类/位置/供应商），仅在标注提供该字段时计分 |
| 完全正确率 | 预测与标注一一对应且全部字段一致 |
| 汇总方式 | 宏平均（各文档平均，报告均值±标准差）+ 微平均（全部池化）+ 平均处理时长 |

报告同时列出漏检清单、误报清单和逐字段错误明细（预测值 vs 标注值），便于改提示词后对照消融。

## 关键配置（config.yaml）

| 配置 | 说明 |
|---|---|
| `provider.name` | `mock` / `openai_compat` |
| `recognition.mode` | `per_page`（逐页识别后合并，稳）/ `whole_doc`（整档一次，省调用） |
| `recognition.duplicate_quantity_policy` | 跨页重复元器件数量策略：`keep_max`（默认，防"明细表+装配图引用"重复计数）/ `sum`（拆表场景）/ `keep_first` |
| `recognition.min_confidence` | 低于该置信度的条目过滤 |
| `knowledge.enabled` | 开启后把 `data/knowledge/*.txt` 里的企业规则检索注入提示词（RAG 简化版） |
| `ingestion.dpi` | PDF 渲染 DPI，扫描件建议 300 |
| `output.formats` | json / csv / xlsx |

## 与参考论文的对应关系

| 论文模块 | 本系统实现 |
|---|---|
| Step1 文档解析与结构化 | `ingestion.py`（PDF/图片→页面图像） |
| Step2 RAG-LLM 协同生成 | `providers/`（多模态模型）+ `knowledge.py`（规则检索注入）+ `prompts.py`（双语提示词） |
| Step3 工程师校验 | `data/predictions/traces/` 原始输出留档 + 校验提示清单（可扩展 Web 复核界面） |
| Step4 约束解码与多层校验 | `parsing.py` JSON 容错 + `schema.py` 件号冲突检测/类型/数量校验 |
| 10 折交叉验证评测 | `evaluation/` 宏/微平均、均值±标准差、处理时长，`experiment.py` 多 run 对比 |

## 已验证 / 待扩展

- ✅ 30 个单元测试全过；演示数据端到端跑通（PDF + 图片输入，多页合并，评测报告）
- 🔜 接入真实视觉模型 API 后：先小样本调 `prompts.py`，再跑全量实验
- 🔜 可选扩展：向量库（Qdrant）替换关键词知识库、Web 标注复核界面、按 BOM 层级（部件→组件）输出

## 运行测试

```bash
python -X utf8 -m unittest discover -s tests -v
```
