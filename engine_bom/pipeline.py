# -*- coding: utf-8 -*-
"""端到端流水线：输入 PDF/图片 -> 页面图像 -> 视觉模型识别 -> 解析/合并/校验 -> BOM 导出。

流程对应论文的四步闭环：
  Step1 文档解析结构化（ingestion）
  Step2 视觉模型识别（providers，可插拔；可选 RAG 知识注入 knowledge）
  Step3 解析与多层校验（parsing + schema.validate_components，含件号冲突检测）
  Step4 BOM 装配与导出（schema.merge_components + export）
"""
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .config import cfg_get, resolve_output_dir
from .export import export_bom
from .ingestion import IngestionError, load_document
from .knowledge import build_knowledge
from .parsing import response_to_components
from .prompts import get_prompt_builder
from .providers import ProviderError, build_provider
from .schema import BomComponent, BomDocument, merge_components, validate_components
from .agent_loop import AgentLoop, validate_bom_response
from .corrections import sha256


@dataclass
class ProcessResult(object):
    document_id: str
    source_file: str
    status: str                       # "ok" | "failed"
    bom: Optional[BomDocument] = None
    errors: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    process_time_s: float = 0.0
    agent_events: List[Dict[str, Any]] = field(default_factory=list)
    pages: List[Any] = field(default_factory=list, repr=False)


class BomPipeline(object):
    """识别流水线。config 为 engine_bom.config.load_config 的产物。"""

    def __init__(self, config: Dict[str, Any], base_dir: Optional[str] = None):
        self.config = config
        self.base_dir = base_dir or os.getcwd()
        self.provider = build_provider(config.get("provider") or {})
        self.kb = build_knowledge(config.get("knowledge") or {}, self.base_dir)
        self.prompt_builder = get_prompt_builder(str(cfg_get(config, "recognition.prompt_version", "v1")))
        self.agent = AgentLoop(self.provider, cfg_get(config, "agent_loop.max_attempts", 3))

    def _recognize(self, images, prompt, result, page_no):
        if cfg_get(self.config,'recognition.detail_crops',True) and any(max(image.size)>1200 for image in images):
            from .installation_review import review_images
            images,note=review_images(images)
            prompt+='\n【明细表原文核对】附加放大图是原页的局部，不是新页；请逐行核对序号、名称及数量。不得用相似功能名称或轴系常识替换明细表原文，不得重复计数。'+note
        outcome = self.agent.run(images, prompt, validate_bom_response)
        result.agent_events.extend(dict(event, page_no=page_no) for event in outcome.events)
        if outcome.status != "validated":
            raise ProviderError("Agent loop 校验未通过，需复核：%s" % outcome.events[-1]["errors"])
        return outcome.response, outcome.value

    # ------------------------------------------------------------------
    def process_file(self, path: str, retain_pages: bool = False) -> ProcessResult:
        path = os.path.abspath(path)
        doc_id = os.path.splitext(os.path.basename(path))[0]
        started = time.time()
        result = ProcessResult(document_id=doc_id, source_file=path, status="failed")

        try:
            pages = load_document(path, self.config.get("ingestion") or {})
        except IngestionError as exc:
            result.errors.append(str(exc))
            return result
        if retain_pages:
            result.pages = pages

        mode = str(cfg_get(self.config, "recognition.mode", "per_page"))
        trace_pages: List[Dict[str, Any]] = []
        pages_of_components: List[List[BomComponent]] = []
        try:
            if mode == "whole_doc":
                snippets = self.kb.retrieve(
                    "发动机 元器件 明细 BOM 图号 件号 数量 重量 单量 weight 材料 规格",
                    int(cfg_get(self.config, "knowledge.top_k", 3)))
                prompt = self.prompt_builder(mode="whole_doc", total_pages=len(pages),
                                             knowledge_snippets=snippets)
                resp, comps = self._recognize([getattr(p,'original_image',None) or p.image for p in pages], prompt, result, 0)
                for c in comps:
                    if c.source_page is None:
                        c.source_page = 1
                pages_of_components.append(comps)
                trace_pages.append(self._trace_entry(0, resp, len(comps), []))
            else:
                snippets = self.kb.retrieve(
                    "发动机 元器件 明细 BOM 图号 件号 数量 重量 单量 weight 材料 规格",
                    int(cfg_get(self.config, "knowledge.top_k", 3)))
                for page in pages:
                    prompt = self.prompt_builder(mode="per_page", page_no=page.page_no,
                                                 total_pages=len(pages), knowledge_snippets=snippets)
                    resp, comps = self._recognize([getattr(page,'original_image',None) or page.image], prompt, result, page.page_no)
                    for c in comps:
                        if c.source_page is None:
                            c.source_page = page.page_no
                    pages_of_components.append(comps)
                    trace_pages.append(self._trace_entry(page.page_no, resp, len(comps), []))
        except ProviderError as exc:
            result.errors.append(str(exc))
            result.process_time_s = time.time() - started
            import json
            failed_dir = os.path.join(resolve_output_dir(self.config), "traces")
            os.makedirs(failed_dir, exist_ok=True)
            with open(os.path.join(failed_dir, doc_id + ".failed.json"), "w", encoding="utf-8") as f:
                json.dump({"status": "failed", "errors": result.errors,
                           "agent_events": result.agent_events}, f, ensure_ascii=False, indent=2)
            return result

        policy = str(cfg_get(self.config, "recognition.duplicate_quantity_policy", "keep_max"))
        preserve_rows = bool(cfg_get(self.config, "recognition.preserve_printed_rows", True))
        if preserve_rows:
            merged = [c for page_comps in pages_of_components for c in page_comps]
            merge_notes = []
        else:
            merged, merge_notes = merge_components(pages_of_components, quantity_policy=policy)

        min_conf = float(cfg_get(self.config, "recognition.min_confidence", 0.0) or 0.0)
        if min_conf > 0:
            kept, dropped = [], []
            for c in merged:
                (dropped if (c.confidence is not None and c.confidence < min_conf) else kept).append(c)
            for c in dropped:
                merge_notes.append("置信度低于阈值已过滤: %s (%.2f)" % (c.display_name(), c.confidence or 0))
            merged = kept

        strict = bool(cfg_get(self.config, "validation.strict", False))
        issues = validate_components(merged, strict=strict,
                                     allow_repeated_rows=preserve_rows)

        bom = BomDocument(
            document_id=doc_id,
            source_file=os.path.basename(path),
            generated_at=datetime.now().isoformat(timespec="seconds"),
            model_info={
                **self.provider.describe(),
                "prompt_version": str(cfg_get(self.config, "recognition.prompt_version", "v1")),
                "recognition_mode": mode,
                "preserve_printed_rows": preserve_rows,
                "knowledge_base": self.kb.describe(),
                "pages": len(pages),
                "source_sha256": sha256(path),
                "agent_loop": {"status": "validated", "events": result.agent_events},
            },
            components=merged,
            validation_issues=sorted(set(merge_notes + issues)),
            process_time_s=round(time.time() - started, 3),
        )

        out_dir = resolve_output_dir(self.config)
        from .assembly import infer_assembly
        bom.assembly = infer_assembly(self.provider, [getattr(p,'original_image',None) or p.image for p in pages],
                                       [c.to_dict() for c in merged], self.config.get('assembly'))
        for _w in (bom.assembly.get('warnings') or []):
            bom.validation_issues.append('装配层级：' + _w)
        from .assembly import update_quantity_checks
        checked = {'assembly': bom.assembly, 'components': [c.to_dict() for c in merged],
                   'validation_issues': bom.validation_issues}
        update_quantity_checks(checked)
        bom.validation_issues = checked['validation_issues']
        formats = [str(x) for x in cfg_get(self.config, "output.formats", ["json"]) or []]
        result.outputs = export_bom(bom, os.path.join(out_dir, doc_id), formats)
        self._write_trace(out_dir, doc_id, bom, trace_pages, result.outputs)

        result.status = "ok"
        result.bom = bom
        result.process_time_s = bom.process_time_s or 0.0
        return result

    # ------------------------------------------------------------------
    def process_many(self, paths: List[str],
                     on_result: Optional[Callable[[ProcessResult], None]] = None) -> List[ProcessResult]:
        results: List[ProcessResult] = []
        for path in paths:
            try:
                res = self.process_file(path)
            except Exception as exc:  # 单文件崩溃不影响批量
                res = ProcessResult(document_id=os.path.splitext(os.path.basename(path))[0],
                                    source_file=path, status="failed", errors=["未捕获异常: %r" % exc])
            results.append(res)
            if on_result:
                on_result(res)
        return results

    # ------------------------------------------------------------------
    @staticmethod
    def _trace_entry(page_no: int, resp, n_components: int, warnings: List[str]) -> Dict[str, Any]:
        return {
            "page_no": page_no,
            "model": resp.model,
            "latency_s": round(resp.latency_s, 3),
            "usage": resp.usage,
            "n_components": n_components,
            "warnings": warnings,
            "raw_text": resp.raw_text,
        }

    @staticmethod
    def _write_trace(out_dir: str, doc_id: str, bom: BomDocument,
                     trace_pages: List[Dict[str, Any]], outputs: List[str]) -> None:
        """保存原始模型输出，便于调试与人工复核（对应论文 human-in-the-loop 的审计日志）。"""
        trace_dir = os.path.join(out_dir, "traces")
        if not os.path.isdir(trace_dir):
            os.makedirs(trace_dir, exist_ok=True)
        trace = {
            "document_id": doc_id,
            "source_file": bom.source_file,
            "generated_at": bom.generated_at,
            "model_info": bom.model_info,
            "summary": bom.summary(),
            "validation_issues": bom.validation_issues,
            "outputs": outputs,
            "pages": trace_pages,
        }
        import json
        path = os.path.join(trace_dir, "%s.trace.json" % doc_id)
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(trace, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            print("[warn] trace 写入失败 %s: %s" % (path, exc))


def print_result_summary(res: ProcessResult) -> None:
    """控制台打印单文档处理结果。"""
    if res.status != "ok":
        print("[FAIL] %s -> %s" % (res.document_id, "; ".join(res.errors)))
        return
    bom = res.bom
    print("[OK] %s: %d 个元器件, 总数量 %d, 耗时 %.1fs" % (
        res.document_id, bom.total_components, bom.total_quantity, res.process_time_s))
    for c in bom.components:
        conf = "" if c.confidence is None else " (%.2f)" % c.confidence
        print("  %2d. %-28s %-14s x%-4s %s" % (
            c.item_no or 0, c.display_name(), c.part_number or "-",
            str(c.quantity if c.quantity is not None else "?"), (c.material or "") + conf))
    if bom.validation_issues:
        print("  校验提示: %d 条（详见 JSON）" % len(bom.validation_issues))
    for out in res.outputs:
        print("  导出: %s" % out)
