# -*- coding: utf-8 -*-
"""数据集发现与标注加载。

数据集目录约定（详见 README）:
  data/raw/<doc_id>.pdf|.png|.jpg...        原始输入文档
  data/annotations/<doc_id>.json            人工标注 BOM（与系统输出同构）
"""
import json
import os
from typing import Dict, List, Optional, Tuple

from ..config import DEFAULT_CONFIG
from ..schema import BomDocument, components_from_payload

_RAW_EXTS = [".pdf"] + [str(x).lower() for x in DEFAULT_CONFIG["ingestion"]["image_formats"]]


def discover_documents(raw_dir: str, anno_dir: Optional[str] = None) -> List[Dict[str, Optional[str]]]:
    """枚举 raw_dir 下全部受支持的输入文档；给出 anno_dir 时附带对应标注路径（可能为 None）。"""
    if not os.path.isdir(raw_dir):
        raise FileNotFoundError("原始文档目录不存在: %s" % raw_dir)
    docs: List[Dict[str, Optional[str]]] = []
    for name in sorted(os.listdir(raw_dir)):
        path = os.path.join(raw_dir, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in _RAW_EXTS:
            continue
        doc_id = os.path.splitext(name)[0]
        anno_path: Optional[str] = None
        if anno_dir:
            candidate = os.path.join(anno_dir, doc_id + ".json")
            anno_path = candidate if os.path.isfile(candidate) else None
        docs.append({"doc_id": doc_id, "raw_path": path, "annotation_path": anno_path})
    return docs


def load_bom_json(path: str) -> BomDocument:
    """加载 BOM JSON（预测输出或人工标注均可），容错解析为 BomDocument。"""
    doc_id = os.path.splitext(os.path.basename(path))[0]
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    components, warnings = components_from_payload(data.get("components", data))
    return BomDocument(
        document_id=str(data.get("document_id") or doc_id),
        source_file=str(data.get("source_file") or ""),
        generated_at=str(data.get("generated_at") or ""),
        model_info=dict(data.get("model_info") or {}),
        components=components,
        validation_issues=[str(x) for x in (data.get("validation_issues") or [])],
        process_time_s=data.get("process_time_s"),
    )
