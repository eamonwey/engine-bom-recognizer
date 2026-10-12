# -*- coding: utf-8 -*-
"""文档摄入：PDF 渲染为页面图像、图片直接加载、统一缩放。

输出 PageImage 列表（1-based 页码 + PIL Image），供视觉模型统一消费。
"""
import io
import os
from dataclasses import dataclass
from typing import Any, Dict, List

from PIL import Image

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None


@dataclass
class PageImage(object):
    page_no: int          # 1-based
    image: Image.Image
    label: str = ""       # 备注标签，如 "page 1/3"
    original_image: Image.Image = None  # Native pixels for detail crops.

    @property
    def size(self) -> tuple:
        return self.image.size


class IngestionError(RuntimeError):
    pass


def is_supported(path: str, cfg: Dict[str, Any]) -> bool:
    ext = os.path.splitext(path)[1].lower()
    formats = [str(x).lower() for x in cfg.get("image_formats", [])]
    return ext in (".pdf", ".dxf") or ext in formats


def load_document(path: str, cfg: Dict[str, Any]) -> List[PageImage]:
    """把输入文件转成页面图像列表。"""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise IngestionError("文件不存在: %s" % path)
    ext = os.path.splitext(path)[1].lower()
    native_cfg = dict(cfg, max_image_long_side=0)
    if ext == ".pdf":
        pages = _render_pdf(path, native_cfg)
    elif ext in [str(x).lower() for x in cfg.get("image_formats", [])]:
        img = _load_image_file(path, native_cfg)
        pages = [PageImage(page_no=1, image=img, label=os.path.basename(path))]
    elif ext == ".dxf":
        from .cad import render_dxf
        try:
            pages = render_dxf(path, cfg)
        except ImportError:
            raise IngestionError("DXF渲染需要 ezdxf 和 matplotlib，请安装 requirements-cad.txt")
    elif ext == ".dwg":
        raise IngestionError(
            "CAD 源文件（%s）需先转换为 PDF/图片再识别：内网部署时安装 ODA File Converter "
            "或 ezdxf 渲染后接入本系统（详见 README 内网部署章节）" % ext.upper())
    else:
        raise IngestionError("不支持的文件类型 %s（支持 PDF 与 %s）" % (ext, cfg.get("image_formats")))
    total = len(pages)
    pre_cfg = cfg.get("preprocess") or {}
    if pre_cfg.get("enabled"):
        from .preprocess import preprocess_available, preprocess_image
        if preprocess_available():
            for p in pages:
                p.image = preprocess_image(p.image, pre_cfg)
        else:
            print("[warn] 未安装 OpenCV，跳过扫描件预处理（pip install opencv-python）")
    for p in pages:
        p.original_image = p.image
        p.image = _resize_if_needed(p.image,cfg)
        p.label = "page %d/%d" % (p.page_no, total)
    return pages


def _resize_if_needed(image: Image.Image, cfg: Dict[str, Any]) -> Image.Image:
    max_side = int(cfg.get("max_image_long_side") or 0)
    if max_side <= 0:
        return image
    w, h = image.size
    long_side = max(w, h)
    if long_side <= max_side:
        return image
    scale = max_side / float(long_side)
    return image.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def _render_pdf(path: str, cfg: Dict[str, Any]) -> List[PageImage]:
    if fitz is None:
        raise IngestionError("处理 PDF 需要 PyMuPDF：pip install pymupdf")
    dpi = int(cfg.get("dpi") or 200)
    pages: List[PageImage] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            has_3d = any(a.type[1] == "3D" for a in (page.annots() or []))
            if has_3d and all(low >= 250 for low, high in image.getextrema()):
                raise IngestionError("PDF第%d页只有交互式3D模型，未提供可渲染的二维图纸；请从CAD导出二维PDF/图片后上传" % (i + 1))
            pages.append(PageImage(page_no=i + 1, image=_resize_if_needed(image, cfg)))
    if not pages:
        raise IngestionError("PDF 无有效页面: %s" % path)
    return pages


def _load_image_file(path: str, cfg: Dict[str, Any]) -> Image.Image:
    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:  # Pillow 对损坏文件的报错类型不稳定
        raise IngestionError("图片无法读取 %s: %s" % (path, exc))
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return _resize_if_needed(image, cfg)
