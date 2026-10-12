# -*- coding: utf-8 -*-
"""Web 服务（纯标准库实现，零额外依赖，符合内网部署约束 C-01/C-02）。

启动:
  python -m engine_bom.webapp --host 0.0.0.0 --port 8787

页面: http://127.0.0.1:8787/

REST API 一览:
  POST /api/jobs/bom       上传图纸 -> BOM 识别 + 标题栏 + 图纸检查（异步任务）
  POST /api/jobs/doc       上传文档 -> 关键要素提取（异步任务）
  POST /api/jobs/compare   上传两版文件 -> 变更对比（异步任务）
  GET  /api/compare/<id>/ecn.md                  ECN 变更单草稿下载
  GET  /api/history                              变更历史
  POST /api/jobs/inspect   上传图纸 -> 规则 + VLM 混合检查（异步任务）
  GET  /api/jobs           任务列表
  GET  /api/jobs/<id>      任务状态与结果
  POST /api/bom/save       人工复核保存（写入修正记录，供模型迭代）
  POST /api/doc/save       文档提取结果人工复核保存
  GET  /api/export/bom/<id>?fmt=json|csv|xlsx    BOM 下载
  GET  /api/export/doc/<id>?fmt=json|xlsx        要素提取下载
  GET  /api/reviewlog                            人工修正记录
  GET  /api/status                               当前模型配置状态
  POST /api/config                         修改运行时配置（provider/base_url/model）
"""
import csv
import copy
import functools
import tempfile
import html
import io
import json
import os
import re
import secrets
import shutil
import socket
import sys
import threading
import time
import urllib.parse
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import DEFAULT_CONFIG, deep_merge, load_config
from .export import write_csv, write_json, write_xlsx
from .schema import BomDocument, components_from_payload

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(_ROOT, "static")
DATA_DIR = os.path.join(_ROOT, "data")
JOBS_DIR = os.path.join(DATA_DIR, "web_jobs")
SETTINGS_PATH = os.path.join(DATA_DIR, "web_settings.json")
CONFIG_PATH = None
HISTORY_PATH = os.path.join(DATA_DIR, "change_history.json")
DETECTION_HISTORY_DIR = os.path.join(DATA_DIR, "detection_history")
REVIEWLOG_PATH = os.path.join(DATA_DIR, "review_log.json")

_jobs: dict = {}
_jobs_lock = threading.RLock()
_log_lock = threading.Lock()
_API_TOKEN = os.environ.get("ENGINE_BOM_API_TOKEN") or secrets.token_urlsafe(32)
MAX_REQUEST_BYTES = int(os.environ.get("ENGINE_BOM_MAX_UPLOAD_MB", "100")) * 1024 * 1024
JOB_TTL_SECONDS = int(os.environ.get("ENGINE_BOM_JOB_TTL_HOURS", "24")) * 3600
MAX_RETAINED_JOBS = int(os.environ.get("ENGINE_BOM_MAX_JOBS", "200"))


class RequestTooLarge(ValueError):
    pass


class _UploadedPart(object):
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self.file = io.BytesIO(content)


class _FormData(dict):
    def getvalue(self, name: str, default=None):
        value = self.get(name, default)
        return default if isinstance(value, _UploadedPart) else value


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def load_web_config() -> dict:
    if CONFIG_PATH:
        # Explicit deployment profile is authoritative, not cloud web settings.
        return load_config(CONFIG_PATH)
    cfg_path = os.path.join(_ROOT, "config.yaml")
    cfg = load_config(cfg_path) if os.path.exists(cfg_path) else load_config()
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                cfg = deep_merge(cfg, json.load(f))
        except (ValueError, OSError):
            pass
    return cfg


def save_web_settings(patch: dict) -> None:
    current = {}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                current = json.load(f)
        except (ValueError, OSError):
            pass
    merged = deep_merge(current, patch)
    parent = os.path.dirname(SETTINGS_PATH)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 任务管理
# ---------------------------------------------------------------------------

def _create_job(kind: str) -> str:
    _cleanup_jobs()
    job_id = time.strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3)
    job_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    with _jobs_lock:
        _jobs[job_id] = {"id": job_id, "kind": kind, "status": "running",
                         "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "created_ts": time.time(),
                         "dir": job_dir, "result": None, "error": None}
    return job_id


def _cleanup_jobs(now: float = None) -> None:
    """清理过期或超出容量的已完成任务；运行中的任务永不删除。"""
    now = time.time() if now is None else now
    removed = []
    with _jobs_lock:
        terminal = [job for job in _jobs.values() if job.get("status") != "running"]
        terminal.sort(key=lambda job: float(job.get("created_ts") or 0))
        expired = {job["id"] for job in terminal
                   if now - float(job.get("created_ts") or 0) > JOB_TTL_SECONDS}
        overflow = max(0, len(_jobs) - MAX_RETAINED_JOBS - len(expired))
        eligible = [job["id"] for job in terminal if job["id"] not in expired]
        expired.update(eligible[:overflow])
        for job_id in expired:
            job = _jobs.pop(job_id, None)
            if job and job.get("dir"):
                removed.append(job["dir"])
    for path in removed:
        shutil.rmtree(path, ignore_errors=True)


def _cleanup_orphan_job_dirs(now: float = None) -> None:
    now = time.time() if now is None else now
    if not os.path.isdir(JOBS_DIR):
        return
    for name in os.listdir(JOBS_DIR):
        path = os.path.join(JOBS_DIR, name)
        try:
            if os.path.isdir(path) and now - os.path.getmtime(path) > JOB_TTL_SECONDS:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


def _sync_detection_history(job):
    """任务完成或 BOM/装配编辑后，刷新该任务的检测历史（同 job_id 覆盖）。"""
    try:
        from .history import append_record, build_record
        record = build_record(job.get("id"), "bom", job.get("source_file"),
                              result=job.get("result"), error=job.get("error"),
                              finished_at=job.get("finished_at"))
        append_record(DETECTION_HISTORY_DIR, record,
                      full_result=None if job.get("error") else job.get("result"))
    except Exception as exc:  # noqa: BLE001 历史绝不能拖垮任务收尾
        print("[warn] 检测历史记录失败: %s" % exc)


def _finish_job(job_id: str, result: dict = None, error: str = None) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["status"] = "done" if not error else "failed"
        job["result"] = result
        job["error"] = error
        job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        snapshot = {k: v for k, v in job.items() if k != "dir"}
    if result is not None:
        if job.get('kind')=='bom' and isinstance(result,dict):
            from .run_consistency import compare_runs
            result['run_consistency']=compare_runs(result,DETECTION_HISTORY_DIR,exclude_job=job_id)
        path = os.path.join(job["dir"], "result.json")
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            print("[warn] 任务结果写入失败: %s" % exc)
    if job.get("kind") == "bom":
        _sync_detection_history(snapshot)


def _run_async(job_id: str, fn) -> None:
    def worker():
        try:
            result = fn()
            _finish_job(job_id, result=result)
        except Exception as exc:  # 任何异常都落到任务状态，前端可见
            import traceback
            traceback.print_exc()
            _finish_job(job_id, error="%s: %s" % (type(exc).__name__, exc))
    threading.Thread(target=worker, daemon=True).start()


def _save_upload(job_dir: str, form, field: str) -> str:
    item = form[field]
    if not getattr(item, "filename", None):
        raise ValueError("缺少上传文件字段 %s" % field)
    filename = os.path.basename(item.filename)
    if not filename or filename in ('.', '..') or ':' in filename:
        raise ValueError('上传文件名无效')
    # Each form field owns a directory: old/new revisions commonly have the same filename.
    upload_dir = os.path.join(job_dir, field)
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, filename)
    with open(path, "wb") as f:
        f.write(item.file.read())
    return path


def _prepare_upload_job(kind, form, fields):
    """Keep synchronous upload failures out of the running-job registry."""
    for field in fields:
        if field not in form or not getattr(form[field], 'filename', None):
            raise ValueError('缺少上传文件字段 %s' % field)
    job_id = _create_job(kind)
    try:
        paths = [_save_upload(_jobs[job_id]['dir'], form, field) for field in fields]
    except Exception as exc:
        _finish_job(job_id, error=str(exc) or type(exc).__name__)
        raise
    return job_id, paths


def _safe_review_path(parent: str, identifier: str, prefix: str = "") -> str:
    """把用户标识限制为 reviewed 目录内的单一 JSON 文件名。"""
    value = str(identifier or "").strip()
    if (not value or value in (".", "..") or "\x00" in value
            or any(ch in value for ch in ("/", "\\", ":"))):
        raise ValueError("文件标识包含非法路径字符")
    safe = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]", "_", value)
    if not safe or safe in (".", ".."):
        raise ValueError("文件标识无效")
    root = os.path.realpath(parent)
    output = os.path.realpath(os.path.join(root, prefix + safe + ".json"))
    try:
        inside = os.path.commonpath([root, output]) == root
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("保存路径超出复核目录")
    return output


def _atomic_json(path, value):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.pending-', suffix='.json', dir=parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _append_log(path: str, record: dict) -> None:
    # ThreadingHTTPServer handlers share the entire read-modify-replace critical section.
    with _log_lock:
        records = []
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as handle:
                records = json.load(handle)
            if not isinstance(records, list):
                raise ValueError('历史日志不是数组，拒绝覆盖原始记录')
        records.append(dict(record, time=time.strftime('%Y-%m-%d %H:%M:%S')))
        _atomic_json(path, records)


def _serialized_edit(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        # Keep validation, persistence and in-memory update in one task-edit transaction.
        with _jobs_lock:
            return function(*args, **kwargs)
    return wrapped


def _commit_bom_edit(updates, record):
    """Serialize audit publication; roll back file mirrors on ordinary I/O failure."""
    with _log_lock:
        records = []
        if os.path.isfile(REVIEWLOG_PATH):
            with open(REVIEWLOG_PATH, encoding='utf-8') as handle:
                records = json.load(handle)
            if not isinstance(records, list):
                raise ValueError('历史日志不是数组，拒绝覆盖原始记录')
        records.append(dict(record, time=time.strftime('%Y-%m-%d %H:%M:%S')))
        updates = list(updates) + [(REVIEWLOG_PATH, records)]
        originals = {}
        for path, value in updates:
            json.dumps(value, allow_nan=False)
            if os.path.isfile(path):
                with open(path, encoding='utf-8') as handle:
                    originals[path] = json.load(handle)
        written = []
        try:
            for path, value in updates:
                _atomic_json(path, value)
                written.append(path)
        except Exception:
            for path in reversed(written):
                if path in originals:
                    _atomic_json(path, originals[path])
                else:
                    os.unlink(path)
            raise


def _save_result_section(job_id, kind, section, value):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job or job.get('kind') != kind or job.get('status') != 'done':
            raise ValueError('任务不存在、类型不符或未完成')
        result = copy.deepcopy(job['result'])
        if section == 'assembly':
            result['bom']['assembly'] = value
        else:
            result[section] = value
        _atomic_json(os.path.join(job['dir'], 'result.json'), result)
        job['result'] = result
    if kind == 'bom':
        _sync_detection_history({k: v for k, v in job.items() if k != 'dir'})



# ---------------------------------------------------------------------------
# 任务实现
# ---------------------------------------------------------------------------

def _anchor_knowledge_path(cfg):
    path = str((cfg.get("knowledge") or {}).get("path") or "")
    if path and not os.path.isabs(path):
        cfg.setdefault("knowledge", {})["path"] = os.path.join(_ROOT, path)


def balloon_bom_mismatch_note(balloons, components):
    """球标序号与明细行不一致时返回提示语（丢行/重新编号的确定性信号）；一致或数据不足返回 None。"""
    from .inspect_rules import _coerce_item_no
    raw = list(balloons or []) + [c.get("item_no") for c in (components or [])]
    if any(isinstance(v, (int, float)) and not isinstance(v, bool)
           and _coerce_item_no(v) is None for v in raw):
        return "球标或明细序号含非法数值，无法确认对应关系，请对照原图核实"
    bals = sorted({n for b in (balloons or []) if (n := _coerce_item_no(b)) is not None})
    nos = sorted({n for c in (components or []) if (n := _coerce_item_no(c.get("item_no"))) is not None})
    if bals and not nos:
        # 有球标但没有任何带序号的明细行：本页可能没有明细表（BOM 在其他图号上），如实提示
        return ("图上有 %d 个引出序号，但明细清单中没有可对应的序号行——本页可能没有明细表"
                "（BOM 或在图纸注明的其他图号/图纸上），请核对原图。" % len(bals))
    if not bals:
        return None  # 没检出球标时不判不一致（球标检测本身可能为空）
    missing = [b for b in bals if b not in nos]
    extra = [n for n in nos if n not in bals]
    if not missing and not extra:
        return None
    parts = []
    if missing:
        parts.append("球标 %s 无对应明细行" % missing)
    if extra:
        parts.append("明细行 %s 无对应球标" % extra)
    return "球标与明细栏不一致: %s；可能存在丢行或重新编号，请对照原图核对" % "；".join(parts)


def _job_bom(job_dir: str, file_path: str, options: dict) -> dict:
    from .pipeline import BomPipeline
    from .titleblock import extract_dims_and_balloons, extract_titleblock

    cfg = load_web_config()
    if options.get("provider"):
        cfg.setdefault("provider", {})["name"] = options["provider"]
    if options.get("preprocess"):
        cfg.setdefault("ingestion", {})["preprocess"] = {
            "enabled": True, **{k: True for k in ("deskew", "denoise", "binarize", "contrast")
                                if options["preprocess"].get(k)}}

    # 相对的知识库路径必须相对项目根解析；base_dir 传的是任务目录，
    # 直接传下去会让 FileKnowledgeBase 在任务目录里找规则文件（静默 0 条）。
    _anchor_knowledge_path(cfg)
    pipeline = BomPipeline(cfg, base_dir=job_dir)
    result = pipeline.process_file(file_path, retain_pages=True)
    if result.status != "ok":
        raise RuntimeError("; ".join(result.errors))

    bom = result.bom.to_dict()
    pages = result.pages
    images = [getattr(p,'original_image',None) or p.image for p in pages]
    import time as _time
    _t_review = _time.time()
    from .drawing_layout import locate_regions, titleblock_images, titleblock_page_numbers
    layout = locate_regions(pipeline.provider, images, (cfg.get('enterprise') or {}).get('drawing_template'))
    title_images = titleblock_images(images, layout['regions'])
    tb = extract_titleblock(pipeline.provider, title_images, total_pages=len(images),
                           source_page_numbers=titleblock_page_numbers(images, layout['regions']))
    dims = extract_dims_and_balloons(pipeline.provider, images)
    from .hybrid_inspection import inspect
    from .engineering_checks import inspection_config
    inspection_cfg = inspection_config(cfg, file_path, tb['fields'])
    inspection = inspect(pipeline.provider, images, tb["fields"], bom["components"],
                         dims.get("dimensions"), dims.get("balloons"), inspection_cfg)
    inspection['dimension_extraction'] = {key:dims.get(key) for key in ('status','warnings','events','model')}
    # BOM 管线计时在 bom.process_time_s；审图（定位/标题栏/尺寸/纠错）单独计时，
    # 这阶段在大图上往往远慢于识别本身，不让它隐身。
    inspection["process_time_s"] = round(_time.time() - _t_review, 1)
    note = balloon_bom_mismatch_note(dims.get("balloons"), bom.get("components"))
    if note:
        bom.setdefault("validation_issues", []).append(note)
    issues = inspection["issues"]
    from .corrections import sha256
    return {"source_sha256": sha256(file_path), "document_id": result.document_id, "bom": bom, "title_block": tb["fields"],
            "missing_required": tb["missing_required"],
            "dimensions": dims.get("dimensions"), "balloons": dims.get("balloons"),
            "issues": issues, "outputs": result.outputs,
            "model_info": bom.get("model_info"), "inspection": inspection, "layout": layout}


def _job_doc(job_dir: str, file_path: str, options: dict) -> dict:
    from .docextract import extract_elements, parse_document
    from .providers import build_provider

    cfg = load_web_config()
    if options.get("provider"):
        cfg.setdefault("provider", {})["name"] = options["provider"]
    provider = build_provider(cfg.get("provider") or {})

    parsed = parse_document(file_path)
    page_images = []
    if parsed.get("kind") in ("pages", "mixed") or parsed.get('format') == 'pdf':
        from .ingestion import load_document
        try:
            page_images = [p.image for p in load_document(file_path, cfg.get("ingestion") or {})]
        except Exception as exc:
            print("[warn] 页面渲染失败，仅用文本提取: %s" % exc)
    extraction = extract_elements(provider, parsed, page_images, cfg.get("enterprise"))
    return {"file_name": os.path.basename(file_path), "format": parsed.get("format"),
            "n_pages": parsed.get("n_pages"), "text_chars": len(parsed.get("text") or ""),
            "extraction": extraction, "model": provider.describe()}


def _job_compare(job_dir: str, before_path: str, after_path: str, options: dict) -> dict:
    from .changedetect import align_and_diff, extract_text, summarize_changes

    before = extract_text(before_path)
    after = extract_text(after_path)
    items = align_and_diff(before["paragraphs"], after["paragraphs"],
                           ignore_format=bool(options.get("ignore_format", True)))
    for item in items:
        for side, source in [('before', before), ('after', after)]:
            match = re.fullmatch(r'第(\d+)段', item.get('location_' + side, ''))
            blocks = source.get('blocks') or []
            if match and int(match.group(1)) <= len(blocks):
                block = blocks[int(match.group(1))-1]
                item['source_' + side] = block
                if block.get('source_page'):
                    item['location_' + side] = '第%d页 / %s' % (block['source_page'], block['id'])
    summary = summarize_changes(items)
    from .impact import analyze_impact, load_index
    cfg = load_web_config()
    index_path = (cfg.get('impact') or {}).get('index_path', 'data/knowledge/associations.json')
    if not os.path.isabs(index_path):
        index_path = os.path.join(_ROOT, index_path)
    index = load_index(index_path) if os.path.isfile(index_path) else {'objects': []}
    impact = analyze_impact(items, index)
    from .corrections import sha256
    _append_log(HISTORY_PATH, {'action':'compare', 'before_name':os.path.basename(before_path),
                'after_name':os.path.basename(after_path), 'before_sha256':sha256(before_path),
                'after_sha256':sha256(after_path), 'summary':summary, 'items':items, 'impact':impact})
    return {
        "before": {"file_name": os.path.basename(before_path), "n_paragraphs": len(before["paragraphs"]),
                   "format": before["format"]},
        "after": {"file_name": os.path.basename(after_path), "n_paragraphs": len(after["paragraphs"]),
                  "format": after["format"]},
        "items": items, "summary": summary, "impact": impact,
    }


def _job_inspect(job_dir: str, file_path: str, options: dict) -> dict:
    from .ingestion import load_document
    from .inspect_rules import run_all_checks
    from .pipeline import BomPipeline
    from .providers import build_provider
    from .titleblock import extract_dims_and_balloons, extract_titleblock

    cfg = load_web_config()
    if options.get("provider"):
        cfg.setdefault("provider", {})["name"] = options["provider"]
    _anchor_knowledge_path(cfg)
    pages = load_document(file_path, cfg.get("ingestion") or {})
    images = [getattr(p,'original_image',None) or p.image for p in pages]
    provider = build_provider(cfg.get("provider") or {})

    tb = extract_titleblock(provider, images[-1:], total_pages=len(images))
    dims = extract_dims_and_balloons(provider, images)
    bom_comps: list = []
    try:
        pipeline = BomPipeline(cfg, base_dir=job_dir)
        result = pipeline.process_file(file_path)
        if result.status == "ok":
            bom_comps = result.bom.to_dict()["components"]
    except Exception as exc:
        print("[warn] BOM 识别失败，仅检查标题栏/尺寸: %s" % exc)
    from .hybrid_inspection import inspect
    from .engineering_checks import inspection_config
    inspection = inspect(provider, images, tb["fields"], bom_comps,
                         dims.get("dimensions"), dims.get("balloons"), inspection_config(cfg, file_path, tb['fields']))
    inspection['dimension_extraction'] = {key:dims.get(key) for key in ('status','warnings','events','model')}
    issues = inspection["issues"]
    return {"document_id": os.path.splitext(os.path.basename(file_path))[0],
            "source_sha256": __import__("engine_bom.corrections",fromlist=["sha256"]).sha256(file_path),
            "title_block": tb["fields"], "missing_required": tb["missing_required"],
            "dimensions": dims.get("dimensions"), "balloons": dims.get("balloons"),
            "issues": issues, "n_bom_components": len(bom_comps),
            "model": provider.describe(), "inspection": inspection}


# ---------------------------------------------------------------------------
# BOM dict -> BomDocument（导出用）
# ---------------------------------------------------------------------------

def _bom_document_from(data: dict) -> BomDocument:
    comps, _ = components_from_payload(data.get("components") or [])
    return BomDocument(document_id=str(data.get("document_id") or "bom"),
                       components=comps)


def _xlsx_bytes(rows, headers) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(headers)
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---------- 基础 ----------
    def _send(self, code: int, body: bytes, ctype: str,
              filename: str = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            quoted = urllib.parse.quote(filename)
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''%s" % quoted)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' blob: data:; "
                         "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj: dict, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json_body(self) -> dict:
        ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            raise ValueError("JSON 接口要求 Content-Type: application/json")
        body = self._read_request_body()
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except ValueError:
            raise ValueError("请求 JSON 格式无效")

    def _read_request_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("Content-Length 无效")
        if length < 0:
            raise ValueError("Content-Length 无效")
        if length > MAX_REQUEST_BYTES:
            raise RequestTooLarge("请求超过 %d MB 上限" % (MAX_REQUEST_BYTES // 1024 // 1024))
        return self.rfile.read(length) if length else b""

    def _form(self) -> _FormData:
        ctype = self.headers.get("Content-Type", "")
        if not ctype.lower().startswith("multipart/form-data"):
            raise ValueError("上传接口要求 multipart/form-data")
        raw = self._read_request_body()
        envelope = ("Content-Type: %s\r\nMIME-Version: 1.0\r\n\r\n" % ctype).encode("utf-8") + raw
        message = BytesParser(policy=policy.default).parsebytes(envelope)
        if not message.is_multipart():
            raise ValueError("multipart 请求格式无效")
        form = _FormData()
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            payload = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename is not None:
                form[name] = _UploadedPart(filename, payload)
            else:
                charset = part.get_content_charset() or "utf-8"
                form[name] = payload.decode(charset, errors="replace")
        return form

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-API-Token", "")
        return bool(supplied) and secrets.compare_digest(supplied, _API_TOKEN)

    def log_message(self, fmt, *args):  # 精简日志
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---------- 路由 ----------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/" or path == "/index.html":
            return self._serve_static("index.html")
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        try:
            if path.startswith('/api/reviews/'):
                if not self._authorized():
                    return self._json({"error": "请求令牌无效，请刷新页面后重试"}, 403)
                self._review_actor()
                from .review_workflow import ReviewStore
                result = ReviewStore(os.path.join(DATA_DIR, 'reviews.sqlite')).get(urllib.parse.unquote(path.rsplit('/', 1)[-1]))
                return self._json(result or {'state': 'draft', 'revision': 0})
            if path == "/api/jobs":
                return self._api_jobs()
            if path.startswith("/api/jobs/"):
                return self._api_job_detail(path.rsplit("/", 1)[-1])
            if path.startswith("/api/corrections/"):
                job = _jobs.get(path.rsplit("/", 1)[-1])
                if not job or job["kind"] != "correct" or job["status"] != "done":
                    return self._json({"error": "修订不存在或未完成"}, 404)
                output = job["result"]["output"]
                with open(output, "rb") as f:
                    return self._send(200, f.read(), "application/pdf" if output.endswith(".pdf") else "image/png")
            if path.startswith("/api/pages/"):
                job = _jobs.get(path.rsplit("/", 1)[-1])
                if not job or not job.get("source_file"):
                    return self._json({"error": "原图不存在"}, 404)
                from .ingestion import load_document
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                page_no = int(query.get("page", ["1"])[0])
                preview_config = deep_merge(DEFAULT_CONFIG["ingestion"], {"dpi":150,"max_image_long_side":2240,"preprocess":{"enabled":False}})
                pages = load_document(job["source_file"], preview_config)
                if page_no < 1 or page_no > len(pages):
                    return self._json({"error":"页码超出范围"},400)
                buffer = io.BytesIO()
                pages[page_no-1].image.save(buffer, format="PNG")
                return self._send(200, buffer.getvalue(), "image/png")
            if path.startswith("/api/export/bom/"):
                return self._api_export_bom(path.rsplit("/", 1)[-1])
            if path.startswith("/api/export/doc/"):
                return self._api_export_doc(path.rsplit("/", 1)[-1])
            if path.startswith("/api/compare/") and path.endswith("/ecn.md"):
                return self._api_ecn(path.split("/")[3])
            if path == "/api/history":
                return self._api_history()
            if path == "/api/detection_history":
                return self._api_detection_history()
            if path.startswith("/api/detection_history/"):
                return self._api_detection_history_detail(
                    urllib.parse.unquote(path.rsplit("/", 1)[-1]))
            if path == "/api/reviewlog":
                return self._api_reviewlog()
            if path == "/api/status":
                return self._api_status()
        except PermissionError as exc:
            return self._json({"error": str(exc)}, 403)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return self._json({"error": str(exc)}, 500)
        self._json({"error": "not found: %s" % path}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._authorized():
            return self._json({"error": "请求令牌无效，请刷新页面后重试"}, 403)
        try:
            if path == '/api/enterprise/profile':
                from .enterprise import validate_profile
                profile = validate_profile(self._read_json_body())
                save_web_settings({'enterprise': profile})
                return self._json({'ok': True})
            if path == '/api/reviews/transition':
                return self._api_review_transition()
            if path == '/api/assembly/save':
                return self._api_assembly_save()
            if path == "/api/jobs/bom":
                return self._api_job_bom()
            if path == "/api/jobs/doc":
                return self._api_job_doc()
            if path == "/api/jobs/compare":
                return self._api_job_compare()
            if path == '/api/impact/index':
                return self._api_impact_index()
            if path == "/api/jobs/inspect":
                return self._api_job_inspect()
            if path == "/api/jobs/correct":
                return self._api_job_correct()
            if path == "/api/bom/save":
                return self._api_bom_save()
            if path == "/api/doc/save":
                return self._api_doc_save()
            if path == "/api/config":
                return self._api_config()
            if path == "/api/test-connection":
                return self._api_test_connection()
        except PermissionError as exc:
            return self._json({"error": str(exc)}, 403)
        except RequestTooLarge as exc:
            return self._json({"error": str(exc)}, 413)
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            return self._json({"error": str(exc)}, 500)
        self._json({"error": "not found: %s" % path}, 404)

    # ---------- 静态 ----------
    def _serve_static(self, rel: str) -> None:
        rel = rel.lstrip("/")
        root = os.path.realpath(STATIC_DIR)
        full = os.path.realpath(os.path.join(root, rel))
        try:
            inside = os.path.commonpath([root, full]) == root
        except ValueError:
            inside = False
        if not inside:
            return self._send(403, b"forbidden", "text/plain")
        if not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        ext = os.path.splitext(full)[1].lower()
        ctypes = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                  ".css": "text/css; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml",
                  ".pdf": "application/pdf", ".json": "application/json; charset=utf-8"}
        with open(full, "rb") as f:
            body = f.read()
        if rel in ("index.html", ""):
            token = html.escape(_API_TOKEN, quote=True).encode("utf-8")
            body = body.replace(b"__ENGINE_BOM_API_TOKEN__", token)
        self._send(200, body, ctypes.get(ext, "application/octet-stream"))

    # ---------- 任务端点 ----------
    def _api_job_bom(self):
        form = self._form()
        options = json.loads(form.getvalue("options") or "{}") if hasattr(form, "getvalue") else {}
        if not isinstance(options, dict) or ('preprocess' in options and not isinstance(options['preprocess'], dict)):
            raise ValueError('options 和 preprocess 必须为 JSON 对象')
        job_id, (file_path,) = _prepare_upload_job('bom', form, ['file'])
        _jobs[job_id]["source_file"] = file_path
        _run_async(job_id, lambda: _job_bom(_jobs[job_id]["dir"], file_path, options))
        self._json({"job_id": job_id})

    def _api_job_doc(self):
        form = self._form()
        job_id, (file_path,) = _prepare_upload_job('doc', form, ['file'])
        options = {"provider": form.getvalue("provider") or None} if hasattr(form, "getvalue") else {}
        _jobs[job_id]['source_file'] = file_path
        _run_async(job_id, lambda: _job_doc(_jobs[job_id]["dir"], file_path, options))
        self._json({"job_id": job_id})

    def _api_job_compare(self):
        form = self._form()
        job_id, (before, after) = _prepare_upload_job('compare', form, ['before', 'after'])
        d = _jobs[job_id]["dir"]
        options = {"ignore_format": (form.getvalue("ignore_format") != "false")
                   } if hasattr(form, "getvalue") else {"ignore_format": True}
        _run_async(job_id, lambda: _job_compare(d, before, after, options))
        self._json({"job_id": job_id})

    def _api_job_inspect(self):
        form = self._form()
        job_id, (file_path,) = _prepare_upload_job('inspect', form, ['file'])
        _jobs[job_id]["source_file"] = file_path
        options = {"provider": form.getvalue("provider") or None} if hasattr(form, "getvalue") else {}
        _run_async(job_id, lambda: _job_inspect(_jobs[job_id]["dir"], file_path, options))
        self._json({"job_id": job_id})

    def _api_job_correct(self):
        from .corrections import apply_corrections
        form = self._form()
        reviewed = json.loads(form.getvalue("reviewed") or "{}")
        if not isinstance(reviewed, dict):
            raise ValueError('reviewed 必须为 JSON 对象')
        job_id, (source,) = _prepare_upload_job('correct', form, ['file'])
        ext = ".pdf" if source.lower().endswith(".pdf") else ".png"
        output = os.path.join(_jobs[job_id]["dir"], "revision-" + secrets.token_hex(4) + ext)
        _run_async(job_id, lambda: apply_corrections(source, output, reviewed.get("patches"), reviewed.get("reviewer")))
        self._json({"job_id": job_id})

    def _api_jobs(self):
        with _jobs_lock:
            items = [{k: v for k, v in j.items() if k != "dir"} for j in _jobs.values()]
        items.sort(key=lambda x: x["id"], reverse=True)
        self._json({"jobs": items[:100]})

    def _api_job_detail(self, job_id: str):
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                return self._json({"error": "任务不存在"}, 404)
            payload = {k: v for k, v in job.items() if k != "dir"}
        self._json(payload)

    # ---------- 复核保存 ----------
    def _review_actor(self):
        from .review_workflow import authenticate
        users_path = os.path.join(DATA_DIR, 'review_users.json')
        if not os.path.exists(users_path):
            raise ValueError('尚未配置三角色复核用户，请管理员运行 scripts/provision_reviewer.py')
        with open(users_path, encoding='utf-8') as handle:
            return authenticate(json.load(handle), self.headers.get('X-Review-Token', ''))

    def _api_review_transition(self):
        from .review_workflow import ReviewStore
        actor = self._review_actor()
        body = self._read_json_body()
        result = ReviewStore(os.path.join(DATA_DIR, 'reviews.sqlite')).transition(
            str(body.get('document_id') or ''), body.get('action'), actor,
            body.get('revision', 0), body.get('payload'))
        self._json(result)

    def _api_impact_index(self):
        from .impact import validate_index
        body = validate_index(self._read_json_body())
        path = (load_web_config().get('impact') or {}).get('index_path', 'data/knowledge/associations.json')
        if not os.path.isabs(path):
            path = os.path.join(_ROOT, path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(body, handle, ensure_ascii=False, indent=2)
        self._json({'ok': True, 'objects': len(body['objects'])})

    @_serialized_edit
    def _api_assembly_save(self):
        from .assembly import validate_tree, update_quantity_checks
        body = self._read_json_body()
        result = self._job_result(str(body.get('job_id') or ''))
        if result is None:
            return
        if 'bom' not in result:
            raise ValueError('任务不是 BOM 任务')
        if type(body.get('bom_revision', 0)) is not int or body.get('bom_revision', 0) != result['bom'].get('revision', 0):
            raise ValueError('BOM版本已变化，旧装配关系不能提交，请重新加载并复核')
        reviewer = str(body.get('reviewer') or '').strip()
        if not reviewer:
            raise ValueError('请填写复核人')
        tree = validate_tree(body.get('assembly'), result['bom']['components'])
        max_page = (result['bom'].get('model_info') or {}).get('pages')
        if max_page and any(node['source_page'] > max_page for node in tree['nodes'] + tree.get('context_components', [])):
            raise ValueError('证据页码超出图纸页数')
        updated = copy.deepcopy(result)
        previous_tree = result['bom'].get('assembly') or {}
        if previous_tree.get('relation_semantics') == 'installation':
            tree['relation_semantics'] = 'installation'
        if previous_tree.get('relation_semantics') == 'bom_contains':
            tree['relation_semantics'] = 'bom_contains'
            tree['relation_candidates'] = previous_tree.get('relation_candidates', [])
            by_id = {n['id']: n for n in tree['nodes']}
            refs = {'c%d' % i: i for i in range(len(result['bom']['components']))}
            for candidate in tree['relation_candidates']:
                context = candidate.get('context_component')
                if context:
                    for i, current in enumerate(tree.get('context_components', [])):
                        if current['part_number'] == context['part_number']:
                            refs[candidate['component_id']] = len(result['bom']['components']) + i
            tree['component_refs'] = refs
            reverse = {i: ref for ref, i in refs.items()}
            pairs = {(reverse.get(by_id[n['parent_id']]['component_index']), reverse.get(n['component_index']))
                     for n in tree['nodes'] if n['parent_id'] is not None}
            roots = {reverse.get(n['component_index']) for n in tree['nodes'] if n['parent_id'] is None}
            tree['unresolved_relations'] = [r for r in previous_tree.get('unresolved_relations', [])
                if ((r.get('parent'), r.get('child')) not in pairs if r.get('parent') else r.get('component_id') not in roots)]
        updated['bom']['assembly'] = tree
        for node in tree['nodes']:
            node['status'] = 'confirmed'
        update_quantity_checks(updated['bom'])
        tree['status'] = ('reviewed_with_conflicts' if tree['quantity_conflicts'] else
                          'reviewed_partial' if tree['unresolved_component_indices'] or tree.get('unresolved_relations') else 'reviewed')
        for node in tree['nodes']:
            node['status'] = 'confirmed'
        tree['source_sha256'] = result.get('source_sha256')
        parent = os.path.join(DATA_DIR, 'reviewed')
        os.makedirs(parent, exist_ok=True)
        path = _safe_review_path(parent, str(body['job_id']), 'assembly_')
        job = _jobs[str(body['job_id'])]
        _commit_bom_edit([(path, tree), (os.path.join(job['dir'], 'result.json'), updated)],
                         {'action': 'assembly_review', 'editor': reviewer,
                          'document_id': result.get('document_id'), 'assembly': tree})
        job['result'] = updated
        self._json({'ok': True, 'assembly': tree,
                    'validation_issues': updated['bom']['validation_issues']})

    @_serialized_edit
    def _api_bom_save(self):
        body = self._read_json_body()
        doc_id = str(body.get("document_id") or "unnamed")
        comps = body.get("components", [])
        if not isinstance(comps, list) or any(not isinstance(c, dict) for c in comps):
            raise ValueError('components 必须为对象数组')
        from .schema import INT_FIELDS, FLOAT_FIELDS, TEXT_FIELDS, validate_components
        import math
        for row, comp in enumerate(comps, 1):
            for key in INT_FIELDS + FLOAT_FIELDS:
                value = comp.get(key)
                if value is None:
                    continue
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError('第%d行 %s 必须为有限数值或空值' % (row, key))
                if key in INT_FIELDS and int(value) != value:
                    raise ValueError('第%d行 %s 必须为整数' % (row, key))
            for key in TEXT_FIELDS:
                if key in comp and not isinstance(comp[key], str):
                    raise ValueError('第%d行 %s 必须为文本' % (row, key))
        json.dumps(comps, allow_nan=False)
        parsed, _ = components_from_payload(comps)
        job_id = body.get('job_id')
        job = _jobs.get(job_id)
        if job_id and (not job or job.get('kind') != 'bom' or job.get('status') != 'done'):
            raise ValueError('BOM任务不存在或未完成')
        parent = os.path.join(DATA_DIR, "reviewed")
        if not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        out = _safe_review_path(parent, doc_id)
        previous = copy.deepcopy(job['result']['bom'].get('components', [])) if job else []
        if not job and os.path.isfile(out):
            with open(out, encoding='utf-8') as handle:
                previous = json.load(handle).get('components', [])
        old_components, _ = components_from_payload(previous)
        preserve_rows = (job['result']['bom'].get('model_info') or {}).get('preserve_printed_rows', True) if job else True
        previous_findings = [reason for component in old_components for reason in component.review_reasons]
        previous_findings.extend(validate_components(old_components, allow_repeated_rows=preserve_rows))
        findings = validate_components(parsed, allow_repeated_rows=preserve_rows)
        # Retain submitted source fields, replacing only derived review flags.
        for raw, checked in zip(comps, parsed):
            raw['needs_review'] = checked.needs_review
            raw['review_reasons'] = checked.review_reasons
        # Each successful edit publishes an immutable snapshot and a before/after log.
        from .review_workflow import digest
        edit = {'document_id': doc_id, 'job_id': job_id,
                'source_sha256': job['result'].get('source_sha256') if job else None,
                'before': previous, 'after': copy.deepcopy(comps),
                'before_hash': digest(previous), 'after_hash': digest(comps),
                'editor': body.get('editor') or 'engineer', 'time': time.time()}
        versions = os.path.join(parent, 'edit_versions')
        os.makedirs(versions, exist_ok=True)
        snapshot = os.path.join(versions, secrets.token_hex(16) + '.json')
        updates = [(snapshot, edit), (out, {'document_id': doc_id, 'components': comps, 'validation_issues': findings})]
        record = {
            "action": "bom_review", "document_id": doc_id,
            "n_components": len(comps),
            'before': previous, 'after': comps, 'snapshot': snapshot,
            'job_id': job_id, 'source_sha256': edit['source_sha256'],
            "editor": body.get("editor") or "engineer",
            "comment": body.get("comment") or ""}
        if job:
            updated = copy.deepcopy(job['result'])
            bom = updated['bom']
            previous = bom.get('components', [])
            # Component indices and every relationship need re-review after a BOM edit.
            source_rows = lambda rows: [{k: v for k, v in row.items()
                                        if k not in ('needs_review', 'review_reasons')} for row in rows]
            if source_rows(previous) != source_rows(comps):
                from .assembly import validate_tree
                bom['assembly'] = dict(validate_tree({'nodes': []}, comps), inference_status='invalidated_by_bom_edit')
                bom['revision'] = bom.get('revision', 0) + 1
            bom['components'] = comps
            old_findings = set(previous_findings)
            bom['validation_issues'] = list(dict.fromkeys(
                [note for note in bom.get('validation_issues', []) if note not in old_findings] + findings))
            from .assembly import update_quantity_checks
            update_quantity_checks(bom)
            bom['summary'] = _bom_document_from(bom).summary()
            bom['review_status'] = 'draft'
            updates.append((os.path.join(job['dir'], 'result.json'), updated))
        _commit_bom_edit(updates, record)
        if job:
            job['result'] = updated
            _sync_detection_history({k: v for k, v in job.items() if k != 'dir'})
        self._json({"ok": True, "saved": out, 'bom': job['result']['bom'] if job else None})

    @_serialized_edit
    def _api_doc_save(self):
        body = self._read_json_body()
        name = str(body.get("file_name") or "unnamed")
        job_id = body.get('job_id')
        if job_id and (job_id not in _jobs or _jobs[job_id].get('kind') != 'doc' or _jobs[job_id].get('status') != 'done'):
            raise ValueError('文档任务不存在或未完成')
        if not isinstance(body.get('extraction'), dict):
            raise ValueError('extraction 必须为对象')
        parent = os.path.join(DATA_DIR, "reviewed")
        if not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        out = _safe_review_path(parent, name, prefix="doc_")
        _atomic_json(out, body['extraction'])
        _append_log(REVIEWLOG_PATH, {"action": "doc_review", "file_name": name,
                                     "editor": body.get("editor") or "engineer",
                                     "extraction": body.get('extraction'),
                                     "comment": body.get("comment") or ""})
        job_id = body.get('job_id')
        if job_id:
            _save_result_section(job_id, 'doc', 'extraction', body['extraction'])
        self._json({"ok": True, "saved": out})

    # ---------- 导出 ----------
    def _api_export_bom(self, job_id: str):
        result = self._job_result(job_id)
        if not result:
            return
        fmt = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("fmt", ["json"])[0]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if query.get('profile') == ['enterprise']:
            from .enterprise import mapped_components
            from .export import display_value
            mapped = mapped_components((result.get('bom') or {}).get('components', []), load_web_config().get('enterprise') or {})
            display_rows = [{label: display_value(field, row.get(label))
                             for field, label in mapped['field_mapping'].items()} for row in mapped['rows']]
            if fmt == 'csv':
                buffer = io.StringIO()
                writer = csv.DictWriter(buffer, fieldnames=list(mapped['field_mapping'].values()))
                writer.writeheader()
                writer.writerows(display_rows)
                return self._send(200, buffer.getvalue().encode('utf-8-sig'), 'text/csv; charset=utf-8', 'enterprise_bom.csv')
            if fmt == 'xlsx':
                body = _xlsx_bytes([list(row.values()) for row in display_rows], list(mapped['field_mapping'].values()))
                return self._send(200, body, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'enterprise_bom.xlsx')
            return self._json(mapped)
        bom_doc = _bom_document_from(result.get("bom") or {})
        doc_id = str(result.get("document_id") or job_id)
        if fmt == "csv":
            from .export import CSV_HEADERS, EXPORT_COLUMNS, display_value
            csv_buf = io.StringIO()
            w = csv.writer(csv_buf)
            w.writerow([CSV_HEADERS[k] for k in EXPORT_COLUMNS])
            for c in bom_doc.components:
                d = c.to_dict()
                w.writerow([display_value(k, d[k]) for k in EXPORT_COLUMNS])
            body = csv_buf.getvalue().encode("utf-8-sig")
            return self._send(200, body, "text/csv; charset=utf-8", doc_id + ".csv")
        if fmt == "xlsx":
            from .export import write_xlsx
            import tempfile
            bom_doc.assembly = (result.get('bom') or {}).get('assembly') or {}
            with tempfile.TemporaryDirectory() as temp_dir:
                target = os.path.join(temp_dir, 'bom.xlsx')
                write_xlsx(bom_doc, target)
                with open(target, 'rb') as handle:
                    body = handle.read()
            return self._send(200, body,
                              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', doc_id + '.xlsx')
        body = json.dumps(result.get("bom") or {}, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8", doc_id + ".json")

    def _api_export_doc(self, job_id: str):
        result = self._job_result(job_id)
        if not result:
            return
        fmt = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("fmt", ["json"])[0]
        extraction = result.get("extraction") or {}
        name = str(result.get("file_name") or job_id)
        if fmt == "xlsx":
            from .docextract import elements_to_rows
            headers = ["类别", "名称/项目", "内容/值", "单位/规格", "标准/条件", "来源"]
            rows = elements_to_rows(extraction)
            body = _xlsx_bytes(rows, headers)
            return self._send(200, body,
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              name + "_要素提取.xlsx")
        body = json.dumps(extraction, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8", name + "_要素提取.json")

    def _api_ecn(self, job_id: str):
        result = self._job_result(job_id)
        if not result:
            return
        from .changedetect import generate_ecn_md, summarize_changes
        meta = {"file_name": (result.get("after") or {}).get("file_name", "-"),
                "before_name": (result.get("before") or {}).get("file_name", "-"),
                "after_name": (result.get("after") or {}).get("file_name", "-")}
        md = generate_ecn_md(meta, result.get("items") or [],
                             summarize_changes(result.get("items") or []))
        impact = result.get('impact') or {}
        md += '\n\n## 关联影响检索结果\n\n' + str(impact.get('coverage', '尚未分析')) + '\n'
        for obj in impact.get('objects', []):
            md += '\n- %s（%s，%s，待复核）' % (obj['name'], obj['kind'], obj['severity'])
            for reason in obj['reasons']:
                md += '\n  - 变更 #%d，命中 %s，依赖路径 %s' % (reason['change_index']+1,
                    '、'.join(reason['matched_terms']), ' → '.join(reason['dependency_path']))
        _append_log(HISTORY_PATH, {"action": "ecn_generated", "job_id": job_id,
                                   "file_name": meta["file_name"],
                                   "summary": summarize_changes(result.get("items") or [])})
        self._send(200, md.encode("utf-8"), "text/markdown; charset=utf-8",
                   "ECN_%s.md" % job_id)

    def _job_result(self, job_id: str):
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                self._json({"error": "任务不存在"}, 404)
                return None
            if job["status"] != "done":
                self._json({"error": "任务未完成: %s" % job["status"]}, 409)
                return None
            return job.get("result")

    # ---------- 历史 / 记录 / 配置 ----------
    def _api_history(self):
        from .changedetect import load_history
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self._json({"records": load_history(HISTORY_PATH,
                                            qs.get("file_name", [None])[0],
                                            qs.get("category", [None])[0])})

    def _api_reviewlog(self):
        records = []
        if os.path.exists(REVIEWLOG_PATH):
            try:
                with open(REVIEWLOG_PATH, "r", encoding="utf-8") as f:
                    records = json.load(f)
            except (ValueError, OSError):
                records = []
        records.reverse()
        self._json({"records": records[:200]})

    def _api_detection_history(self):
        from .history import load_records
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        try:
            limit = min(max(int(qs.get("limit", ["200"])[0]), 1), 1000)
        except ValueError:
            limit = 200
        records, summary = load_records(DETECTION_HISTORY_DIR, limit=limit,
                                        file_name=qs.get("file_name", [None])[0],
                                        status=qs.get("status", [None])[0])
        self._json({"records": records, "summary": summary})

    def _api_detection_history_detail(self, job_id: str):
        from .history import load_detail
        detail = load_detail(DETECTION_HISTORY_DIR, job_id)
        if detail is None:
            return self._json({"error": "该次检测的历史记录不存在"}, 404)
        self._json(detail)

    def _api_status(self):
        self._json(_status_payload())

    def _api_config(self):
        body = self._read_json_body()
        patch = {}
        if body.get("provider"):
            patch.setdefault("provider", {})["name"] = str(body["provider"])
        oc = body.get("openai_compat") or {}
        sub = {}
        for key in ("base_url", "model"):
            if oc.get(key) is not None and str(oc[key]).strip():
                sub[key] = str(oc[key]).strip()
        # API Key：仅当传入非空值时更新，留空表示沿用已保存/环境变量的值
        if oc.get("api_key") is not None and str(oc["api_key"]).strip():
            sub["api_key"] = str(oc["api_key"]).strip()
        if body.get("clear_api_key"):
            sub["api_key"] = ""
        if sub:
            patch.setdefault("provider", {})["openai_compat"] = sub
        if patch:
            save_web_settings(patch)
        self._json({"ok": True, "status": _status_payload()})

    def _api_test_connection(self):
        """测试模型连通性：先用请求里的临时配置（未保存也能测），否则用已保存配置。"""
        from .providers import ProviderError, build_provider
        body = self._read_json_body()
        cfg = load_web_config()
        patch = {}
        if body.get("provider"):
            patch.setdefault("provider", {})["name"] = str(body["provider"])
        oc = {k: str(v).strip() for k, v in (body.get("openai_compat") or {}).items()
              if v is not None and str(v).strip()}
        if oc:
            patch.setdefault("provider", {})["openai_compat"] = oc
        if patch:
            cfg = deep_merge(cfg, patch)
        try:
            provider = build_provider(cfg.get("provider") or {})
        except ProviderError as exc:
            return self._json({"ok": False, "error": str(exc)})
        if provider.name == "mock":
            return self._json({"ok": True, "model": "mock", "latency_s": 0.0,
                               "message": "离线演示模型可用（未连接真实 API）"})
        try:
            provider.max_tokens = 32  # 测试只取极短回复，省费用
            resp = provider.analyze([], "请只回复两个字：可用")
            text = (resp.raw_text or "").strip()[:50]
            self._json({"ok": True, "model": resp.model,
                        "latency_s": round(resp.latency_s, 2),
                        "message": "连接成功，模型回复: %s" % (text or "(空)")})
        except ProviderError as exc:
            self._json({"ok": False, "error": str(exc)})
        except Exception as exc:
            self._json({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})


def _preprocess_ok() -> bool:
    try:
        from .preprocess import preprocess_available
        return preprocess_available()
    except Exception:
        return False


def _status_payload() -> dict:
    """当前模型/环境状态（不泄露密钥本身，只报告是否已设置及其来源）。"""
    import engine_bom as pkg
    cfg = load_web_config()
    name = str((cfg.get("provider") or {}).get("name") or "mock")
    oc = (cfg.get("provider") or {}).get("openai_compat") or {}
    cfg_key = str(oc.get("api_key") or "").strip()
    env_name = str(oc.get("api_key_env") or "VISION_API_KEY")
    env_key = os.environ.get(env_name, "").strip()
    return {
        "version": pkg.__version__,
        "provider": name,
        "model": oc.get("model") or os.environ.get("VISION_MODEL", ""),
        "base_url": oc.get("base_url") or os.environ.get("VISION_BASE_URL", ""),
        "api_key_set": bool(cfg_key or env_key),
        "api_key_source": "config" if cfg_key else ("env" if env_key else "none"),
        "api_key_env_name": env_name,
        "recognition_mode": (cfg.get("recognition") or {}).get("mode"),
        "preprocess_available": _preprocess_ok(),
    }


class _WebServer(ThreadingHTTPServer):
    # Windows 的 SO_REUSEADDR 允许两个进程同时 bind 同一端口（请求随机分流，
    # 令牌校验时好时坏），故 Windows 上关闭复用并加 SO_EXCLUSIVEADDRUSE 独占绑定。
    allow_reuse_address = not sys.platform.startswith("win")

    def server_bind(self):
        if sys.platform.startswith("win") and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="发动机元器件 BOM 系统 Web 服务（标准库实现）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（内网部署用 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--config", help="固定部署配置（此模式不读取网页保存的云端设置）")
    args = parser.parse_args(argv)
    global CONFIG_PATH
    CONFIG_PATH = os.path.abspath(args.config) if args.config else None

    os.makedirs(JOBS_DIR, exist_ok=True)
    _cleanup_orphan_job_dirs()
    try:
        server = _WebServer((args.host, args.port), Handler)
    except OSError as exc:
        print("[error] 端口 %d 绑定失败: %s" % (args.port, exc))
        print("        很可能已有实例在运行（Windows 下旧版本允许重复绑定，会导致请求分流）。")
        return 1
    print("=" * 60)
    print("发动机元器件识别与 BOM 系统 Web 服务已启动")
    print("  地址: http://%s:%d/" % (args.host if args.host != "0.0.0.0" else "127.0.0.1", args.port))
    print("  停止: Ctrl+C")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
