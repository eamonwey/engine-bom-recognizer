# -*- coding: utf-8 -*-
"""OpenAI 兼容视觉模型 Provider（模板已写好，填入你的 API 信息即可用）。

适配所有提供 OpenAI 风格 /chat/completions 接口的服务，例如：
  * OpenAI          base_url=https://api.openai.com/v1           model=gpt-4o
  * 阿里 DashScope   base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
                    model=qwen2.5-vl-72b-instruct（论文所用 Qwen2.5-VL 系列）
  * 智谱 GLM        base_url=https://open.bigmodel.cn/api/paas/v4
                    model=glm-4v-plus / glm-4.5v
  * 本地 vLLM       base_url=http://localhost:8000/v1            model=服务加载的模型名

═══════════════════════════════════════════════════════════════════
【TODO 接入点】三选一（推荐方式 1，避免把密钥写进文件）：
  方式 1（环境变量，推荐）:
      set VISION_BASE_URL=https://open.bigmodel.cn/api/paas/v4
      set VISION_MODEL=glm-4v-plus
      set VISION_API_KEY=你的key
  方式 2（配置文件）: 在 config.yaml 里填:
      provider:
        name: openai_compat
        openai_compat:
          base_url: https://open.bigmodel.cn/api/paas/v4
          model: glm-4v-plus
  方式 3: 修改下方 _init_from_cfg() 中的 TODO 处，直接写死（仅本地调试用）。
填好后命令行加 --provider openai_compat 即可切换，其余代码零改动。
═══════════════════════════════════════════════════════════════════
"""
import base64
import hashlib
import io
import json
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from PIL import Image

from .base import ProviderConfigError, ProviderError, ProviderResponse, ProviderTimeout, ProviderTransientError, VisionProvider


class OpenAICompatVisionProvider(VisionProvider):
    """通过 OpenAI 兼容 /chat/completions 接口调用多模态视觉模型。"""

    name = "openai_compat"

    def __init__(self, cfg: Dict[str, Any]):
        self._init_from_cfg(cfg or {})

    def _init_from_cfg(self, cfg: Dict[str, Any]) -> None:
        # ── TODO(接入点): 如需写死配置，直接改下面两行 ──────────────
        # 注意 .strip()：环境变量值首尾的空白/换行会导致 HTTP 头非法
        self.base_url: str = str(cfg.get("base_url") or os.environ.get("VISION_BASE_URL", "")).strip().rstrip("/")
        self.model: str = str(cfg.get("model") or os.environ.get("VISION_MODEL", "")).strip()
        # ───────────────────────────────────────────────────────────
        api_key_env = str(cfg.get("api_key_env") or "VISION_API_KEY")
        # 优先级：网页/配置文件里的 api_key > 环境变量（便于内网部署时在界面直接维护）
        cfg_key = str(cfg.get("api_key") or "").strip()
        self.api_key: str = cfg_key or os.environ.get(api_key_env, "").strip()
        self.api_key_source = "config" if cfg_key else ("env" if self.api_key else "none")
        self.temperature: float = float(cfg.get("temperature", 0.0))
        self.max_tokens: int = int(cfg.get("max_tokens", 4096))
        self.timeout: int = int(cfg.get("timeout", 300))
        self.retries: int = int(cfg.get("retries", 2))
        self.response_format_json: bool = bool(cfg.get("response_format_json", False))
        self.max_image_long_side = int(cfg.get("max_image_long_side", 2240))
        self.enable_thinking = cfg.get("enable_thinking") if self.model.lower().startswith("qwen3") else None
        # GLM-5.x 始终思考且不支持关闭，但支持 reasoning_effort（low/high/max）控制推理量
        self.reasoning_effort = cfg.get("reasoning_effort") if "glm" in self.model.lower() else None
        self.last_usage = {}
        self.last_finish_reason = None

        missing = [n for n, v in (("base_url", self.base_url), ("model", self.model)) if not v]
        if missing:
            raise ProviderConfigError(
                "openai_compat 未配置 %s。请设置环境变量 VISION_BASE_URL / VISION_MODEL / VISION_API_KEY，"
                "或在 config.yaml 的 provider.openai_compat 中填写（详见 openai_compat.py 顶部说明）。"
                % ", ".join(missing))
        if not self.api_key:
            # 本地 vLLM 等可免密，仅提示
            print("[warn] 未设置 %s（部分本地部署端点可忽略此提示）" % api_key_env)

    # ------------------------------------------------------------------
    def analyze(self, images: List[Image.Image], prompt: str) -> ProviderResponse:
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,%s" % _image_to_data_uri(img, self.max_image_long_side)},
            })
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.enable_thinking is not None:
            payload["enable_thinking"] = bool(self.enable_thinking)
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        if self.response_format_json:
            payload["response_format"] = {"type": "json_object"}

        self.last_usage = {}
        self.last_finish_reason = None
        metadata={'prompt_sha256':hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
                  'request_sha256':hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest(),
                  'image_sha256s':[hashlib.sha256(c['image_url']['url'].encode('ascii')).hexdigest() for c in content if c.get('type')=='image_url'],
                  'input_image_sizes':[list(img.size) for img in images],
                  'parameters':{'model':self.model,'temperature':self.temperature,'max_tokens':self.max_tokens,
                      'reasoning_effort':self.reasoning_effort,'max_image_long_side':self.max_image_long_side,
                      'response_format_json':self.response_format_json}}
        started = time.time()
        raw_text = self._post_chat(payload)
        latency = time.time() - started
        return ProviderResponse(raw_text=raw_text,model=self.model,latency_s=latency,usage=dict(self.last_usage),
                                finish_reason=self.last_finish_reason,request_metadata=metadata)

    def _post_chat(self, payload: Dict[str, Any]) -> str:
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url = url + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        attempts = 1 + max(0, self.retries)
        last_error: Optional[ProviderError] = None
        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                return self._post_once(request)
            except (ProviderTimeout, ProviderTransientError) as exc:
                last_error = exc
                if attempt < attempts:
                    wait = 10 * attempt
                    print("[warn] 第 %d/%d 次调用暂时失败（%s），%ds 后自动重试..."
                          % (attempt, attempts, exc, wait))
                    time.sleep(wait)
        raise last_error if last_error else ProviderError("视觉模型 API 调用失败")

    def _post_once(self, request: urllib.request.Request) -> str:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "ignore")[:500]
            except Exception:
                pass
            if "AllocationQuota.FreeTierOnly" in detail:
                raise ProviderConfigError("视觉模型 API 免费额度已耗尽（AllocationQuota.FreeTierOnly，HTTP 403）。请在服务控制台恢复可用额度，或在系统设置更换可用 API；本次请求未完成。")
            try:
                api_error=json.loads(detail).get('error') or {}
            except (ValueError,AttributeError):api_error={}
            if isinstance(api_error,dict) and str(api_error.get('code'))=='1113':
                raise ProviderConfigError('视觉模型 API 余额不足或无可用资源包（1113）。请在系统设置更换有额度的视觉 API；本次请求未完成，重试不能恢复额度。')
            error = ProviderTransientError if exc.code == 429 or 500 <= exc.code <= 599 else ProviderError
            raise error("视觉模型 API HTTP %s: %s" % (exc.code, detail))
        except socket.timeout:
            # Python 3.8 下 socket.timeout 不是 TimeoutError 的子类，必须单独捕获
            raise ProviderTimeout(
                "视觉模型 API 响应超时（>%ds）。高密度图纸推理慢属正常现象；可重试、"
                "调大 provider.openai_compat.timeout，或换更快的模型（如 qwen3.8-flash）。"
                % self.timeout)
        except (urllib.error.URLError, OSError) as exc:
            raise ProviderTransientError("视觉模型 API 连接失败（%s）: %s" % (self.base_url, exc))
        except ValueError as exc:
            raise ProviderError("视觉模型 API 返回非 JSON: %s" % exc)

        try:
            self.last_usage = body.get("usage") or {}
            self.last_finish_reason = body['choices'][0].get('finish_reason')
            message = body["choices"][0]["message"]
            text = message.get("content") or ""
            # 部分端点把多模态回复放在 content 列表里
            if isinstance(text, list):
                text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
            return text
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("视觉模型 API 响应结构异常: %r (%s)" % (body, exc))

    def describe(self) -> Dict[str, Any]:
        return {"provider": self.name, "model": self.model, "base_url": self.base_url,
                "api_key_source": self.api_key_source}


def _image_to_data_uri(image: Image.Image, max_long_side=2240) -> str:
    """PIL Image -> base64 PNG（控制体积：长边超过 1600px 时压缩）。"""
    img = image
    long_side = max(img.size)
    if max_long_side > 0 and long_side > max_long_side:
        scale = float(max_long_side) / long_side
        img = img.resize((max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")
