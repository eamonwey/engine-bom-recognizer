# -*- coding: utf-8 -*-
"""离线 Mock 视觉模型：不联网即可端到端跑通流水线与评测。

注意：Mock 故意模拟“不完美的识别结果”——
  * 漏掉清单中的最后一个元器件（模拟漏检，考察召回）；
  * 把“活塞”的数量识别错（模拟字段错误，考察字段准确率）。
这样演示评测时能得到非平凡的 P/R/F1 指标，方便验证评测链路本身。
接入了真实视觉模型后，直接在 config 里切换 provider 即可，无需改代码。
"""
import json
import time
from typing import Any, Dict, List

from PIL import Image

from .base import ProviderResponse, VisionProvider

_MOCK_COMPONENTS = [
    {"item_no": 1, "part_number": "ENG-BLK-001", "name_zh": "气缸体", "name_en": "Cylinder Block",
     "category": "机体与气缸盖", "specification": "直列四缸", "material": "铸铁 HT250",
     "quantity": 1, "unit": "件", "position": "发动机主体", "confidence": 0.97},
    {"item_no": 2, "part_number": "ENG-HD-002", "name_zh": "气缸盖", "name_en": "Cylinder Head",
     "category": "机体与气缸盖", "specification": "DOHC 16V", "material": "铝合金 A356",
     "quantity": 1, "unit": "件", "position": "气缸体上方", "confidence": 0.96},
    {"item_no": 3, "part_number": "ENG-PST-003", "name_zh": "活塞", "name_en": "Piston",
     "category": "曲柄连杆机构", "specification": "Φ86×60mm", "material": "铝合金 4032",
     "quantity": 6, "unit": "件", "position": "气缸体内", "remark": "数量识别存疑", "confidence": 0.72},
    {"item_no": 4, "part_number": "ENG-RNG-004", "name_zh": "活塞环", "name_en": "Piston Ring",
     "category": "曲柄连杆机构", "specification": "三件组", "material": "合金钢",
     "quantity": 12, "unit": "件", "position": "活塞环槽", "confidence": 0.94},
    {"item_no": 5, "part_number": "ENG-CRD-005", "name_zh": "连杆", "name_en": "Connecting Rod",
     "category": "曲柄连杆机构", "specification": "锻造成型", "material": "锻钢 40Cr",
     "quantity": 4, "unit": "件", "position": "活塞与曲轴间", "confidence": 0.95},
    {"item_no": 6, "part_number": "ENG-CRS-006", "name_zh": "曲轴", "name_en": "Crankshaft",
     "category": "曲柄连杆机构", "specification": "五主轴颈", "material": "锻钢 42CrMo",
     "quantity": 1, "unit": "件", "position": "主轴承座", "confidence": 0.96},
    {"item_no": 7, "part_number": "ENG-VLV-007", "name_zh": "进气门", "name_en": "Intake Valve",
     "category": "配气机构", "specification": "Φ32mm", "material": "耐热钢",
     "quantity": 4, "unit": "件", "position": "气缸盖进气侧", "confidence": 0.93},
    {"item_no": 8, "part_number": "ENG-VLV-008", "name_zh": "排气门", "name_en": "Exhaust Valve",
     "category": "配气机构", "specification": "Φ28mm", "material": "耐热合金",
     "quantity": 4, "unit": "件", "position": "气缸盖排气侧", "confidence": 0.93},
    {"item_no": 9, "part_number": "ENG-CAM-009", "name_zh": "凸轮轴", "name_en": "Camshaft",
     "category": "配气机构", "specification": "双顶置", "material": "合金铸铁",
     "quantity": 2, "unit": "件", "position": "气缸盖上部", "confidence": 0.94},
    {"item_no": 10, "part_number": "ENG-INJ-010", "name_zh": "喷油器", "name_en": "Fuel Injector",
     "category": "燃油供给系统", "specification": "多孔高压", "material": "",
     "quantity": 4, "unit": "件", "position": "进气道", "confidence": 0.92},
    {"item_no": 11, "part_number": "ENG-OMP-011", "name_zh": "机油泵", "name_en": "Oil Pump",
     "category": "润滑系统", "specification": "转子式", "material": "",
     "quantity": 1, "unit": "件", "position": "油底壳内", "confidence": 0.91},
    # 第 12 项（水泵）被 Mock “漏检”，用于演示召回率指标
]


class MockVisionProvider(VisionProvider):
    """确定性 Mock：按提示词中的任务标记返回对应的固定演示数据（JSON 字符串）。

    任务标记: TASK:TITLEBLOCK / TASK:DOC_EXTRACT / TASK:DIMS / 无标记=BOM 识别。
    """

    name = "mock"

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg or {}

    def analyze(self, images: List[Image.Image], prompt: str) -> ProviderResponse:
        started = time.time()
        if "TASK:TITLEBLOCK" in prompt:
            payload: Any = {"title_block": _MOCK_TITLEBLOCK}
        elif "TASK:DOC_EXTRACT" in prompt:
            payload = _MOCK_DOC_EXTRACT
        elif "TASK:DIMS" in prompt:
            payload = {"dimensions": _MOCK_DIMENSIONS, "balloons": list(range(1, 19))}
        else:
            payload = {"components": _MOCK_COMPONENTS}
        raw = json.dumps(payload, ensure_ascii=False)
        return ProviderResponse(
            raw_text=raw,
            model="mock-engine-bom-v1",
            latency_s=time.time() - started,
            usage={"mock": True, "pages": len(images)},
        )

    def describe(self) -> Dict[str, Any]:
        return {"provider": self.name, "model": "mock-engine-bom-v1"}


_MOCK_TITLEBLOCK = {
    "drawing_name": "XX490 汽油发动机 零部件明细表",
    "drawing_no": "XX490-ZM-01",
    "material": "HT250 / 4032 铝合金",
    "scale": "1:2",
    "weight": "",
    "designer": "王工",
    "checker": "李工",
    "approver": "",
    "date": "2026-09-01",
    "revision": "B",
    "project": "XX490",
}

_MOCK_DOC_EXTRACT = {
    "tech_params": [
        {"name": "工作环境温度", "value": "-55~+70", "unit": "℃", "condition": "试车条件", "source": "技术要求5"},
        {"name": "转速范围", "value": "0~12000", "unit": "r/min", "condition": "稳态工况", "source": "技术要求5"},
        {"name": "平衡等级", "value": "G6.3", "unit": "", "condition": "装配后动平衡", "source": "技术要求5"},
    ],
    "materials": [
        {"name": "缸体材料", "brand": "HT250", "spec": "", "standard": "GB/T 9439", "treatment": "时效处理"},
        {"name": "活塞材料", "brand": "4032 铝合金", "spec": "Φ86mm", "standard": "GB/T 3190", "treatment": "T6"},
    ],
    "process_requirements": [
        {"content": "零件需进行无损检测，关键部位按 GJB 5286-2004 要求执行", "type": "检验工艺", "location": "技术要求4"},
        {"content": "装配后应进行动平衡试验，平衡等级 G6.3", "type": "装配要求", "location": "技术要求5"},
    ],
    "inspection": [
        {"item": "缸体水压试验", "method": "0.4MPa 保压 3min", "criteria": "无渗漏", "standard": "企业标准 Q/XX 012"},
        {"item": "关键部位无损检测", "method": "磁粉/超声", "criteria": "无裂纹", "standard": "GJB 5286-2004"},
    ],
}

_MOCK_DIMENSIONS = [
    {"tag": "总长", "value": "2680±5", "view": "主视图"},
    {"tag": "最大外径", "value": "Φ1560", "view": "主视图"},
    {"tag": "最大外径", "value": "Φ1560", "view": "左视图"},
    {"tag": "安装孔分布圆", "value": "Φ1200", "view": "A-A 剖视"},
    {"tag": "安装孔分布圆", "value": "Φ980", "view": "A-A 剖视"},
]
