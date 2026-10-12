# -*- coding: utf-8 -*-
"""扫描件预处理（REQ-01-1 子功能）：去噪、倾斜校正、二值化、对比度增强。

依赖 OpenCV（本机已装）；未安装时自动降级为不预处理并给出提示。
"""
from typing import Any, Dict, Optional

from PIL import Image

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None
    np = None


def preprocess_available() -> bool:
    return cv2 is not None


def preprocess_image(image: Image.Image, cfg: Optional[Dict[str, Any]] = None) -> Image.Image:
    """按配置执行预处理流水线。cfg 键: deskew/denoise/binarize/contrast (bool)。"""
    cfg = cfg or {}
    if cv2 is None or not any([cfg.get("deskew"), cfg.get("denoise"), cfg.get("binarize"), cfg.get("contrast")]):
        return image
    arr = np.array(image.convert("L"))
    if cfg.get("denoise"):
        arr = cv2.fastNlMeansDenoising(arr, h=10)
    if cfg.get("deskew"):
        arr = _deskew(arr)
    if cfg.get("binarize"):
        # Otsu 自适应阈值，保留文字笔画
        _, arr = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif cfg.get("contrast"):
        arr = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(arr)
    return Image.fromarray(arr).convert("RGB")


def _deskew(gray) -> "np.ndarray":
    """基于最小面积矩的倾斜校正（工程图纸常见 ±10° 以内的小倾角）。"""
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(binary)
    if coords is None:
        return gray
    angle = cv2.minAreaRect(coords)[-1]
    if angle > 45:
        angle -= 90
    if abs(angle) < 0.3 or abs(angle) > 15:  # 角度过小无需校正，过大视为误判
        return gray
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)
