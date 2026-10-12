# -*- coding: utf-8 -*-
"""视觉模型 Provider 抽象基类。

═══════════════════════════════════════════════════════════════════
【视觉模型接入点】当你拿到视觉模型 API 后：
  1. 实现 analyze(images, prompt) -> ProviderResponse；
  2. 在 providers/__init__.py 的 PROVIDERS 注册表中登记；
  3. config.yaml 里 provider.name 改成你的名字。
系统其余部分（多页合并、校验、导出、评测）不需要任何改动。
参考实现见 openai_compat.py（OpenAI 兼容接口，适配 GPT-4o /
Qwen-VL / GLM-4V / vLLM 本地部署等）与 mock.py（离线假实现）。
═══════════════════════════════════════════════════════════════════
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from PIL import Image


@dataclass
class ProviderResponse(object):
    raw_text: str                      # 模型原始回复（应为 JSON 文本）
    model: str = ""                    # 实际使用的模型名
    latency_s: float = 0.0             # 单次调用耗时（秒）
    usage: Dict[str, Any] = field(default_factory=dict)  # token 用量等
    finish_reason: Optional[str] = None
    request_metadata: Dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Provider 配置或调用错误。"""


class ProviderTimeout(ProviderError):
    """调用超时（通常值得重试）。"""


class ProviderTransientError(ProviderError):
    """Temporary transport/server failure. Authentication errors are not transient."""


class ProviderConfigError(ProviderError):
    """配置缺失（如未填 base_url/api_key）。"""


class VisionProvider(ABC):
    """所有视觉模型 Provider 的抽象基类。"""

    name: str = "base"

    @abstractmethod
    def analyze(self, images: List[Image.Image], prompt: str) -> ProviderResponse:
        """对若干页面图像执行识别，返回模型原始输出。

        images: 当前请求的页面图像（per_page 模式下为单页；whole_doc 为全部页）。
        prompt: 由 prompts.build_recognition_prompt 构造的完整提示词。
        """

    def describe(self) -> Dict[str, Any]:
        """写入 BOM meta 的 Provider 描述（模型名、版本等，便于实验追踪）。"""
        return {"provider": self.name}

    def close(self) -> None:  # 供需要释放连接的 Provider 覆写
        pass
