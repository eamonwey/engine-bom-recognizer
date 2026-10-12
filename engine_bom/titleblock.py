# -*- coding: utf-8 -*-
"""标题栏信息提取（REQ-01-2）：定位图纸标题栏并抽取结构化字段。

通过视觉模型完成（提示词内置 TASK:TITLEBLOCK 标记供 Mock 分流），
字段按常见 GB 制图标题栏设计，不同企业模板差异由提示词自适应 +
人工复核兜底（需求表备注：需支持模板配置+少样本适配）。
"""
import json
import re
from typing import Any, Dict, List

from .providers import VisionProvider

TASK_MARKER = "TASK:TITLEBLOCK"

TITLE_FIELDS = [
    "drawing_name", "drawing_no", "material", "scale", "weight",
    "designer", "checker", "approver", "date", "revision", "project",
]

# 必填字段（ERR-08 检查用）
REQUIRED_TITLE_FIELDS = ["drawing_name", "drawing_no", "designer", "date"]

_EXAMPLE = {
    "drawing_name": "航空发动机总装图（涡扇发动机）",
    "drawing_no": "AE-1000-00",
    "material": "",
    "scale": "1:10 / 1:5 / 1:2",
    "weight": "",
    "designer": "张三",
    "checker": "李四",
    "approver": "王五",
    "date": "2025.06",
    "revision": "B",
    "project": "AE-1000",
}


def build_titleblock_prompt() -> str:
    return """%s 你是工程图纸标题栏识别专家。请阅读图纸右下角标题栏区域（可能包含图名、图号、材料、比例、重量、设计/校核/审核/批准人员、日期、版本、项目代号等），提取全部可辨识字段。

【规则】
1. 只提取图纸中真实出现的文字，看不清或没有的字段填空字符串 ""，禁止编造。
2. 日期保持原格式；比例如有多视图多个比例，用 "/" 连接原文。
3. 企业自定义字段放入 extra 对象，仅当原图明确写有“序号”标签才允许 title_no_field；不得把材料牌号当成序号。
4. drawing_type 填 assembly/part/unknown。图上明确标有材料时，无论装配图还是零件图，照录 material 并令 material_applicable=true；不能凭图纸类型忽略可见材料。无材料且明确不适用才填false，否则null。
5. 必须返回 field_evidence.material={"label":"原图材料标签","value":"原文值"}；未发现标签和值时两者填空。extra 中每个字段也提供同名 field_evidence，包含原图标签和值，禁止臆造标签。
6. 输入可能同时含整页和标题栏放大图，它们是同一图纸的上下文与局部。局部边缘的标签如被裁切，应回到整页读取；明细栏各零件材料不可替代标题栏材料。

【输出格式】只输出一个 JSON 对象：
{"title_block": {"drawing_name": "图名", "drawing_no": "图号", "material": "材料", "scale": "比例",
 "weight": "重量", "designer": "设计", "checker": "校核", "approver": "批准",
 "date": "日期", "revision": "版本", "project": "项目代号", "drawing_type":"unknown", "material_applicable":null,"extra": {},"field_evidence":{"material":{"label":"","value":""}}}}
""" % TASK_MARKER


def parse_titleblock_response(raw_text: str) -> Dict[str, Any]:
    """模型回复 -> 标题栏字段 dict（容错）。"""
    from .parsing import extract_json_payload
    payload, _ = extract_json_payload(raw_text)
    if isinstance(payload, dict):
        tb = payload.get("title_block")
        if isinstance(tb, dict):
            return tb
        return payload
    return {}


def extract_titleblock(provider: VisionProvider, images: List, total_pages: int = 1,
                       source_page_numbers=None) -> Dict[str, Any]:
    """对图纸（通常取末页/单页）提取标题栏。返回 {fields, missing_required, raw}。"""
    from .agent_loop import AgentLoop
    mapping = source_page_numbers if source_page_numbers is not None else ([total_pages] if len(images) == 1 else None)
    prompt = build_titleblock_prompt()
    if mapping:
        prompt += '\n输入图片对应原始页码：' + json.dumps(mapping) + '。标题栏另返回source_page，必须使用原始页码，放大图不是新页。'
    if provider.name == 'mock':
        resp = provider.analyze(images, prompt)
        fields = parse_titleblock_response(resp.raw_text)
    else:
        outcome = AgentLoop(provider, 3).run(images, prompt, validate_titleblock)
        resp, fields = outcome.response, outcome.value
        fields['extraction_status'] = outcome.status
        fields['extraction_warnings'] = outcome.events[-1]['errors']
    if mapping and len(set(mapping)) == 1:
        fields['source_page'] = mapping[0]
    elif type(fields.get('source_page')) is not int or not mapping or fields['source_page'] not in mapping:
        fields.pop('source_page', None)
    missing = [f for f in REQUIRED_TITLE_FIELDS if not str(fields.get(f) or "").strip()]
    return {
        "fields": fields,
        "missing_required": missing,
        "model": resp.model,
        "latency_s": resp.latency_s,
    }


def validate_titleblock(raw):
    """Check label/value alignment; never guess a material from a bare number."""
    fields = parse_titleblock_response(raw)
    errors = []
    evidence = fields.get('field_evidence')
    if not isinstance(evidence, dict):
        evidence = {}
    material = evidence.get('material')
    if not isinstance(material, dict) or not all(isinstance(material.get(k), str) for k in ('label', 'value')):
        errors.append('缺少材料字段的原图标签和值证据')
    else:
        label, value = material['label'].strip(), material['value'].strip()
        if value and ('材料' in label or 'material' in label.lower()):
            fields['material'] = value
            fields['material_applicable'] = True
        elif str(fields.get('material') or '').strip() or value:
            errors.append('材料值缺少对应原图材料标签，请重新读图')
    extra = fields.get('extra') or {}
    if not isinstance(extra, dict):
        errors.append('extra 必须为对象')
    else:
        for key, value in extra.items():
            item = evidence.get(key)
            if not isinstance(item, dict) or not str(item.get('label') or '').strip() or str(item.get('value', '')).strip() != str(value).strip():
                errors.append('自定义字段 %s 缺少一致的标签和值证据' % key)
            elif key == 'title_no_field' and not any(word in str(item['label']).lower() for word in ('序号', 'item', 'serial')):
                errors.append('title_no_field 标签不是序号，不得把材料放入序号栏')
    return fields, errors


def mock_titleblock() -> Dict[str, Any]:
    return json.loads(json.dumps(_EXAMPLE, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 尺寸标注 / 引出序号抽取（供图纸规则检查 ERR-01/ERR-08 使用）
# ---------------------------------------------------------------------------

DIMS_TASK_MARKER = "TASK:DIMS"

_DIMS_PROMPT = """%s 你是工程图纸读图专家。请通读图纸，完成两项抽取：

1. dimensions: 提取全部可读尺寸标注（包括匿名数值、直径、半径、公差）。
   - tag只填写图面印出的尺寸代号；“总高、键槽宽、轴伸直径、轴承座孔”等描述另填description，不能当成跨视图同一要素标识。
   - 特别逐处读取端盖止口、轴承座孔、配合直径，即使两处数值相同也保留各自位置；不能用另一处数值补全当前读数。
   - bbox尽量准确圈住尺寸文本；未定位的读数不得编造feature_id。尺寸线在纸面同向不证明三维方向相同。
   - 匿名尺寸tag填空字符串；description记录所在位置与要素描述，禁止因数值相同就猜为同一尺寸；
   - value 填数值原文（含公差/直径符号）；view 填所在视图（主视图/左视图/A-A 等）。
   - source_page 填1起始页码，unit填原文单位，bbox填整页归一化坐标或null。图面整体声明单位mm时，各线性尺寸unit均填mm；单位无法确认填空。
   - part_id 填所属零件图号或明确的独立分区编号；feature_id只有原图明确的同一几何要素标识才填写。不同零件/独立分区的同名孔不是同一要素。
   - 不把形位框格值、硬度、表面粗糙度、螺钉规格当普通线性尺寸；公差不能凭空改成正常读数。
   - 普通线性尺寸另填 linear_geometry：{"axis":"horizontal|vertical","dimension_line":[[x1,y1],[x2,y2]],"evidence":"尺寸线与两端尺寸界线的实际位置"}。
     带±公差、上下偏差或极限尺寸的线性长度也必须独立记录linear_geometry，保留公差原文；不得只给无公差长度记录端点。
     坐标为整页归一化0..1，取尺寸线两端箭头/尺寸界线交点，不是数字文本框、物体外框或引出序号。
     horizontal按左到右、vertical按上到下记录；方向以尺寸线为准，不能以数字文字的阅读方向为准。
     无法追踪两个端点、斜向尺寸、直径/半径/角度时linear_geometry填null；禁止按数值比例或猜测的尺寸链补坐标。
     每个尺寸独立观察，左右水平长度与右侧上下高度不得混作同方向。
   - dimension_role 填component/closing_requirement/unknown；只有原图明确写装配后间隙、轴向游隙、功能封闭环要求时才填closing_requirement，
     component包括普通组成长度，例如腔体总长、内件长度，不要求该尺寸单独对应BOM的一件；这些长度属于同一装配时应填一致的assembly_scope。
     role_evidence 保留说明该功能要求的原文，普通零件长度即使带公差也不是closing_requirement。
     role_evidence只能照录原文，禁止添加“注：L为封闭环”等自己的推断。原图说“间隙S必须满足...”时，只有S是closing_requirement；
     腔体长度L和内件长度B仍是component，不能给L引用S的要求，也不能仅因L为总长就判为功能封闭环。
     明确的线性间隙/游隙要求也作为dimensions一项提取，保留数值与上下偏差/极限尺寸、单位和实际两端尺寸界线。
     上下偏差可按"100 +0.2/-0.1"保留，极限尺寸可按"0.8/0.2"保留；只允许改变上下排版为单行，不得改动数字或正负号。
   - assembly_scope 填该尺寸所属的明确装配视图/分区图号；同一装配的不同零件长度及间隙可具有同一assembly_scope。
     独立零件分区、无关小件不能使用同一个assembly_scope；无法确认时填空，禁止为凑尺寸链归为同组。
2. balloons: 提取图中全部引出序号（零件球标/圈号）的数字列表。

【输出格式】只输出一个 JSON 对象：
{"dimensions": [{"tag": "", "description":"整体长度", "value": "2680±5", "view": "主视图", "unit":"mm", "source_page":1,"part_id":"原图零件或分区编号","assembly_scope":"明确装配视图或分区标识","dimension_role":"component","role_evidence":"原文长度标注","feature_id":"","bbox":null,"linear_geometry":null}], "balloons": [1, 2, 3]}
""" % DIMS_TASK_MARKER


def extract_dims_and_balloons(provider: VisionProvider, images: List) -> Dict[str, Any]:
    """抽取尺寸标注与引出序号（ERR-01 数值比对与 ERR-08 序号对应检查的数据源）。"""
    from .agent_loop import AgentLoop
    from .parsing import extract_json_payload
    def validate(raw):
        payload,errors=extract_json_payload(raw)
        if not isinstance(payload,dict) or not isinstance(payload.get('dimensions'),list) or not isinstance(payload.get('balloons'),list):
            return {},errors+['必须返回dimensions对象数组和balloons数组']
        for index,dim in enumerate(payload['dimensions']):
            if not isinstance(dim,dict) or not isinstance(dim.get('value'),str):
                errors.append('dimension %d 缺少尺寸对象或原文字符串'%index)
                continue
            error=dimension_role_error(dim)
            if error:errors.append('dimension %d: %s'%(index,error))
        return payload,errors
    loop=AgentLoop(provider,3)
    from .installation_review import review_images
    observed,note=review_images(images)
    if not note:
        observed=images
    outcome=loop.run(observed,_DIMS_PROMPT+note+'\n局部与整页是同一图，不重复计数。bbox使用原始整页坐标，source_page不得使用裁切图片的序号。',validate)
    payload=outcome.value if outcome.status=='validated' else {}
    result = {"dimensions": [], "balloons": []}
    if isinstance(payload, dict):
        if isinstance(payload.get("dimensions"), list):
            result["dimensions"] = payload["dimensions"]
        if isinstance(payload.get("balloons"), list):
            result["balloons"] = payload["balloons"]
    result["model"] = outcome.response.model
    result['detail_images']=len(observed)-len(images)
    result['source_image_sizes']=[list(image.size) for image in images if hasattr(image,'size')]
    result['status']=outcome.status
    result['events']=outcome.events
    result['warnings']=outcome.events[-1]['errors'] if outcome.status!='validated' else []
    for dimension in result['dimensions']:
        if isinstance(dimension,dict) and len(images) == 1 and dimension.get('source_page') is None:
            dimension['source_page'] = 1
    return result


def dimension_role_error(dim):
    """Reject an explicit L->S requirement mixup, never infer new roles."""
    if dim.get('dimension_role')!='closing_requirement':return None
    evidence=dim.get('role_evidence')
    if not isinstance(evidence,str) or not evidence.strip():return '封闭环必须照录该尺寸的功能要求原文'
    tag=re.search(r'([A-Za-z][A-Za-z0-9_]*)$',str(dim.get('tag') or ''))
    named=re.findall(r'(?:间隙|游隙|封闭环|总长|总尺寸|轴向距离|功能长度)\s*([A-Za-z][A-Za-z0-9_]*)',evidence)
    if tag and named and tag[1] not in named:
        return '该尺寸的功能证据实际指向其他标记；不能把总长L当作间隙S的功能要求，须重新读原文'
    return None
