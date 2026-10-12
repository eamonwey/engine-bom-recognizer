# -*- coding: utf-8 -*-
"""BOM 数据结构、字段校验、去重合并与序列化。

输出 JSON 结构（与 data/annotations/ 下人工标注使用同一结构，便于直接评测）:
{
  "document_id": "demo_engine",
  "source_file": "demo_engine.pdf",
  "generated_at": "2026-09-14T10:00:00",
  "model_info": {"provider": "mock", "model": "...", "prompt_version": "v1"},
  "components": [BomComponent, ...],
  "summary": {"total_components": 12, "total_quantity": 43},
  "validation_issues": ["..."]
}
"""
import re
import math
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# 组件字段定义（顺序即 CSV 导出列顺序）
COMPONENT_FIELDS = [
    "item_no", "part_number", "name_zh", "name_en", "category",
    "specification", "material", "quantity", "weight", "unit", "position",
    "supplier", "remark", "needs_review", "review_reasons", "source_page", "confidence",
]

TEXT_FIELDS = [
    "part_number", "name_zh", "name_en", "category", "specification",
    "material", "unit", "position", "supplier", "remark",
]

INT_FIELDS = ["item_no", "quantity", "source_page"]
FLOAT_FIELDS = ["weight", "confidence"]
BOOL_FIELDS = ["needs_review"]
LIST_FIELDS = ["review_reasons"]

_NON_NUMERIC_QUANTITY_RE = re.compile(
    r"(?:^|[\s:：])(?:AR|A/R|AS\s*REQ(?:UIRED)?|按需|见注|参见|—|–|-)(?:$|[\s（(])",
    re.IGNORECASE,
)


def explicit_non_numeric_quantity(remark: Any) -> bool:
    """Printed AR/footnote quantities are unknown, not missing evidence."""
    return bool(_NON_NUMERIC_QUANTITY_RE.search(" " + str(remark or "")))


@dataclass
class BomComponent(object):
    """单个发动机元器件（BOM 行）。"""
    item_no: Optional[int] = None
    part_number: str = ""          # 图号/件号/物料号
    name_zh: str = ""              # 中文名称
    name_en: str = ""              # 英文名称
    category: str = ""             # 功能系统分类，如 曲柄连杆机构
    specification: str = ""        # 规格型号
    material: str = ""             # 材料
    quantity: Optional[int] = None # 数量（整数；未知为 None）
    weight: Optional[float] = None # 重量(g)（明细栏单重；未知为 None）
    unit: str = ""                 # 单位：件/套/个...
    position: str = ""             # 装配位置
    supplier: str = ""             # 供应商
    remark: str = ""               # 备注
    needs_review: bool = False     # 确定性校验发现疑点，需人工核实
    review_reasons: List[str] = field(default_factory=list)  # 触发核实的具体原因
    source_page: Optional[int] = None
    confidence: Optional[float] = None

    def display_name(self) -> str:
        return self.name_zh or self.name_en or self.part_number or "<未命名>"

    def to_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in COMPONENT_FIELDS}


@dataclass
class BomDocument(object):
    """一份输入文档对应的完整 BOM。"""
    document_id: str
    source_file: str = ""
    generated_at: str = ""
    model_info: Dict[str, Any] = field(default_factory=dict)
    components: List[BomComponent] = field(default_factory=list)
    validation_issues: List[str] = field(default_factory=list)
    process_time_s: Optional[float] = None
    assembly: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_components(self) -> int:
        return len(self.components)

    @property
    def total_quantity(self) -> int:
        return sum(c.quantity for c in self.components if c.quantity is not None)

    def summary(self) -> Dict[str, Any]:
        return {
            "total_components": self.total_components,
            "total_quantity": self.total_quantity,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "2.0",
            "document_id": self.document_id,
            "source_file": self.source_file,
            "generated_at": self.generated_at,
            "model_info": self.model_info,
            "components": [c.to_dict() for c in self.components],
            "assembly": self.assembly,
            "summary": self.summary(),
            "validation_issues": self.validation_issues,
            "process_time_s": self.process_time_s,
        }


# ---------------------------------------------------------------------------
# 字段解析 / 类型强制
# ---------------------------------------------------------------------------

def _coerce_int(value: Any) -> Tuple[Optional[int], Optional[str]]:
    """把模型输出的数量类字段尽量转成 int，失败返回 (None, 警告)。"""
    if value is None or value == "":
        return None, None
    if isinstance(value, bool):
        return None, "布尔值不是合法整数: %r" % (value,)
    if isinstance(value, int):
        return value, None
    if isinstance(value, float):
        if float(value).is_integer():
            return int(value), None
        return None, "数值不是整数: %r" % (value,)
    text = str(value).strip()
    # "4" / "4.0" / "4件" / "4 件（每组3个）" -> 取第一个数字
    m = re.search(r"[+-]?\d+(?:\.\d+)?", text)
    if not m:
        return None, "无法从 %r 中解析整数" % (value,)
    num = float(m.group(0))
    if num.is_integer():
        return int(num), ("字段 %r 含额外文本，已截取数字" % (value,)) if m.group(0) != text else None
    return None, "数值不是整数: %r" % (value,)


def _coerce_float(value: Any) -> Tuple[Optional[float], Optional[str]]:
    if value is None or value == "":
        return None, None
    try:
        number = float(value)
        if not math.isfinite(number):
            return None, "浮点数必须为有限数值: %r" % (value,)
        return number, None
    except (TypeError, ValueError):
        return None, "无法解析浮点数: %r" % (value,)


def _coerce_bool(value: Any) -> Tuple[bool, Optional[str]]:
    if isinstance(value, bool):
        return value, None
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value), None
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "y", "是", "待核实", "需核实"):
        return True, None
    if text in ("false", "0", "no", "n", "", "否", "无"):
        return False, None
    return True, "无法识别的布尔值 %r，按 true 处理" % (value,)


def _coerce_str_list(value: Any) -> Tuple[List[str], Optional[str]]:
    if value is None or value == "":
        return [], None
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()], None
    return [str(value).strip()], None


def component_from_dict(raw: Dict[str, Any]) -> Tuple[BomComponent, List[str]]:
    """从模型输出的 dict 构建 BomComponent，做类型清洗，收集警告。"""
    warnings: List[str] = []
    comp = BomComponent()
    known_alias = {
        "no": "item_no", "序号": "item_no", "item": "item_no",
        "pn": "part_number", "part_no": "part_number", "图号": "part_number", "件号": "part_number",
        "name": "name_zh", "名称": "name_zh", "名称（中文）": "name_zh", "中文名称": "name_zh",
        "名称（英文）": "name_en", "english_name": "name_en", "英文名称": "name_en",
        "类别": "category", "分类": "category",
        "规格": "specification", "规格型号": "specification", "spec": "specification",
        "材料": "material", "材质": "material",
        "数量": "quantity", "qty": "quantity",
        "重量": "weight", "单重": "weight", "重量(g)": "weight", "weight": "weight", "weight_g": "weight",
        "单位": "unit", "装配位置": "position", "位置": "position",
        "供应商": "supplier", "备注": "remark",
        "页码": "source_page", "page": "source_page",
        "置信度": "confidence",
    }
    for key, value in raw.items():
        name: Optional[str] = None
        if isinstance(key, str):
            stripped = key.strip()
            if stripped in COMPONENT_FIELDS:
                name = stripped
            elif stripped in known_alias:
                name = known_alias[stripped]
            elif stripped.lower() in known_alias:
                name = known_alias[stripped.lower()]
        if name is None:
            continue
        if name in INT_FIELDS:
            iv, warn = _coerce_int(value)
            if warn:
                warnings.append(("非整数原始序号已保留: %r" % value) if name == "item_no" else warn)
            setattr(comp, name, iv)
        elif name in FLOAT_FIELDS:
            fv, warn = _coerce_float(value)
            if warn:
                warnings.append(warn)
            setattr(comp, name, fv)
        elif name in BOOL_FIELDS:
            bv, warn = _coerce_bool(value)
            if warn:
                warnings.append(warn)
            setattr(comp, name, bv)
        elif name in LIST_FIELDS:
            lv, warn = _coerce_str_list(value)
            if warn:
                warnings.append(warn)
            setattr(comp, name, lv)
        elif value is None:
            setattr(comp, name, "")
        else:
            setattr(comp, name, str(value).strip())
    original_labels = [w for w in warnings if w.startswith("非整数原始序号已保留:")]
    if original_labels:
        comp.remark = "; ".join([v for v in [comp.remark] + original_labels if v])
    return comp, warnings


def components_from_payload(payload: Any) -> Tuple[List[BomComponent], List[str]]:
    """把解析出的 JSON 载荷（dict 或 list）转成组件列表。"""
    warnings: List[str] = []
    if isinstance(payload, dict):
        for key in ("components", "bom", "items", "parts", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            warnings.append("JSON 对象中未找到 components 列表，已忽略: %s" % list(payload.keys()))
            return [], warnings
    if not isinstance(payload, list):
        warnings.append("JSON 载荷既不是 list 也不是含 components 的 dict: %r" % type(payload))
        return [], warnings
    comps: List[BomComponent] = []
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            warnings.append("第 %d 个条目不是对象，已跳过" % (i + 1))
            continue
        comp, warns = component_from_dict(item)
        warnings.extend("[%s] %s" % (comp.display_name(), w) for w in warns)
        comps.append(comp)
    return comps, warnings


# ---------------------------------------------------------------------------
# 校验 / 去重合并
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 标准号-名称一致性校验（确定性规则，拦截 GB/T 代号误读/误写）
# ---------------------------------------------------------------------------

# 归一化标准号（normalize_part_number 后的键）-> (标准名称, 名称应包含的关键词)
# 关键词命中任一即视为与标准相符；不命中则报"疑似引用错误"。
# 仅收录可确认的标准，未收录的代号不参与校验（避免误报）。
_GB_STANDARD_HINTS: Dict[str, Tuple[str, List[str]]] = {
    # 滚动轴承
    "GBT276": ("深沟球轴承", ["轴承"]),
    "GBT283": ("圆柱滚子轴承", ["轴承"]),
    "GBT285": ("圆锥滚子轴承", ["轴承"]),
    "GBT292": ("角接触球轴承", ["轴承"]),
    # 螺栓/螺柱
    "GBT5780": ("六角头螺栓 C级", ["螺栓"]),
    "GBT5781": ("六角头螺栓 全螺纹 C级", ["螺栓"]),
    "GBT5782": ("六角头螺栓", ["螺栓"]),
    "GBT5783": ("六角头螺栓 全螺纹", ["螺栓"]),
    # 螺母
    "GBT41": ("六角螺母 C级", ["螺母"]),
    "GBT6170": ("1型六角螺母", ["螺母"]),
    "GBT6171": ("1型六角螺母 细牙", ["螺母"]),
    "GBT6172": ("六角薄螺母", ["螺母"]),
    # 螺钉
    "GBT65": ("开槽圆柱头螺钉", ["螺钉"]),
    "GBT67": ("开槽盘头螺钉", ["螺钉"]),
    "GBT68": ("开槽沉头螺钉", ["螺钉"]),
    "GBT818": ("十字槽盘头螺钉", ["螺钉"]),
    "GBT819": ("十字槽沉头螺钉", ["螺钉"]),
    "GBT845": ("十字槽盘头自攻螺钉", ["螺钉"]),
    # 销
    "GBT91": ("开口销", ["开口销"]),
    "GBT117": ("圆锥销", ["锥销"]),
    "GBT119": ("圆柱销", ["圆柱销"]),
    # 键
    "GBT1095": ("平键 键槽的剖面尺寸", ["键"]),
    "GBT1096": ("普通型 平键", ["键"]),
    "GBT1097": ("导向型 平键", ["键"]),
    # 垫圈/挡圈
    "GBT93": ("标准型弹簧垫圈", ["垫圈"]),
    "GBT96": ("大系列 平垫圈", ["垫圈"]),
    "GBT848": ("小系列 平垫圈", ["垫圈"]),
    "GBT893": ("孔用弹性挡圈", ["挡圈"]),
    "GBT894": ("轴用弹性挡圈", ["挡圈"]),
    # 油封
    "GBT13871": ("旋转轴唇形密封圈", ["油封"]),
    "GBT138711": ("旋转轴唇形密封圈 第1部分", ["油封"]),
    # 实测中曾被误读/误写进 BOM 的真实标准（领域与机械紧固件无关，命中即几乎必错）
    "GBT1276": ("化学试剂 氟化铵", ["氟化铵"]),
    "GBT1117": ("直齿三面刃铣刀", ["铣刀"]),
    "GBT15780": ("竹材物理力学性质试验方法", ["竹材"]),
}

# 名称关键词 -> 该类零件的常用标准（用于校验提示中的修正建议）
_NAME_TO_STANDARD: List[Tuple[str, str]] = [
    ("深沟球轴承", "GB/T 276"), ("圆锥滚子轴承", "GB/T 285"), ("圆柱滚子轴承", "GB/T 283"),
    ("轴承", "GB/T 276 等"), ("螺栓", "GB/T 5780~5783"), ("螺钉", "GB/T 818/819"),
    ("螺母", "GB/T 6170 或 GB/T 41"), ("圆锥销", "GB/T 117"), ("圆柱销", "GB/T 119"),
    ("开口销", "GB/T 91"), ("销", "GB/T 117/119"), ("平键", "GB/T 1096"), ("键", "GB/T 1096"),
    ("垫圈", "GB/T 97 或 GB/T 93"), ("挡圈", "GB/T 893/894"), ("油封", "GB/T 13871"),
]

_GB_CODE_RE = re.compile(r"^GB/?T?\s*\d", re.IGNORECASE)
_GB_REFERENCE_RE = re.compile(
    r"^(GB\s*/?\s*T?)\s*(\d+(?:\.\d+)*)(?:\s*[-—–]\s*\d{4})?$", re.IGNORECASE)


def _standard_reference_key(reference: str) -> str:
    text = unicodedata.normalize("NFKC", str(reference or "")).strip()
    match = _GB_REFERENCE_RE.fullmatch(text)
    return normalize_part_number(match.group(1) + match.group(2)) if match else ""


def _standard_reference_findings(components: List[BomComponent]) -> List[Tuple[int, str]]:
    """标准号-名称一致性检查的逐行版本，返回 (行号, 描述) 列表。"""
    findings: List[Tuple[int, str]] = []
    for idx, c in enumerate(components, start=1):
        pn = str(c.part_number or "").strip()
        key = _standard_reference_key(pn)
        if not key:
            continue
        name_zh = str(c.name_zh or "").strip()
        if not name_zh:
            continue  # 英文名暂不参与比对，避免外文名误报
        hint = _GB_STANDARD_HINTS.get(key)
        if not hint:
            continue
        desc, keywords = hint
        if any(kw in name_zh for kw in keywords):
            continue
        suggest = ""
        for kw, std in _NAME_TO_STANDARD:
            if kw in name_zh:
                suggest = std
                break
        msg = "#%d %s: 标准号引用疑似错误: %s 对应《%s》，与名称「%s」不符" % (
            idx, c.display_name(), pn, desc, name_zh)
        if suggest:
            msg += "；该类零件常用标准: %s，请核实" % suggest
        findings.append((idx, msg))
    return findings


def check_standard_references(components: List[BomComponent]) -> List[str]:
    """校验 GB/T 标准号与零件名称是否相符，返回疑似引用错误清单。

    只比对有中文名称且标准号收录在 _GB_STANDARD_HINTS 中的行；
    名称缺失或标准号未收录时不判（保守，避免误报）。
    """
    return [msg for _, msg in _standard_reference_findings(components)]


def validate_components(components: List[BomComponent], strict: bool = False,
                        attach_flags: bool = True,
                        allow_repeated_rows: bool = False) -> List[str]:
    """多层规则校验（对应论文中的 rule conformity / semantic consistency 校验层）。

    strict=True 时发现错误即抛 ValueError；否则返回问题清单。
    attach_flags=True 时把逐行问题写回组件的 needs_review / review_reasons，
    供前端高亮与导出（比模型自报置信度可靠）。
    allow_repeated_rows=True（preserve_printed_rows 模式）时，同码同名的重复行
    是原图合法写法（同一标准件用于多处、各自保留一行），不判"件号重复"。
    """
    findings: List[Tuple[int, str]] = []
    for idx, c in enumerate(components, start=1):
        tag = "#%d %s" % (idx, c.display_name())
        if not (c.part_number or c.name_zh or c.name_en):
            findings.append((idx, "%s: 缺少任何可识别标识（part_number/name_zh/name_en 均为空）" % tag))
        if c.quantity is not None and c.quantity <= 0:
            findings.append((idx, "%s: 数量非正数 %r" % (tag, c.quantity)))
        if (c.quantity is None and not (c.material or "").strip()
                and not (c.part_number or "").strip()
                and not explicit_non_numeric_quantity(c.remark)):
            # 数量/材料/件号全空：真实明细行几乎必有数量。此模式多见于
            # 无明细表的视图页——模型照球标编造的占位行，必须标给人工核实。
            findings.append((idx, "%s: 数量、材料、件号均为空——疑似无明细表页的占位行，请对照原图核实" % tag))
        if c.weight is not None and not math.isfinite(c.weight):
            findings.append((idx, "%s: 重量必须为有限数值: %r" % (tag, c.weight)))
        if c.confidence is not None and not (0.0 <= c.confidence <= 1.0):
            findings.append((idx, "%s: 置信度超出 [0,1]: %r" % (tag, c.confidence)))
    # 件号冲突检测（对应论文 collision detection）。
    # 国标代号（GB/GB/T 开头）允许不同规格复用同一标准号（如 轴承6204/6206 同引 GB/T 276），
    # 仅当名称也相同时才判重；企业自编号（如 ENG-1）仍按件号唯一判重。冲突标记到相关各行。
    seen: Dict[str, Tuple[int, str]] = {}
    dup_groups: Dict[int, List[int]] = {}
    for idx, c in enumerate(components, start=1):
        key = normalize_part_number(c.part_number) if c.part_number else ""
        if not key:
            continue
        nm = normalize_text(c.name_zh) or normalize_text(c.name_en)
        if key in seen:
            first_idx, first_nm = seen[key]
            same_name = (nm == first_nm)
            if same_name and allow_repeated_rows:
                pass  # preserve 模式：原图合法的重复行
            elif same_name or not _GB_CODE_RE.match(key):
                findings.append((first_idx, "件号重复: #%d 与 #%d 均为 %s" % (first_idx, idx, c.part_number)))
                findings.append((idx, "件号重复: #%d 与 #%d 均为 %s" % (first_idx, idx, c.part_number)))
        else:
            seen[key] = (idx, nm)
    findings.extend(_standard_reference_findings(components))
    if attach_flags:
        by_row: Dict[int, List[str]] = {}
        for idx, msg in findings:
            by_row.setdefault(idx, []).append(msg)
        for idx, c in enumerate(components, start=1):
            c.review_reasons = by_row.get(idx, [])
            c.needs_review = bool(c.review_reasons)
    if strict and findings:
        raise ValueError("BOM 校验失败:\n" + "\n".join(msg for _, msg in findings))
    return [msg for _, msg in findings]


def _dedup_key(c: BomComponent) -> Tuple[str, str, str]:
    return (
        normalize_part_number(c.part_number),
        normalize_text(c.name_zh) or normalize_text(c.name_en),
        normalize_text(c.specification),
    )


def merge_components(pages_of_components: List[List[BomComponent]],
                     quantity_policy: str = "keep_max") -> Tuple[List[BomComponent], List[str]]:
    """跨页合并、按（件号, 名称, 规格）去重，并重新编号。

    quantity_policy:
      keep_max  取多次出现的最大数量（默认；防止"明细表+装配图引用"场景重复计数）
      sum       数量累加（适用于同一张 BOM 表跨页拆分、行内分列的场景）
      keep_first 保留首次出现的数量
    """
    notes: List[str] = []
    merged: Dict[Tuple[str, str, str], BomComponent] = {}
    order: List[Tuple[str, str, str]] = []
    for page_comps in pages_of_components:
        for c in page_comps:
            key = _dedup_key(c)
            if key in merged:
                base = merged[key]
                if c.quantity is not None:
                    if base.quantity is None:
                        base.quantity = c.quantity
                    elif quantity_policy == "sum" and (base.unit or "") == (c.unit or ""):
                        base.quantity += c.quantity
                    elif quantity_policy == "keep_max":
                        base.quantity = max(base.quantity, c.quantity)
                    # keep_first: 不变
                if quantity_policy != "sum":
                    notes.append("跨页重复元器件已合并: %s（数量策略 %s）"
                                 % (base.display_name(), quantity_policy))
                else:
                    notes.append("跨页重复元器件已合并数量: %s -> %d" % (base.display_name(), base.quantity))
                if c.remark and c.remark not in base.remark:
                    base.remark = (base.remark + "; " + c.remark).strip("; ")
                if not base.part_number and c.part_number:
                    base.part_number = c.part_number
                if not base.name_en and c.name_en:
                    base.name_en = c.name_en
                if base.weight is None and c.weight is not None:
                    base.weight = c.weight
                if base.source_page and c.source_page and c.source_page < base.source_page:
                    base.source_page = c.source_page
            else:
                merged[key] = c
                order.append(key)
    result = [merged[k] for k in order]
    for i, c in enumerate(result, start=1):
        c.item_no = i
    return result, notes


# ---------------------------------------------------------------------------
# 归一化（评测匹配用）
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"[\s\-_/\\.,:;()（）\[\]【】]+")
_FULL2HALF = {ord(f): ord(t) for f, t in zip(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")}


def normalize_part_number(value: str) -> str:
    """件号归一化：全角转半角、去空白与分隔符、大写。"""
    text = str(value or "").translate(_FULL2HALF)
    return _WS_RE.sub("", text).upper()


def normalize_text(value: str) -> str:
    """文本归一化：全角转半角、去空白与标点、小写。"""
    text = str(value or "").translate(_FULL2HALF)
    return _WS_RE.sub("", text).lower()
