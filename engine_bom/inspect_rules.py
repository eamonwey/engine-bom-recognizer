# -*- coding: utf-8 -*-
"""图纸规则检查（Sheet3 图纸错误检测，第一阶段 P0 规则可检类型）。

覆盖:
  ERR-01 尺寸矛盾（数值比对部分，需要 VLM 抽取的尺寸标注列表）
  ERR-06 材料不明/矛盾（标题栏材料字段 + 材料牌号规范校验）
  ERR-08 标题栏/明细栏错误（必填字段完整性、明细栏序号连续性、引出序号对应）
其余类型（公差/形位公差/视图一致性等）依赖 CV 符号识别与 VLM 语义推理，
按需求表建议作为第二阶段，接口已预留 add_issue。
"""
import re
import unicodedata
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from .titleblock import REQUIRED_TITLE_FIELDS
from .schema import explicit_non_numeric_quantity

# 材料牌号合法性：常见国标牌号模式（示例库，企业可扩充 data/knowledge/material_brands.txt）
_MATERIAL_BRAND_PATTERNS = [
    r"^\d{1,2}(Cr|Mn|Mo|Ni|Si|Ti|V|W|Co|Cu)[A-Za-z0-9]*$",
    r"^(GCr\d+|TC\d+|TA\d+|\d{1,2})$",
    r"^[A-Z]\d{2,4}$",                # 45、40Cr、20 号钢风格
    r"^(HT|QT|KT|ZG)[A-Z0-9\-]+$",    # 铸铁/铸钢 HT250、QT500、ZG230-450
    r"^(Q|T)\s?\d{3,4}[A-Z]?$",       # Q235、Q345、T8
    r"^[A-Z]{1,4}\d{2,4}([A-Z0-9\-]+)?$",  # 40Cr、42CrMo、GCr15、Inconel718、TC4、7075
    r"^\d{4}$",                        # 铝合金 2024/6061/7075
    r"^(GB|JB|HB|YB)\s?/?\s?T?\s?\d+", # 直接引标准
    r"^(不锈钢|碳钢|合金钢|铸铁|铸钢|铜|铝|钛|镍|镁|锌)$",  # 类别词
    r"^\d{1,3}#?钢$",                 # 45钢、45#钢
    r"^\d{1,3}#$",                   # 45#
    r"^\d{4}(?:-T\d{1,3})?$",        # 6061-T6、7075-T651
    r"^(不锈钢|铝合金|铜合金|钛合金|镍基合金)[A-Z0-9\-]*$",
    r"^(INCONEL|MONEL|HASTELLOY)\d*[A-Z0-9\-]*$",
]

_MATERIAL_PLACEHOLDERS = ("不知道", "不详", "待定", "未知", "无材料", "N/A", "NONE")
_GENERIC_DIMENSION_TAGS = {
    "孔径", "直径", "半径", "壁厚", "厚度", "长度", "宽度", "高度", "深度",
    "间距", "圆角", "倒角", "尺寸", "外径", "内径",
    "孔直径", "轴直径", "轴径", "通孔直径", "螺钉规格", "硬度", "表面粗糙度",
}

_ERR_META = {
    "ERR-01": {"type": "尺寸矛盾", "severity": "高"},
    "ERR-06": {"type": "材料不明/矛盾", "severity": "中"},
    "ERR-08": {"type": "标题栏/明细栏错误", "severity": "高"},
}


def make_issue(err_id: str, message: str, location: str = "",
               suggestion: str = "", severity: Optional[str] = None) -> Dict[str, Any]:
    meta = _ERR_META.get(err_id, {"type": err_id, "severity": "中"})
    return {
        "err_id": err_id,
        "type": meta["type"],
        "severity": severity or meta["severity"],
        "message": message,
        "location": location,
        "suggestion": suggestion,
    }


def _brand_valid(brand: str) -> bool:
    text = re.sub(r"\s+", "", str(brand or ""))
    if not text:
        return False
    upper = text.upper()
    if any(marker in upper for marker in _MATERIAL_PLACEHOLDERS):
        return False
    if any(re.match(p, text, re.IGNORECASE) for p in _MATERIAL_BRAND_PATTERNS):
        return True
    # 组合材料/标准写法由数字、字母、中文材料名及工程分隔符组成时只做格式放行；
    # 是否符合具体标准交给企业材料库或人工复核，避免规则层无依据地断言无效。
    return bool(re.fullmatch(r"[A-Za-z0-9#./+\-（）()\u4e00-\u9fff]+", text))


def check_titleblock(title_fields: Dict[str, Any]) -> List[Dict[str, Any]]:
    """ERR-06 + ERR-08 标题栏部分。"""
    issues: List[Dict[str, Any]] = []
    material = str(title_fields.get("material") or "").strip()
    declared = title_fields.get("material_applicable")
    drawing_type = str(title_fields.get("drawing_type") or "unknown").lower()
    # An unsupported model flag alone cannot impose a material requirement
    # on an assembly drawing. Enterprise requirements are checked separately.
    applicable = (declared is True and drawing_type != 'assembly') or drawing_type == 'part'
    if not material and applicable:
        issues.append(make_issue("ERR-06", "标题栏材料字段为空",
                                 location="标题栏-材料栏",
                                 suggestion="补填材料牌号（须符合国标牌号体系）"))
    elif material and not _brand_valid(material):
        issues.append(make_issue("ERR-06", "材料填写疑似不规范: %r（未匹配常见国标牌号模式）" % material,
                                 location="标题栏-材料栏",
                                 suggestion="核对材料标准（GB/T 221 命名规则）或确认企业内部牌号"))
    for field in REQUIRED_TITLE_FIELDS:
        if not str(title_fields.get(field) or "").strip():
            issues.append(make_issue("ERR-08", "标题栏必填字段缺失: %s" % field,
                                     location="标题栏",
                                     suggestion="按企业制图规范补全标题栏"))
    return issues


def _is_standard_reference(part_number: str) -> bool:
    """A standard identifies a family, not an individual drawing or part.

    Specifications may be embedded in the printed name or missing entirely.
    Neither an empty nor an equal specification proves that two rows are the
    same part (material, grade, finish and assembly context can also differ).
    """
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", part_number)).upper()
    return bool(re.match(
        r"^(?:GB|GJB|JB|HB|YB|HG|QJ|SJ|QC|YY|NB|DL|SY|SH|NY|JT|JC|TB|QB|FZ)"
        r"(?:/?[TZ])?[-—–]?[0-9]"
        r"|^(?:DIN|EN|ISO|IEC|BS|ASTM|ASME|ANSI|JIS)"
        r"(?:(?:DIN|EN|ISO|IEC)|[/.-])*[A-Z]{0,3}[0-9]", compact))


def check_bom_table(components: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ERR-08 明细栏部分：序号连续性、图号重复、数量缺失。"""
    issues: List[Dict[str, Any]] = []
    nos: List[int] = []
    seen_pn: Dict[Any, int] = {}
    for i, c in enumerate(components, start=1):
        no = _coerce_item_no(c.get("item_no"))
        if no is not None:
            nos.append(no)
        pn = str(c.get("part_number") or "").strip()
        if pn and not _is_standard_reference(pn):
            normalized_pn = re.sub(r"[\s\-_]", "", pn).upper()
            key = normalized_pn
            if key in seen_pn:
                issues.append(make_issue("ERR-08", "明细栏图号重复: %s（第 %d 项与第 %d 项）"
                                         % (pn, seen_pn[key], i),
                                         location="明细栏第 %d 行" % i,
                                         suggestion="核对是否图号笔误；仅在完整零件要求和装配归属一致时考虑合并明细行"))
            else:
                seen_pn[key] = i
        remark = str(c.get("remark") or "").strip()
        if c.get("quantity") in (None, "") and not explicit_non_numeric_quantity(remark):
            issues.append(make_issue("ERR-08", "明细栏第 %d 行数量缺失" % i,
                                     location="明细栏第 %d 行" % i))
        elif isinstance(c.get("quantity"), (int, float)) and c["quantity"] <= 0:
            issues.append(make_issue("ERR-08", "明细栏第 %d 行数量非正数" % i,
                                     location="明细栏第 %d 行" % i))
    if nos:
        duplicates = sorted(no for no, count in Counter(nos).items() if count > 1)
        missing = sorted(set(range(1, max(nos) + 1)) - set(nos)) if max(nos) > 0 else []
        if duplicates:
            issues.append(make_issue("ERR-08", "明细栏序号重复: %s" % duplicates[:20],
                                     location="明细栏", suggestion="核对重复序号对应行"))
        if missing:
            issues.append(make_issue("ERR-08", "明细栏序号不连续，缺少: %s" % missing[:20],
                                 location="明细栏",
                                 suggestion="核对是否存在漏行或序号笔误"))
    return issues


def check_dimensions(dimensions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ERR-01 数值比对部分：同一标记在不同视图数值不一致 / 同值不同标记的明显冲突。"""
    issues: List[Dict[str, Any]] = []
    by_tag = {}
    for index, d in enumerate(dimensions or []):
        tag = str(d.get("tag") or d.get("label") or "").strip()
        # feature_id/dimension_id 是跨视图关联的可靠键；只有通用语义名称时不强行关联。
        stable_id = str(d.get("feature_id") or d.get("dimension_id") or "").strip()
        # Semantic descriptions are not printed identifiers. Different shafts
        # and holes can legitimately share a compound description.
        printed_symbol = tag if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,15}',tag) and tag.lower() not in _GENERIC_DIMENSION_TAGS else ''
        group_key = (str(d.get('part_id') or ''), stable_id or printed_symbol, d.get('source_page') or 1)
        if stable_id or printed_symbol:
            by_tag.setdefault(group_key, []).append((index,d))
    for key, items in by_tag.items():
        tag = key[1]
        values = {_canonical_dimension(d) for _,d in items if d.get("value") not in (None, "")}
        if len(values) > 1:
            issue=make_issue(
                "ERR-01", "同一标记 %s 在不同位置数值不一致: %s"
                % (tag, " / ".join(sorted(values))),
                location="; ".join(str(d.get("view") or "") for _,d in items),
                suggestion="核对同一要素的原文与对应关系，不自动指定修改值")
            issue.update(dimension_indices=[index for index,_ in items], source_page=key[2],
                         evidence='；'.join(str(d.get('value')) for _,d in items),
                         bbox=next((d.get('bbox') for _,d in items if d.get('bbox')),None))
            issues.append(issue)
    return issues


def _canonical_dimension(d):
    text = re.sub(r"\s+", "", str(d.get("value", ""))).replace("φ", "Φ").replace("Ø", "Φ")
    fit = re.fullmatch(r'([ΦR]?\d+(?:\.\d+)?)(?:[A-Za-z]{1,2}\d{1,2})(?:/[A-Za-z]{1,2}\d{1,2})?',text)
    if fit:
        text=fit.group(1)  # Nominal size comparison; tolerance has its own checks.
    if re.fullmatch(r"[ΦR]?[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?:±\d+(?:\.\d+)?)?(?:[A-Za-zμ]+)?", text):
        text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    match = re.fullmatch(r"([ΦR]?)([+-]?\d+(?:\.\d+)?)(?:±(\d+(?:\.\d+)?))?(mm|cm|m|μm|um)?", text, re.IGNORECASE)
    if not match:
        return text
    prefix, value, tolerance, suffix = match.groups()
    unit = (suffix or str(d.get("unit") or "mm")).lower()
    factor = {"mm":Decimal(1), "cm":Decimal(10), "m":Decimal(1000), "μm":Decimal(".001"), "um":Decimal(".001")}.get(unit)
    if factor is None:
        return text + unit
    result = prefix + format((Decimal(value)*factor).normalize(), "f")
    if tolerance is not None:
        result += "±" + format((Decimal(tolerance)*factor).normalize(), "f")
    return result + "mm"


def check_balloon_consistency(balloons: List[Any], components: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ERR-08 引出序号 vs 明细栏序号对应检查。"""
    issues: List[Dict[str, Any]] = []
    balloon_set = set()
    for b in balloons or []:
        number = _coerce_item_no(b)
        if number is not None:
            balloon_set.add(number)
    comp_set = set()
    for c in components or []:
        number = _coerce_item_no(c.get("item_no"))
        if number is not None:
            comp_set.add(number)
    if not balloon_set or not comp_set:
        return issues  # 数据不全时不误报
    only_balloon = sorted(balloon_set - comp_set)
    only_comp = sorted(comp_set - balloon_set)
    if only_balloon:
        issues.append(make_issue("ERR-08", "图中有引出序号但明细栏缺失: %s" % only_balloon,
                                 location="图面/明细栏",
                                 suggestion="补全明细栏对应行或清理多余引出序号"))
    if only_comp:
        issues.append(make_issue("ERR-08", "明细栏有序号但图中无对应引出序号: %s" % only_comp,
                                 location="图面/明细栏",
                                 suggestion="检查引出序号是否漏标"))
    return issues


def _coerce_item_no(value: Any) -> Optional[int]:
    """接受 JSON 常见的 1、1.0、"1"、"1.0"，拒绝小数序号和布尔值。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number != number.to_integral_value():
        return None
    return int(number)


# 常用滚动轴承外径表（内径 = 末两位×5，00~03 查表）；未收录型号不参与校验
_BEARING_OD = {
    "6200": 30, "6201": 32, "6202": 35, "6203": 40, "6204": 47, "6205": 52,
    "6206": 62, "6207": 72, "6208": 80, "6209": 85, "6210": 90,
    "6300": 35, "6301": 37, "6302": 42, "6303": 47, "6304": 52, "6305": 62,
    "6306": 72, "6307": 80, "6308": 90, "7507": 72,
}
_BEARING_BORE_SPECIAL = {"00": 10, "01": 12, "02": 15, "03": 17}


def _bearing_models(components):
    """从明细栏提取轴承型号（如 6204 / 7507）。"""
    models, seen = [], set()
    for c in components or []:
        name = str(c.get("name_zh") or c.get("name_en") or "")
        m = re.search(r"轴承\s*([0-9]{4,5})", name)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            models.append(m.group(1))
    return models


def _bearing_expected_dims(model):
    """按型号推算（内径, 外径）名义值；无法推算的分量返回 None。"""
    digits = re.sub(r"\D", "", model)
    if len(digits) < 4:
        return None
    b2 = digits[-2:]
    if not b2.isdigit():
        return None
    bore = _BEARING_BORE_SPECIAL.get(b2, int(b2) * 5 if int(b2) > 0 else None)
    od = _BEARING_OD.get(digits[-4:])
    if bore is None:
        return None
    from decimal import Decimal as _D
    return (_D(bore), _D(od) if od is not None else None)


def check_bearing_fits(components, dimensions):
    """ERR-01 × ERR-07 交叉：明细栏轴承型号 ↔ 图面轴承位/座孔尺寸一致性。

    仅比较显式绑定的bearing_component_index及inner/outer配合界面，
    且必须有association_evidence。泛化标签、相邻型号和数值接近均不
    建立绑定；不能将端盖尺寸自动解释为某个轴承的座孔。
    """
    models = _bearing_models(components)
    if not models:
        return []
    expected = {}
    for model in models:
        dims_pair = _bearing_expected_dims(model)
        if dims_pair is not None:
            expected[model] = dims_pair
    if not expected:
        return []
    issues = []
    seat_dims = []
    for d in dimensions or []:
        tag = str(d.get("tag") or d.get("label") or "")
        ref=d.get('bearing_component_index')
        interface=d.get('bearing_interface')
        # A tag or nearest size does not bind a hole to a bearing. End-cover
        # spigots can be coaxial yet have a different diameter from its OD.
        if (type(ref) is not int or not 0<=ref<len(components) or interface not in ('inner','outer')
                or not isinstance(d.get('association_evidence'),str) or not d['association_evidence'].strip()):
            continue
        bound=_bearing_models([components[ref]])
        if len(bound)!=1 or bound[0] not in expected:continue
        m = re.search(r"(?:Φ|Ø|φ)?\s*(\d+(?:\.\d+)?)", str(d.get("value") or ""))
        if not m:
            continue
        try:
            from decimal import Decimal as _D
            seat_dims.append((_D(m.group(1)), d, tag,bound[0],interface))
        except Exception:
            continue
    if not seat_dims:
        return []
    for nominal, d, tag, model, interface in seat_dims:
        val=expected[model][0 if interface=='inner' else 1]
        if val is None or nominal==val:
            continue
        issue=make_issue('ERR-01','轴承直接配合尺寸疑似错误: %s 处标注 %s mm，但所关联轴承 %s 的%s名义尺寸应为 %s mm；需核对尺寸读数与实际关联'%(
            tag,nominal,model,'内径' if interface=='inner' else '外径',val),location=str(d.get('view') or ''),
            suggestion='核对具体轴承型号、直接配合面及标准外形尺寸，不能用同轴相邻关系替代直接配合证据')
        issue.update(evidence=d['association_evidence'],bbox=d.get('bbox'),source_page=d.get('source_page'))
        issues.append(issue)
    return issues


def run_all_checks(title_fields: Optional[Dict[str, Any]] = None,
                   components: Optional[List[Dict[str, Any]]] = None,
                   dimensions: Optional[List[Dict[str, Any]]] = None,
                   balloons: Optional[List[Any]] = None,
                   check_balloons: bool = True) -> List[Dict[str, Any]]:
    """汇总执行全部已实现规则，返回问题清单（未提供的数据项自动跳过）。"""
    issues: List[Dict[str, Any]] = []
    if title_fields is not None:
        issues += check_titleblock(title_fields)
    if components is not None:
        issues += check_bom_table(components)
        if check_balloons:
            issues += check_balloon_consistency(balloons or [], components)
    if dimensions is not None:
        issues += check_dimensions(dimensions)
        issues += check_bearing_fits(components or [], dimensions)
    return issues
