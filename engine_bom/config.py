# -*- coding: utf-8 -*-
"""配置加载与合并（支持 YAML / JSON，未安装 pyyaml 时可用 JSON）。"""
import copy
import json
import os
from typing import Any, Dict, Optional

DEFAULT_CONFIG: Dict[str, Any] = {
    "assembly": {"enabled": True, "max_attempts": 3, "method": "installation", "verify_visual": True},
    "impact": {"index_path": "data/knowledge/associations.json"},
    "enterprise": {"required_annotations": [], "export_fields": {}},
    "agent_loop": {"max_attempts": 3},
    "inspection": {"enabled": True, "max_attempts": 3, "require_engineering_observations": True,
                   "dimension_links": True, "dimension_link_attempts": 2,"local_dimension_text":True},
    "ingestion": {
        "dpi": 200,                    # PDF 渲染 DPI
        "max_image_long_side": 2240,   # 送入模型前长边上限（像素），0 表示不缩放
        "image_formats": [".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"],
        # 扫描件预处理（需 OpenCV；REQ-01-1: 去噪/倾斜校正/二值化）
        "preprocess": {
            "enabled": False,
            "deskew": True,            # 倾斜校正
            "denoise": False,          # 去噪（较慢，扫描质量差时开启）
            "binarize": False,         # 二值化
            "contrast": True,          # 对比度增强
        },
    },
    "provider": {
        "name": "mock",                # mock | openai_compat
        "openai_compat": {
            "base_url": "",            # TODO(接入点): 视觉模型 API 地址
            "model": "",               # TODO(接入点): 模型名
            "api_key_env": "VISION_API_KEY",
            "temperature": 0.0,
            "max_tokens": 4096,
            "timeout": 300,        # 密集工程图纸单页推理可能超过 120s
            "retries": 2,          # 超时/连接失败自动重试次数
            "response_format_json": False,  # 端点支持 response_format 时可开启
        },
    },
    "recognition": {
        "mode": "per_page",            # per_page（逐页识别后合并） | whole_doc（整档一次识别）
        "prompt_version": "v4",
        "min_confidence": 0.0,
        "preserve_printed_rows": True,  # 审图必须保留原序号、重复行和异常数量
        # 跨页重复元器件的数量合并策略: keep_max（默认，防重复计数）| sum（拆表场景）| keep_first
        "duplicate_quantity_policy": "keep_max",
    },
    "knowledge": {
        "enabled": True,               # 对应论文 RAG 检索增强（可选）
        "path": "data/knowledge/engine_rules.txt",
        "top_k": 3,
    },
    "validation": {
        "strict": False,               # True 时校验失败直接抛错
    },
    "output": {
        "dir": "data/predictions",
        "formats": ["json", "csv"],    # json | csv | xlsx
    },
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并 dict，override 优先。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """加载配置文件并与默认值合并；path 为空则返回默认配置。"""
    if not path:
        return copy.deepcopy(DEFAULT_CONFIG)
    path = os.path.abspath(path)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError:
            raise RuntimeError("读取 YAML 配置需要 pyyaml：pip install pyyaml（或改用 .json 配置）")
        user_cfg = yaml.safe_load(text) or {}
    else:
        user_cfg = json.loads(text) if text.strip() else {}
    return deep_merge(DEFAULT_CONFIG, user_cfg)


def cfg_get(cfg: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    """按 'a.b.c' 路径取配置值。"""
    node: Any = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def resolve_output_dir(cfg: Dict[str, Any], config_path: Optional[str] = None) -> str:
    """输出目录：绝对路径直接用；相对路径相对配置文件所在目录（无配置文件则相对当前目录）。"""
    out_dir = str(cfg_get(cfg, "output.dir", "data/predictions"))
    if os.path.isabs(out_dir):
        return out_dir
    base = os.path.dirname(os.path.abspath(config_path)) if config_path else os.getcwd()
    return os.path.normpath(os.path.join(base, out_dir))
