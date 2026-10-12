# -*- coding: utf-8 -*-
"""Provider 注册表与工厂。

【接入新视觉模型】实现 VisionProvider 子类后在下方 PROVIDERS 登记，
再把 config.yaml 的 provider.name 改成你的键名即可。
"""
from typing import Any, Dict

from .base import ProviderConfigError, ProviderError, ProviderResponse, ProviderTimeout, VisionProvider
from .mock import MockVisionProvider
from .openai_compat import OpenAICompatVisionProvider

PROVIDERS = {
    MockVisionProvider.name: MockVisionProvider,
    OpenAICompatVisionProvider.name: OpenAICompatVisionProvider,
}


def build_provider(cfg: Dict[str, Any]) -> VisionProvider:
    name = str(cfg.get("name") or "mock")
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ProviderConfigError("未知 provider: %r，可选: %s" % (name, sorted(PROVIDERS)))
    if name == "openai_compat":
        return cls(cfg.get("openai_compat") or {})
    return cls(cfg)
