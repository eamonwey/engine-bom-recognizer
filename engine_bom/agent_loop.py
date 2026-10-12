"""Bounded observe/validate/retry loop. Never treats exhausted validation as success."""
import json
from dataclasses import dataclass, field
from .parsing import extract_json_payload, response_to_components
from .providers import ProviderError
from .schema import validate_components


@dataclass
class LoopResult:
    response: object = None
    value: object = None
    status: str = "needs_review"
    events: list = field(default_factory=list)


class AgentLoop:
    def __init__(self, provider, max_attempts=3):
        self.provider = provider
        self.max_attempts = max(1, min(int(max_attempts), 5))

    def run(self, images, prompt, validator):
        result = LoopResult()
        self.last_result = result
        feedback = ""
        for attempt in range(1, self.max_attempts + 1):
            strategy = "original"
            observed = images
            if attempt == 2 and validator is validate_bom_response:
                from PIL import ImageOps
                observed = [ImageOps.autocontrast(image.convert("RGB")) for image in images]
                strategy = "contrast_enhancement"
            elif attempt >= 3 and validator is validate_bom_response and len(images) == 1:
                image = images[0]
                w, h = image.size
                observed = [image] + [image.crop(box) for box in
                    [(0, 0, w//2, h//2), (w//2, 0, w, h//2),
                     (0, h//2, w//2, h), (w//2, h//2, w, h)]]
                strategy = "original_with_quadrant_crops"
                feedback += "\n第一张是整页，其余四张是同页左上、右上、左下、右下放大块。只返回该页完整BOM，同件不得重复计数。"
            try:
                response = self.provider.analyze(observed, prompt + feedback)
            except ProviderError as exc:
                result.events.append({'attempt': attempt, 'action': 'provider_error',
                                      'strategy': strategy, 'errors': [str(exc)]})
                raise
            if getattr(response,'finish_reason',None)=='length':
                # A validator may stash a parsed tree as a fallback. Never let
                # even valid-looking truncated JSON populate that stash.
                value,errors={},['模型输出达到长度上限，不能认为结果完整；缩短证据文字并完整重读']
            else:
                value, errors = validator(response.raw_text)
            result.response, result.value = response, value
            result.events.append({"attempt": attempt, "action": "extract_validate",
                                  "strategy": strategy,
                                  "errors": errors, "raw_text": response.raw_text,
                                  "model": response.model,
                                  "finish_reason":getattr(response,'finish_reason',None),
                                  "request_metadata":getattr(response,'request_metadata',{}),
                                  "usage":getattr(response,'usage',{})})
            if not errors:
                result.status = "validated"
                return result
            feedback = "\n上一次输出未通过校验。重新阅读原图，返回完整 JSON，禁止依据错误提示猜造信息。\n校验问题：" + json.dumps(errors, ensure_ascii=False)
        return result


def validate_bom_response(raw):
    payload, errors = extract_json_payload(raw)
    if not isinstance(payload, (dict, list)):
        return [], errors or ["输出必须是 JSON 对象或数组"]
    if isinstance(payload, dict) and not isinstance(payload.get("components"), list):
        return [], ["components 必须是数组"]
    components, warnings = response_to_components(raw)
    # A valid empty table is allowed (a detail drawing may have no BOM).
    # Drawing defects and uncertain rows belong in human review. Preserve
    # their values and flags; never feed suggested standard numbers into retries.
    review_only = ("数量非正数", "件号重复:", "疑似无明细表页的占位行", "标准号引用疑似错误:")
    structural = [e for e in validate_components(components, strict=False)
                  if not any(marker in e for marker in review_only)]
    # Alphabetic/footnote item labels cannot fit the integer schema; preserve
    # their exact text in remark and leave item_no unknown rather than dropping
    # the entire correctly extracted table or inventing a numeric identifier.
    # JSON 自动修复成功属提示而非错误，不作废本轮（已解析出 components）。
    fatal_warnings = [w for w in warnings
                      if "非整数原始序号已保留:" not in w and "已自动修复" not in w]
    return components, fatal_warnings + structural


def validate_issues_response(raw):
    payload, warnings = extract_json_payload(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
        return [], ["必须包含 issues 数组"]
    errors = []
    for i, issue in enumerate(payload["issues"]):
        if not isinstance(issue, dict):
            errors.append("issue %d 必须是对象" % i)
            continue
        if issue.get("err_id") not in ["ERR-%02d" % n for n in range(1, 11)]:
            errors.append("issue %d 错误类型无效" % i)
        if not issue.get("message") or not issue.get("evidence"):
            errors.append("issue %d 缺少问题描述或图面证据" % i)
        page = issue.get("source_page")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            errors.append("issue %d 缺少合法页码" % i)
    return payload["issues"], errors
