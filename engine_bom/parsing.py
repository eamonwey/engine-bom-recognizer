# -*- coding: utf-8 -*-
"""模型原始输出 -> 组件列表：鲁棒的 JSON 提取与容错修复。"""
import json
import re
from typing import Any, List, Optional, Tuple

from .schema import BomComponent, components_from_payload

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def extract_json_payload(text: str) -> Tuple[Optional[Any], List[str]]:
    """从模型回复中提取 JSON 载荷，逐级降级容错。

    1. 直接 json.loads
    2. Markdown 代码块 ```json ... ```
    3. 首个 '{' 到末个 '}' / 首个 '[' 到末个 ']' 的切片
    4. 去掉尾逗号 / 智能引号后再试
    """
    warnings: List[str] = []
    if text is None:
        return None, ["模型输出为空"]
    text = text.strip()
    if not text:
        return None, ["模型输出为空"]

    candidates: List[str] = [text]
    for match in _FENCE_RE.finditer(text):
        candidates.append(match.group(1).strip())

    brace = _outer_slice(text, "{", "}")
    bracket = _outer_slice(text, "[", "]")
    if brace:
        candidates.append(brace)
    if bracket:
        candidates.append(bracket)

    for cand in candidates:
        payload, err = _try_loads(cand)
        if payload is not None:
            return payload, warnings
        if err is not None and cand == text:
            # 首个候选（原文）失败时再尝试修复后重载
            repaired = _repair_common_issues(cand)
            if repaired != cand:
                payload, _ = _try_loads(repaired)
                if payload is not None:
                    warnings.append("模型输出包含非法 JSON，已自动修复（尾逗号/智能引号）")
                    return payload, warnings

    warnings.append("无法从模型输出中解析出 JSON（前 200 字符: %s）" % text[:200])
    return None, warnings


def _outer_slice(text: str, open_ch: str, close_ch: str) -> Optional[str]:
    start = text.find(open_ch)
    end = text.rfind(close_ch)
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start:end + 1]


def _try_loads(text: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(text), None
    except (ValueError, TypeError) as exc:
        return None, str(exc)


def _repair_common_issues(text: str) -> str:
    repaired = re.sub(r",\s*([}\]])", r"\1", text)           # 尾逗号
    repaired = repaired.replace("“", '"').replace("”", '"')  # 智能引号
    repaired = repaired.replace("’", "'").replace("‘", "'")
    repaired = re.sub(r"[ \t]+([,\]\}])", r"\1", repaired)
    return repaired


def response_to_components(raw_text: str) -> Tuple[List[BomComponent], List[str]]:
    """模型回复 -> (组件列表, 警告列表)。"""
    payload, warnings = extract_json_payload(raw_text)
    if payload is None:
        return [], warnings
    comps, parse_warnings = components_from_payload(payload)
    return comps, warnings + parse_warnings
