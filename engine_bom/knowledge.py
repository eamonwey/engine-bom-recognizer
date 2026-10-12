# -*- coding: utf-8 -*-
"""领域知识库（对应论文中 RAG 的检索增强，当前为轻量关键词检索实现）。

把企业的元器件命名规范/分类规则放进一个 txt（每行一条规则），
识别时会检索最相关的若干条注入提示词，用来约束模型输出。
将来要换成 Qdrant/向量检索时，只需实现 KnowledgeBase 接口。
"""
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .schema import normalize_text


class KnowledgeBase(ABC):
    """检索接口：给定查询文本，返回最相关的 top_k 条知识片段。"""

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        ...

    def describe(self) -> Dict[str, Any]:
        return {"kind": self.__class__.__name__}


class NoopKnowledgeBase(KnowledgeBase):
    """空知识库：不注入任何规则。"""

    def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        return []


class FileKnowledgeBase(KnowledgeBase):
    """基于 txt 文件的轻量知识库：按字符级重合度打分检索整行规则。"""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.entries: List[str] = []
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self.entries = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
        else:
            print("[warn] 知识库文件不存在（将不注入规则）: %s" % self.path)

    def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        if not self.entries:
            return []
        q_chars = set(normalize_text(query))
        scored = []
        for entry in self.entries:
            e_chars = set(normalize_text(entry))
            score = len(q_chars & e_chars) / float(len(q_chars | e_chars) or 1)
            scored.append((score, entry))
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [entry for score, entry in scored[:top_k] if score > 0]

    def describe(self) -> Dict[str, Any]:
        return {"kind": "file", "path": self.path, "entries": len(self.entries)}


def build_knowledge(cfg: Dict[str, Any], base_dir: Optional[str] = None) -> KnowledgeBase:
    """根据配置构建知识库；未启用或未配置时返回空实现。"""
    if not cfg or not cfg.get("enabled"):
        return NoopKnowledgeBase()
    path = str(cfg.get("path") or "")
    if not path:
        return NoopKnowledgeBase()
    if not os.path.isabs(path) and base_dir:
        path = os.path.join(base_dir, path)
    return FileKnowledgeBase(path)
