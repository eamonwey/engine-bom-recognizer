"""Checks on source-grounded observations; never a whole-drawing compliance verdict.

Numeric checks are exact Decimal arithmetic. Visual associations remain model
observations and require human review. Standards tables are supplied with a source,
not reconstructed by a language model or inferred from a tolerance letter.
"""
import json
import os
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

CODES = ('ERR-03', 'ERR-04', 'ERR-05', 'ERR-07', 'ERR-09', 'ERR-10')
RULE_BASES = {
    'ERR-03': '原文格式解析及极限尺寸区间算术；公差代号查表只使用有来源的配置表。',
    'ERR-04': '有限的形位项目/基准关系校验；参考NIST https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=910523 ，不是GB/T 1182完整条款验收。',
    'ERR-05': '具有同零件同要素对应证据的等价标注数值比较；不重建三维几何。',
    'ERR-07': '标准状态快照、已配置规格表及占用/容纳尺寸区间比较。',
    'ERR-09': '有适用性证据的企业规则匹配、原文占位/区间检查及标准快照。',
    'ERR-10': '比例正数/企业允许列表及原始PDF页面框；不验证实际绘图比例、CAD图层、字号或线型。'
}
GROUPS = ('fits', 'datums', 'gdt', 'view_features', 'standard_references',
          'technical_requirements', 'requirement_applicability', 'fastener_spaces')
NAMES = dict(zip(CODES, ('公差错误', '形位公差错误', '视图不一致',
                         '标准件/通用件错误', '技术要求缺失/不规范', '图纸格式/规范错误')))

OBSERVATION_PROMPT = '''
另外必须返回 engineering_observations 对象，包含下述八个数组（未观察到填[]；不能读清的事实readable=false，不能编造）。
每条事实包含id（组内唯一）、source_page（原图1起始）、bbox（整页0..1或null）、location、evidence（原文及其几何位置）、readable（bool）。
fits: hole_dimension_index/shaft_dimension_index（输入dimensions的0基下标）、intended_fit（仅照录图上明确的间隙/过渡/过盈要求，否则null）。不得用公差代号猜极限偏差。
datums: label（A/B等原图基准字母）、part_id（所属零件图号或空）、feature_id（有证据时填写同一几何要素的稳定ID，否则空）。
gdt: cells（从左到右照录框格各单元字符串，如["垂直度","0.02","A"]），part_id（所属零件图号或空）、feature_kind（plane/cylindrical_surface/axis/line/unknown），feature_id。
view_features: feature_id（仅有明确图面对应证据时）、view、kind（dimension/hole_count）、value（原文）、unit、part_id（同一零件的图号或明确的独立分区编号；无法确认则null）、association_evidence（解释为何两视图是同一几何特征）、comparable（bool，非投影缩短/隐藏/重复阵列的等价标注才true）。
每个视图必须单独返回一条view_features，禁止把“主视图;剖视图”合成一条。即使读数相同也保留两条。如图面明确标有P003独立分区，则两条part_id都照录P003；禁止关联到P001。
comparable表示几何对应可比较，不是“数值相等”。同一孔在两个视图分别标不同直径时仍应true，差值由规则发现。若false，必须另填exclusion_reason，说明投影缩短、遮挡或无法确认对应的具体证据；不能以数值不同作为不可比较原因。
示例：[{"id":"v1","part_id":"EX-PART","feature_id":"EX-HOLE","view":"主视图","kind":"dimension","value":"Φ8","unit":"mm","source_page":1,"evidence":"EX-PART主视图孔标识EX-HOLE，直径Φ8","location":"EX-PART主视图","bbox":null,"readable":true,"association_evidence":"原图两视图相同孔标识EX-HOLE且同属EX-PART","comparable":true},{"id":"v2","part_id":"EX-PART","feature_id":"EX-HOLE","view":"局部视图","kind":"dimension","value":"Φ8","unit":"mm","source_page":1,"evidence":"EX-PART局部视图孔标识EX-HOLE，直径Φ8","location":"EX-PART局部视图","bbox":null,"readable":true,"association_evidence":"原图两视图相同孔标识EX-HOLE且同属EX-PART","comparable":true}]。例中数值仅演示结构，必须按实际图面读数填写，不得复制示例数值。
standard_references: reference（完整标准号，保留年份）、usage（standard_part/technical_requirement）、component_index（BOM0基下标或null）。
technical_requirements: text（逐条原文）、topic、part_id；只照录，不能把模型建议当原文。
requirement_applicability: rule_id（来自enterprise_required_annotations）、part_id（适用零件图号或空）、applies（true/false/null）、evidence（本图适用或不确定的证据）。
fastener_spaces: kind（diametral_clearance/blind_hole_depth）、fastener_dimension_index、space_dimension_index（dimensions下标）、blind_hole（bool）；只在头部外径和容纳孔径、或螺钉有效伸入长度和盲孔有效深度的图面对应明确时填写，禁止用整根螺钉长度替代伸入长度。
公差原值应在dimensions.value保留：对称±、上下偏差用如"Φ20 +0.02/-0.01"，极限尺寸用如"20.02/19.98"；不得为了让规则通过而改原值。
形位公差不要一律要求基准：平面度/圆度等形状公差通常无需基准，位置度/轮廓度存在无基准情形；复合框格/修饰符不理解时保持原文待核实。
cells中的空白框格必须照录空字符串，不得把框格外的基准符号搬进空白框格。框格引线指向哪个表面要独立追踪，不能因基准A存在就将被测要素也命名为A或同一feature_id。
ERR-05不能把不同零件的同名孔比较，也不能依据透视图轮廓长度测量数值。缺少剖视图只能给人工建议，不能无适用依据断言错误。
ERR-07/09禁止自行判断标准时效，以程序的有来源标准快照为准。热处理、涂层、检验等要求只有企业规则明确适用时才检查缺失。
ERR-10禁止根据像素比例断言图幅、线宽、字号、CAD图层不合规；多个局部视图可以采用不同的明确比例。
'''


def text(value):
    return unicodedata.normalize('NFKC', str(value or '')).replace('−', '-').replace('–', '-').replace('×', 'x')


def number(value):
    if isinstance(value, bool):
        raise ValueError('布尔值不是数值')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('数值无法解析')
    if not result.is_finite():
        raise ValueError('数值必须有限')
    if abs(result) > Decimal('1e12') or result and abs(result) < Decimal('1e-12'):
        raise ValueError('数值超出本模块支持范围')
    return result


def observation_template():
    """Shape guide, deliberately invalid until filled from the actual source."""
    fields = {
        'fits': {'hole_dimension_index':None,'shaft_dimension_index':None,'intended_fit':None},
        'datums': {'label':'','part_id':None,'feature_id':''},
        'gdt': {'cells':[],'part_id':None,'feature_kind':'unknown','feature_id':''},
        'view_features': {'part_id':None,'feature_id':'','view':'','kind':'dimension','value':'','unit':'',
                          'association_evidence':'','comparable':False,'exclusion_reason':''},
        'standard_references': {'reference':'','usage':'standard_part','component_index':None},
        'technical_requirements': {'text':'','topic':'','part_id':None},
        'requirement_applicability': {'rule_id':'','part_id':None,'applies':None},
        'fastener_spaces': {'kind':'diametral_clearance','fastener_dimension_index':None,'space_dimension_index':None,'blind_hole':False}
    }
    common = {'id':'','source_page':None,'bbox':None,'location':'','evidence':'','readable':None}
    return {'engineering_observations':{key:[dict(common,**value)] for key,value in fields.items()}}


NUM = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'
BANDS = {'A', 'B', 'C', 'CD', 'D', 'E', 'EF', 'F', 'FG', 'G', 'H', 'J', 'JS',
         'K', 'M', 'N', 'P', 'R', 'S', 'T', 'U', 'V', 'X', 'Y', 'Z', 'ZA', 'ZB', 'ZC'}


def parse_size(value, unit='mm', *, allow_signed_limits=False):
    """Parse only unambiguous literal sizes, not model-supplied numeric guesses."""
    raw = re.sub(r'\s+', '', text(value)).replace('φ', 'Φ').replace('Ø', 'Φ').replace('⌀', 'Φ')
    suffix = re.search(r'(mm|cm|μm|um|m)$', raw)
    declared = str(unit or '').lower()
    if suffix and declared and suffix[1] != declared:
        raise ValueError('标注单位与字段单位矛盾')
    effective = suffix[1] if suffix else declared
    factor = {'mm': Decimal(1), 'cm': Decimal(10), 'm': Decimal(1000),
              'um': Decimal('.001'), 'μm': Decimal('.001'), '': Decimal(1)}.get(effective)
    if factor is None:
        raise ValueError('不支持的尺寸单位')
    if suffix:
        raw = raw[:suffix.start()]
    kind = 'diameter' if raw.startswith('Φ') else 'radius' if raw.startswith('R') else 'linear'
    raw = re.sub(r'^[ΦR]', '', raw)
    explicit_limits = True
    nominal, lower, upper, band = None, None, None, None
    band_hole = band_shaft = None
    match = re.fullmatch('(' + NUM + r')±(' + NUM + ')', raw)
    if match:
        nominal, delta = number(match[1]), number(match[2])
        if delta < 0:
            raise ValueError('±公差幅值为负数')
        lower, upper = nominal-delta, nominal+delta
    else:
        match = re.fullmatch('(' + NUM + r')([+-](?:\d+(?:\.\d*)?|\.\d+))/((' + NUM + '))', raw)
        if match:
            nominal, hi, lo = number(match[1]), number(match[2]), number(match[3])
            if hi < lo:
                raise ValueError('上偏差小于下偏差')
            lower, upper = nominal+lo, nominal+hi
        else:
            match = re.fullmatch('(' + NUM + ')/(' + NUM + ')', raw)
            if match:
                upper, lower = number(match[1]), number(match[2])
                if upper < lower:
                    raise ValueError('上极限尺寸小于下极限尺寸')
            else:
                match = re.fullmatch('(' + NUM + r')([A-Za-z]{1,2})(01|0|[1-9]|1[0-8])', raw)
                if match:
                    nominal, band = number(match[1]), match[2]+match[3]
                    if match[2].upper() not in BANDS or not (match[2].isupper() or match[2].islower()):
                        raise ValueError('公差带字母无法按支持的ISO代号解析')
                elif re.fullmatch('(' + NUM + r')([A-Za-z]{1,2})(01|0|[1-9]|1[0-8])'
                                  r'/([A-Za-z]{1,2})(01|0|[1-9]|1[0-8])', raw):
                    # 国标合并式配合标注（如 Ø62 H9/h9）：一条尺寸同时标注孔/轴公差带，
                    # size(…, role) 按孔/轴角色分别取用对应公差带
                    m2 = re.fullmatch('(' + NUM + r')([A-Za-z]{1,2})(01|0|[1-9]|1[0-8])'
                                      r'/([A-Za-z]{1,2})(01|0|[1-9]|1[0-8])', raw)
                    if (m2[2].upper() not in BANDS or m2[4].upper() not in BANDS
                            or not m2[2].isupper() or not m2[4].islower()):
                        raise ValueError('合并式配合标注的孔/轴公差带大小写无法区分')
                    nominal = number(m2[1])
                    band = m2[2] + m2[3]
                    band_hole, band_shaft = band, m2[4] + m2[5]
                elif re.fullmatch(NUM, raw):
                    nominal = lower = upper = number(raw)
                    explicit_limits = False
                else:
                    raise ValueError('尺寸标注无法按支持的格式解析')
    # Signed limits are only for a closing clearance/interference requirement,
    # never for an ordinary physical component length or a fit diameter.
    if not allow_signed_limits and (nominal is not None and nominal <= 0 or lower is not None and lower < 0):
        raise ValueError('尺寸或下极限非物理有效值')
    return {'nominal': nominal*factor if nominal is not None else None,
            'lower': lower*factor if lower is not None else None,
            'upper': upper*factor if upper is not None else None, 'band': band,
            'band_hole': band_hole, 'band_shaft': band_shaft,
            'unit_known': bool(effective), 'unit': effective, 'kind': kind,
            'explicit_limits': explicit_limits}


def validate_observations(data, pages, dimensions, components, quarantine_invalid=True):
    if not isinstance(data, dict):
        return ['engineering_observations 必须为对象']
    errors = []
    for group in GROUPS:
        rows = data.get(group)
        if not isinstance(rows, list) or len(rows) > 1000:
            errors.append(group + ' 必须为不超过1000条的数组')
            continue
        seen = set()
        kept_rows = []
        for i, row in enumerate(rows):
            prefix = '%s[%d]: ' % (group, i)
            if not isinstance(row, dict):
                if quarantine_invalid:
                    data.setdefault('quarantined', []).append({'group':group,'index':i,'reasons':[prefix+'事实必须为对象']})
                else:
                    errors.append(prefix+'事实必须为对象')
                continue
            row_errors = []
            def _row_error(msg):
                row_errors.append(prefix + msg)
            ident = row.get('id')
            if not isinstance(ident, str) or not ident.strip() or ident in seen:
                _row_error('id必须非空且组内唯一')
            else:
                seen.add(ident)
            if type(row.get('source_page')) is not int or not 1 <= row['source_page'] <= pages:
                _row_error('原图页码无效')
            if not isinstance(row.get('evidence'), str) or not row['evidence'].strip():
                _row_error('缺少原图证据')
            if type(row.get('readable')) is not bool:
                _row_error('readable必须为bool')
            box = row.get('bbox')
            if box is not None and not (isinstance(box, list) and len(box) == 4 and
                    all(type(v) in (int, float) and 0 <= v <= 1 for v in box) and
                    box[0] < box[2] and box[1] < box[3]):
                _row_error('bbox无效')
            fields = {'fits': ('hole_dimension_index', 'shaft_dimension_index'),
                      'fastener_spaces': ('fastener_dimension_index', 'space_dimension_index')}.get(group, ())
            for field in fields:
                idx = row.get(field)
                if type(idx) is not int or not 0 <= idx < len(dimensions):
                    _row_error(field + '越界')
            if (fields and all(type(row.get(f)) is int for f in fields) and row[fields[0]] == row[fields[1]]
                    and group == 'fits' and _combined_fit_annotation(dimensions, row[fields[0]])):
                pass  # 国标合并式配合标注（如 Ø62 H9/h9）：孔轴公差合写在一条尺寸上，属合法引用
            elif fields and all(type(row.get(f)) is int for f in fields) and row[fields[0]] == row[fields[1]]:
                _row_error('不能引用同一尺寸比较')
            if group == 'gdt' and (not isinstance(row.get('cells'), list) or not row['cells'] or
                                  any(not isinstance(c, str) for c in row['cells'])):
                _row_error('cells必须为原文字符串数组')
            string_fields = {'datums': ('label',), 'view_features': ('feature_id','view','kind','value','association_evidence'),
                             'technical_requirements': ('text',), 'standard_references': ('reference',),
                             'requirement_applicability': ('rule_id',), 'fastener_spaces': ('kind',)}.get(group, ())
            for field in string_fields:
                if not isinstance(row.get(field), str):
                    _row_error(field + '必须为原文字符串')
            for field in ('part_id', 'feature_id', 'feature_kind', 'intended_fit'):
                if field in row and row[field] is not None and not isinstance(row[field], str):
                    _row_error(field + '必须为字符串或null')
            if group == 'view_features' and type(row.get('comparable')) is not bool:
                _row_error('comparable必须为bool')
            if group == 'view_features' and row.get('comparable') is False and not str(row.get('exclusion_reason') or '').strip():
                _row_error('comparable=false必须提供exclusion_reason：说明投影缩短/遮挡/对应不明的具体证据；同一要素不同数值仍可比较')
            if group == 'view_features' and row.get('kind') == 'dimension' and not isinstance(row.get('unit'),str):
                _row_error('尺寸unit必须为字符串')
            if group == 'standard_references':
                idx = row.get('component_index')
                if idx is not None and (type(idx) is not int or not 0 <= idx < len(components)):
                    _row_error('component_index越界')
                if row.get('usage') not in ('standard_part', 'technical_requirement'):
                    _row_error('usage无效')
            if group == 'requirement_applicability' and row.get('applies') is not None and type(row['applies']) is not bool:
                _row_error('applies必须为bool或null')
            if row_errors:
                # 逐条隔离：坏行丢弃并记录告警，不让一条坏事实连坐整批有效事实
                if quarantine_invalid:
                    data.setdefault('quarantined', []).append({'group':group,'index':i,'reasons':row_errors})
                else:
                    errors.extend(row_errors)
                continue
            kept_rows.append(row)
        if quarantine_invalid:
            data[group] = kept_rows
    if quarantine_invalid and data.get('quarantined') and not any(data.get(g) for g in GROUPS):
        errors.append('全部专项事实无效；不能把隔离后的空结果当作成功提取')
    return errors


def _combined_fit_annotation(dimensions, idx):
    """国标合并式配合标注（如 Ø62 H9/h9）：孔轴公差合写在同一条尺寸上。"""
    if type(idx) is not int or not 0 <= idx < len(dimensions or []):
        return False
    raw = re.sub(r'\s+', '', str((dimensions[idx] or {}).get('value') or ''))
    raw = raw.replace('φ', 'Φ').replace('Ø', 'Φ').replace('⌀', 'Φ')
    return bool(re.fullmatch(r'Φ?\d+(?:\.\d+)?[A-Z]{1,2}\d{1,2}/[a-z]{1,2}\d{1,2}', raw))


def standard_key(ref):
    return re.sub(r'\s+', '', text(ref)).upper().replace('—', '-')


def load_catalog():
    path = os.path.join(os.path.dirname(__file__), 'standards_snapshot.json')
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def validate_engineering_config(config, strict=False):
    """Reject ambiguous imported tables before they can drive a finding."""
    if not isinstance(config, dict):
        raise ValueError('inspection_rules必须为对象')
    if strict and set(config) - {'tolerance_bands','standards','format_policy'}:
        raise ValueError('inspection_rules仅支持tolerance_bands、standards、format_policy，不能覆盖模型检查开关或页码')
    tables = config.get('tolerance_bands', [])
    if not isinstance(tables, list):
        raise ValueError('tolerance_bands必须为数组')
    seen = []
    for row in tables:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip() for k in ('band', 'source')):
            raise ValueError('公差带表必须包含band和可追溯source')
        if not re.fullmatch(r'[A-Za-z]{1,2}(?:01|0|[1-9]|1[0-8])', row['band']):
            raise ValueError('公差带表band格式错误')
        low, high = number(row.get('min_exclusive')), number(row.get('max_inclusive'))
        lo, hi = number(row.get('lower_mm')), number(row.get('upper_mm'))
        if low < 0 or high <= low or hi < lo:
            raise ValueError('公差带表尺寸区间/上下偏差无效（单位mm）')
        if any(band == row['band'] and max(low,a) < min(high,b) for band,a,b in seen):
            raise ValueError('同一公差带表区间不能重叠')
        seen.append((row['band'], low, high))
    standards = config.get('standards', [])
    if not isinstance(standards, list):
        raise ValueError('standards必须为数组')
    keys = set()
    for row in standards:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip() for k in ('reference','source','checked_on')):
            raise ValueError('标准状态必须包含reference、source、checked_on')
        if row.get('status') not in ('current','replaced') or (row.get('status') == 'replaced' and not row.get('replacement')):
            raise ValueError('标准状态或替代版本无效')
        try:
            date.fromisoformat(row['checked_on'])
        except ValueError:
            raise ValueError('checked_on必须为YYYY-MM-DD')
        key = standard_key(row['reference'])
        if key in keys:
            raise ValueError('标准状态reference重复')
        keys.add(key)
        for field in ('allowed_specifications', 'incompatible_name_terms'):
            items = row.get(field, [])
            if not isinstance(items, list) or any(not isinstance(v,str) or not v.strip() for v in items):
                raise ValueError(field + '必须为非空字符串组成的数组')
    policy = config.get('format_policy', {})
    if not isinstance(policy, dict):
        raise ValueError('format_policy必须为对象')
    if policy and not (isinstance(policy.get('source'),str) and policy['source'].strip()):
        raise ValueError('图纸格式策略必须有适用标准/企业source')
    scales = policy.get('allowed_scales', [])
    if not isinstance(scales, list):
        raise ValueError('allowed_scales必须为数组')
    for value in scales:
        if not isinstance(value,str) or not re.fullmatch(r'\d+(?:\.\d+)?:\d+(?:\.\d+)?',value) or any(number(n) <= 0 for n in value.split(':')):
            raise ValueError('允许比例必须为正数a:b')
    sheets = policy.get('allowed_sheets', [])
    if not isinstance(sheets,list) or any(v not in ('A0','A1','A2','A3','A4') for v in sheets):
        raise ValueError('allowed_sheets当前仅支持基本A0-A4图幅')
    return config


def inspection_config(config, file_path, title_fields=None):
    """Common setup for combined BOM and standalone inspection routes."""
    result = dict(config.get('inspection') or {})
    enterprise = config.get('enterprise') or {}
    result.update(validate_engineering_config(enterprise.get('inspection_rules') or {}, strict=True))
    result['required_annotations'] = enterprise.get('required_annotations', [])
    result['check_balloons'] = bool((config.get('recognition') or {}).get('preserve_printed_rows', True))
    result['title_source_page'] = (title_fields or {}).get('source_page')
    result['page_metadata'] = []
    if str(file_path).lower().endswith('.pdf'):
        import fitz
        with fitz.open(file_path) as doc:
            for i, page in enumerate(doc):
                result['page_metadata'].append({'source_page': i+1, 'kind':'pdf',
                    'width_mm': page.rect.width*25.4/72, 'height_mm': page.rect.height*25.4/72})
    else:
        result['page_metadata'] = [{'source_page': 1, 'kind':'raster_or_cad_render'}]
    return result


class Checker:
    def __init__(self, dimensions, components, title, config, metadata):
        self.dimensions, self.components, self.title = dimensions, components, title
        self.config, self.metadata = config or {}, metadata or []
        self.checks, self.issues = [], []
        self.catalog = load_catalog()
        self.standards = {standard_key(r['reference']): r for r in self.catalog['entries']}
        self.standards.update({standard_key(r['reference']): r for r in self.config.get('standards', [])})

    def record(self, code, rule, obs, message, state='checked', calculation=None):
        item = {'err_id': code, 'rule_id': rule, 'observation_id': obs.get('id'),
                'status': state, 'message': message, 'evidence': obs.get('evidence', ''),
                'source_page': obs.get('source_page'), 'bbox': obs.get('bbox'),
                'location': obs.get('location', ''), 'calculation': calculation,
                'rule_basis': RULE_BASES[code]}
        self.checks.append(item)
        if state == 'issue':
            self.issues.append(dict(item, type=NAMES[code], severity='中',
                origin='engineering_rule', status='needs_review',
                finding_id='engineering-%d' % len(self.issues),
                message=message, suggestion='对照原图及适用标准核实标注与提取结果；确认后修订，不自动猜测正确值。'))

    def size(self, idx, role=None, *, allow_signed_limits=False):
        dim = self.dimensions[idx]
        parsed = parse_size(dim.get('value'), dim.get('unit') or '', allow_signed_limits=allow_signed_limits)
        band = parsed['band']
        if role and parsed.get('band_hole'):  # 合并式配合标注：孔取大写带，轴取小写带
            band = parsed['band_hole'] if role == 'hole' else parsed.get('band_shaft')
        if band and role and band[0].isupper() != (role == 'hole'):
            raise ValueError('明确孔/轴角色与公差带大小写不符')
        if band:
            nominal = parsed['nominal']
            matches = [r for r in self.config.get('tolerance_bands', [])
                       if r['band'] == band and number(r['min_exclusive']) < nominal <= number(r['max_inclusive'])]
            if len(matches) > 1:
                raise ValueError('公差带表区间重叠，无法唯一查表')
            if matches:
                row = matches[0]
                parsed.update(lower=nominal+number(row['lower_mm']), upper=nominal+number(row['upper_mm']))
        return parsed

    def tolerances(self, facts):
        for idx, dim in enumerate(self.dimensions):
            raw = text(dim.get('value'))
            if not ('±' in raw or re.search(r'\d\s*[A-Za-z]{1,2}\d', raw) or re.search(r'\d\s*[+-].*/', raw) or '/' in raw):
                continue
            obs = dict(dim, id='dimension-%d' % idx, evidence=str(dim.get('value', '')), location=dim.get('view', ''))
            if type(dim.get('source_page')) is not int or dim['source_page'] < 1 or not dim.get('value'):
                self.record('ERR-03', 'tolerance-format', obs, '公差缺少来源页或原文', 'uncertain')
                continue
            try:
                closing = dim.get('dimension_role') == 'closing_requirement' and isinstance(dim.get('role_evidence'),str) and bool(dim['role_evidence'].strip())
                size = self.size(idx, allow_signed_limits=closing)
                if closing and size['kind'] != 'linear':
                    raise ValueError('封闭环功能要求须为线性间隙或游隙，不能用于直径/半径')
                self.record('ERR-03', 'tolerance-format', obs, '支持的公差格式已解析；不代表公差选值合理')
                if size['band'] and size['lower'] is None:
                    self.record('ERR-03', 'tolerance-table', obs, '缺少有来源的公差带极限偏差表，未判断配合合理性', 'uncertain')
            except ValueError as exc:
                # Unsupported notation is not proof of a design defect.
                state = 'issue' if any(s in str(exc) for s in ('为负', '小于', '非物理', '大小写不符')) else 'uncertain'
                self.record('ERR-03', 'tolerance-format', obs, str(exc), state)
        aliases = {'间隙': 'clearance', '间隙配合': 'clearance', '过盈': 'interference', '过盈配合': 'interference',
                   '过渡': 'transition', '过渡配合': 'transition'}
        for obs in facts['fits']:
            if not obs['readable']:
                self.record('ERR-03', 'fit-interval', obs, '配合原文读不清', 'uncertain')
                continue
            try:
                hole, shaft = self.size(obs['hole_dimension_index'], 'hole'), self.size(obs['shaft_dimension_index'], 'shaft')
                if not hole['unit_known'] or not shaft['unit_known']:
                    raise ValueError('配合尺寸单位不明确')
                if not hole['explicit_limits'] or not shaft['explicit_limits']:
                    raise ValueError('配合尺寸未明确公差，不能把未注公差当零公差')
                if hole['kind'] == 'radius' or shaft['kind'] == 'radius':
                    raise ValueError('半径不能作为孔轴配合直径计算')
                if hole['nominal'] is not None and shaft['nominal'] is not None and hole['nominal'] != shaft['nominal']:
                    raise ValueError('孔轴公称尺寸不同，需确认对应关系')
                if any(d[k] is None for d in (hole, shaft) for k in ('lower', 'upper')):
                    raise ValueError('缺少有来源的极限偏差表')
                low, high = hole['lower']-shaft['upper'], hole['upper']-shaft['lower']
                # Zero lies at the boundary, not a guarantee of assembly force.
                actual = 'clearance' if low >= 0 else 'interference' if high <= 0 else 'transition'
                expected = aliases.get(obs.get('intended_fit'), obs.get('intended_fit'))
                fit_names = {'clearance':'间隙配合', 'interference':'过盈配合', 'transition':'过渡配合'}
                calculation = {'clearance_min_mm': str(low), 'clearance_max_mm': str(high), 'computed_fit': actual}
                self.record('ERR-03', 'fit-interval', obs,
                    '孔轴极限尺寸计算为%s；图纸明确要求%s' % (fit_names[actual], fit_names.get(expected,expected) or '未给出'),
                    'issue' if expected in ('clearance', 'interference', 'transition') and expected != actual else 'checked', calculation)
            except ValueError as exc:
                self.record('ERR-03', 'fit-interval', obs, str(exc), 'issue' if '大小写不符' in str(exc) else 'uncertain')

    def geometric(self, facts):
        symbols = {'⏥': 'flatness', '平面度': 'flatness', '○': 'roundness', '圆度': 'roundness',
                   '⌭': 'cylindricity', '圆柱度': 'cylindricity', '直线度': 'straightness', '—': 'straightness',
                   '∥': 'parallelism', '//': 'parallelism', '平行度': 'parallelism', '⊥': 'perpendicularity',
                   '垂直度': 'perpendicularity', '∠': 'angularity', '倾斜度': 'angularity',
                   '位置度': 'position', '⌖': 'position', '同轴度': 'coaxiality', '对称度': 'symmetry',
                   '圆跳动': 'circular_runout', '全跳动': 'total_runout'}
        required = {'parallelism', 'perpendicularity', 'angularity', 'coaxiality', 'symmetry', 'circular_runout', 'total_runout'}
        form = {'flatness', 'roundness', 'cylindricity', 'straightness'}
        datums = [r for r in facts['datums'] if r['readable']]
        for obs in facts['gdt']:
            cells = obs['cells']
            if not obs['readable'] or len(cells) < 2:
                self.record('ERR-04', 'gdt-frame', obs, '框格原文不完整或读不清', 'uncertain')
                continue
            kind = symbols.get(cells[0].strip(), cells[0].strip().lower())
            if kind not in required | form | {'position', 'profile_line', 'profile_surface'}:
                self.record('ERR-04', 'gdt-frame', obs, '尚不支持的形位项目或符号，需核实', 'uncertain')
                continue
            tolerance = re.fullmatch(r'[ΦφØ⌀]?(' + NUM + r')\s*(mm)?\s*([ⓂⓁ]?)', cells[1].strip())
            if not tolerance:
                self.record('ERR-04', 'gdt-value', obs, '复杂修饰符或公差值无法解析', 'uncertain')
            elif number(tolerance[1]) < 0:
                self.record('ERR-04', 'gdt-value', obs, '形位公差值为负数', 'issue')
            else:
                self.record('ERR-04', 'gdt-value', obs, '框格数值已解析；零公差与材料条件须结合设计复核')
            refs = []
            complex_refs = False
            for cell in cells[2:]:
                if not cell.strip():
                    continue
                cleaned = re.sub(r'[ⓂⓁⓇ\s]', '', cell)
                if not re.fullmatch(r'[A-Z](?:-[A-Z])*', cleaned):
                    complex_refs = True
                    continue
                refs.extend(cleaned.split('-'))
            if complex_refs:
                self.record('ERR-04', 'gdt-datum', obs, '复合框格或基准修饰符尚不能完整解析', 'uncertain')
            elif kind in required and not refs:
                self.record('ERR-04', 'gdt-datum', obs, '该方向/位置/跳动项目的已读框格未见所需基准，须核实完整框格', 'issue')
            elif kind in form and refs:
                self.record('ERR-04', 'gdt-datum', obs, '形状公差框格引用了基准，须核实项目是否误读', 'issue')
            else:
                self.record('ERR-04', 'gdt-datum', obs, '基准要求按项目区分，未一律要求位置度/轮廓度带基准')
            for ref in refs:
                candidates = [r for r in datums if str(r.get('label') or '').strip() == ref and
                              (not obs.get('part_id') or r.get('part_id') == obs['part_id'])]
                datum = candidates[0] if len(candidates) == 1 else None
                if datum is None:
                    self.record('ERR-04', 'gdt-reference', obs, '基准%s未在已识别的基准清单中找到；不代表图纸缺失' % ref, 'uncertain')
                elif obs.get('feature_id') and datum.get('feature_id') == obs['feature_id']:
                    self.record('ERR-04', 'gdt-reference', obs, '被测要素与基准%s被关联为同一要素，需核实是否自引用' % ref, 'issue')
                else:
                    self.record('ERR-04', 'gdt-reference', obs, '基准%s在原图识别清单中有对应证据' % ref)
            incompatible = ((kind == 'flatness' and obs.get('feature_kind') == 'cylindrical_surface') or
                            (kind in ('roundness', 'cylindricity') and obs.get('feature_kind') == 'plane'))
            if incompatible:
                self.record('ERR-04', 'gdt-feature', obs, '形位项目与识别的被测表面类型不匹配', 'issue')

    def views(self, facts):
        groups = {}
        for obs in facts['view_features']:
            if self.config.get('dimension_links') and obs.get('kind')=='dimension':
                self.record('ERR-05','view-correspondence',obs,'尺寸跨视图对应须经独立定位和局部复核；不以相同语义名称或模型comparable声明代替对应证据','uncertain')
                continue
            if not obs['readable'] or obs.get('comparable') is not True or not all(obs.get(k) for k in ('part_id', 'feature_id', 'view', 'association_evidence')):
                self.record('ERR-05', 'view-correspondence', obs, '缺少同零件同要素的等价标注对应证据', 'uncertain')
                continue
            groups.setdefault((obs['part_id'], obs['feature_id'], obs.get('kind')), []).append(obs)
        for (_, _, kind), rows in groups.items():
            if len({r['view'] for r in rows}) < 2:
                self.record('ERR-05', 'view-correspondence', rows[0], '只有一个对应视图，未作跨视图一致性判断', 'uncertain')
                continue
            try:
                if kind == 'hole_count':
                    values = [number(r.get('value')) for r in rows]
                    if any(v < 0 or v != v.to_integral_value() for v in values):
                        raise ValueError('孔数必须为非负整数原文')
                elif kind == 'dimension':
                    parsed = [parse_size(r.get('value'), r.get('unit') or '') for r in rows]
                    if any(not r['unit_known'] or r['nominal'] is None for r in parsed):
                        raise ValueError('尺寸单位或公称值不明确')
                    if len({r['kind'] for r in parsed}) != 1:
                        raise ValueError('尺寸类型不同（半径/直径/线性），不能直接按同一标注比较')
                    values = [r['nominal'] for r in parsed]
                else:
                    raise ValueError('尚未支持的视图特征')
                self.record('ERR-05', 'view-equivalent-value', rows[0],
                    '同一要素跨视图%s：%s' % ('标注不一致' if len(set(values)) > 1 else '数值一致', ' / '.join(str(v) for v in values)),
                    'issue' if len(set(values)) > 1 else 'checked',
                    {'observations': [r['id'] for r in rows], 'views': [r['view'] for r in rows], 'values': [str(v) for v in values]})
            except ValueError as exc:
                self.record('ERR-05', 'view-equivalent-value', rows[0], str(exc), 'uncertain')

    def references(self, facts):
        for obs in facts['standard_references']:
            code = 'ERR-07' if obs['usage'] == 'standard_part' else 'ERR-09'
            entry = self.standards.get(standard_key(obs.get('reference')))
            if not obs['readable'] or entry is None:
                self.record(code, 'standard-lifecycle', obs, '未读清标准号或不在有来源的标准快照中；未判定有效/废止', 'uncertain')
                continue
            state = 'uncertain' if entry['status'] == 'replaced' else 'checked'
            message = '标准快照%s：%s；来源%s' % (entry['checked_on'], entry['status'], entry['source'])
            if entry['status'] == 'replaced':
                message += '；替代标准%s。历史图纸须按适用日期和合同核实，不能自动换版本。' % entry.get('replacement', '')
                # A documented replacement is a review finding, not a claim of illegality.
                state = 'issue'
            self.record(code, 'standard-lifecycle', obs, message, state,
                        {'reference': entry['reference'], 'snapshot_date': entry['checked_on'], 'source': entry['source']})
            idx = obs.get('component_index')
            if code == 'ERR-07' and type(idx) is int:
                component = self.components[idx]
                name = str(component.get('name_zh') or component.get('name_en') or '')
                if any(term in name for term in entry.get('incompatible_name_terms', [])):
                    self.record(code, 'standard-part-family', obs,
                        '明细名称%s与该标准的零件类别不匹配；依据%s' % (name,entry['source']), 'issue')
                allowed = entry.get('allowed_specifications', [])
                spec = str(component.get('specification') or '')
                if allowed:
                    normalized = lambda v: re.sub(r'\s+', '', text(v)).lower()
                    self.record(code, 'standard-specification-table', obs,
                        '规格原文缺失，无法查表' if not spec else '规格%s%s已配置的允许规格表；依据%s' %
                        (spec, '命中' if normalized(spec) in {normalized(v) for v in allowed} else '未命中',entry['source']),
                        'uncertain' if not spec else 'checked' if normalized(spec) in {normalized(v) for v in allowed} else 'issue')
        for i, component in enumerate(self.components):
            spec = text(component.get('specification') or '')
            match = re.search(r'\bM\s*(' + NUM + r')\s*x\s*(' + NUM + ')', spec, re.I)
            if match and (number(match[1]) <= 0 or number(match[2]) <= 0):
                obs = dict(component, id='component-%d' % i, evidence=spec, location='明细栏第%d行' % (i+1))
                if obs.get('source_page'):
                    self.record('ERR-07', 'fastener-specification', obs, '紧固件规格中的直径/长度或螺距为非正数', 'issue')
        for obs in facts['fastener_spaces']:
            if not obs['readable'] or obs.get('kind') not in ('diametral_clearance', 'blind_hole_depth'):
                self.record('ERR-07', 'fastener-space', obs, '安装空间关系不明确', 'uncertain')
                continue
            if obs['kind'] == 'blind_hole_depth' and obs.get('blind_hole') is not True:
                self.record('ERR-07', 'fastener-space', obs, '未确认盲孔及有效伸入长度，不比较螺钉长度和孔深', 'uncertain')
                continue
            try:
                bolt, space = self.size(obs['fastener_dimension_index']), self.size(obs['space_dimension_index'])
                if not bolt['unit_known'] or not space['unit_known'] or bolt['lower'] is None or space['upper'] is None:
                    raise ValueError('缺少明确单位或尺寸区间')
                definite = bolt['lower'] > space['upper']
                possible = bolt['upper'] > space['lower']
                self.record('ERR-07', 'fastener-space', obs,
                    '紧固件最小占用尺寸超过最大容纳尺寸' if definite else '尺寸区间有可能干涉，需复核配合' if possible else '该对尺寸未发现占用超过空间',
                    'issue' if definite else 'uncertain' if possible else 'checked',
                    {'fastener_min': str(bolt['lower']), 'fastener_max': str(bolt['upper']),
                     'space_min': str(space['lower']), 'space_max': str(space['upper'])})
            except ValueError as exc:
                self.record('ERR-07', 'fastener-space', obs, str(exc), 'uncertain')

    def requirements(self, facts):
        notes = [r for r in facts['technical_requirements'] if r['readable']]
        applicability = {r.get('rule_id'): r for r in facts['requirement_applicability'] if r['readable']}
        for rule in self.config.get('required_annotations', []):
            obs = applicability.get(rule['id'])
            if obs is None or obs.get('applies') is not True:
                self.record('ERR-09', 'required-' + rule['id'], obs or {'id': rule['id'], 'evidence': rule['applies_when']},
                    '规则适用性未确认' if obs is None or obs.get('applies') is None else '该企业要求在本图不适用',
                    'uncertain' if obs is None or obs.get('applies') is None else 'not_applicable')
                continue
            terms = rule.get('match_terms', [])
            if not terms:
                self.record('ERR-09', 'required-' + rule['id'], obs, '规则无明确原文匹配词，仅供模型和人工核实', 'uncertain')
                continue
            matched = [r for r in notes if r['source_page'] == obs['source_page'] and
                       r.get('part_id') == obs.get('part_id') and
                       any(term in str(r.get('text') or '') for term in terms)]
            self.record('ERR-09', 'required-' + rule['id'], obs,
                '已提取技术要求匹配：%s；企业依据%s' % (rule['requirement'], rule['source']) if matched else
                '适用的企业要求未在本页已提取技术要求中找到：%s；须核实原图与提取完整性，依据%s' % (rule['requirement'], rule['source']),
                'checked' if matched else 'issue')
        for obs in notes:
            raw = str(obs.get('text') or '')
            if re.search(r'待定|待补|TBD|TODO', raw, re.I):
                self.record('ERR-09', 'requirement-placeholder', obs, '技术要求含待定/待补占位文本，需确认发布状态', 'issue')
            match = re.search(r'(?:HRC|HBW?|HV)\s*(' + NUM + r')\s*[~～至]\s*(' + NUM + ')', raw, re.I)
            if match and number(match[1]) > number(match[2]):
                self.record('ERR-09', 'requirement-range', obs, '技术要求硬度范围的下限大于上限；需核实原文', 'issue')
            match = re.search(r'(?<![A-Za-z])Ra\s*(' + NUM + ')', raw, re.I)
            if match and number(match[1]) < 0:
                self.record('ERR-09', 'requirement-roughness', obs, '技术要求Ra数值为负数', 'issue')

    def formatting(self):
        scales = str(self.title.get('scale') or '')
        obs = {'id': 'title-scale', 'source_page': self.config.get('title_source_page'),
               'location': '标题栏-比例', 'evidence': scales}
        if scales:
            pairs = re.findall(r'(' + NUM + r')\s*[:：]\s*(' + NUM + ')', text(scales))
            if not pairs:
                self.record('ERR-10', 'scale-format', obs, '比例原文未解析，可能为不按比例或特殊标记', 'uncertain')
            else:
                for a, b in pairs:
                    if number(a) <= 0 or number(b) <= 0:
                        self.record('ERR-10', 'scale-positive', obs, '比例的分子或分母为非正数',
                                    'issue' if type(obs['source_page']) is int else 'uncertain')
                    else:
                        ratio = number(a)/number(b)
                        allowed = self.config.get('format_policy', {}).get('allowed_scales', [])
                        ratios = [number(v.split(':')[0])/number(v.split(':')[1]) for v in allowed]
                        self.record('ERR-10', 'scale-policy', obs,
                            '比例%s:%s不在企业允许列表中；依据%s' % (a,b,self.config['format_policy']['source']) if ratios and ratio not in ratios else
                            '比例%s:%s为正且可解析；未验证绘图实际比例' % (a,b),
                            'issue' if ratios and ratio not in ratios and type(obs['source_page']) is int else
                            'uncertain' if ratios and ratio not in ratios else 'checked')
        sheets = {'A0': (841,1189), 'A1': (594,841), 'A2': (420,594), 'A3': (297,420), 'A4': (210,297)}
        policy = self.config.get('format_policy', {})
        for page in self.metadata:
            obs = dict(page, id='page-%s' % page.get('source_page'), location='PDF页面', evidence='原始PDF页面框物理尺寸')
            if page.get('kind') != 'pdf':
                self.record('ERR-10', 'sheet-size', obs, '图片/CAD渲染像素无法证明原图物理图幅、字号、线型或图层', 'uncertain')
                continue
            width, height = sorted((page['width_mm'], page['height_mm']))
            match = next((key for key, (w,h) in sheets.items() if abs(width-w) < 1 and abs(height-h) < 1), None)
            self.record('ERR-10', 'sheet-size', obs, 'PDF页面框对应%s；未判断图框、字体、线型和CAD图层' % match if match else
                'PDF页面框不是基本A0-A4尺寸；可能为加长图幅、裁切或缩放，未判违规', 'checked' if match else 'uncertain',
                {'width_mm': width, 'height_mm': height, 'basic_sheet': match})
            if match and policy.get('allowed_sheets') and match not in policy['allowed_sheets']:
                self.record('ERR-10', 'sheet-policy', obs, 'PDF页面框图幅%s不在企业允许列表中；依据%s。须确认PDF导出缩放。' % (match,policy['source']), 'issue')


def run_engineering_checks(observations, dimensions, components, title, config=None, metadata=None):
    facts = observations if isinstance(observations, dict) else {}
    facts = {group: facts.get(group, []) for group in GROUPS}
    original_pages = [r.get('source_page') for r in (metadata or []) + (dimensions or []) if isinstance(r,dict)]
    original_pages += [r.get('source_page') for rows in facts.values() if isinstance(rows,list) for r in rows if isinstance(r,dict)]
    pages = max([p for p in original_pages if type(p) is int and p > 0] or [1])
    errors = validate_observations(facts, pages, dimensions or [], components or [])
    if errors:
        facts = {group: [] for group in GROUPS}
    checker = Checker(dimensions or [], components or [], title or {}, validate_engineering_config(config or {}), metadata)
    checker.tolerances(facts)
    checker.geometric(facts)
    checker.views(facts)
    checker.references(facts)
    checker.requirements(facts)
    checker.formatting()
    coverage = {}
    for code in CODES:
        rows = [r for r in checker.checks if r['err_id'] == code]
        coverage[code] = {'checked': sum(r['status'] in ('checked','issue') for r in rows),
                          'issues': sum(r['status'] == 'issue' for r in rows),
                          'uncertain': sum(r['status'] == 'uncertain' for r in rows),
                          'limitation': '仅覆盖已提取事实与已配置规则；没有问题不代表全图合格。'}
    return {'issues': checker.issues, 'checks': checker.checks, 'coverage': coverage,
            'observations': facts, 'standards_snapshot_date': checker.catalog['checked_on'],
            'status': 'invalid_observations' if errors else 'partial',
            'validation_errors': errors, 'compliance': 'not_certified'}
