"""Apply reviewed text replacements to a COPY of image/PDF; journal hashes and edits."""
import hashlib
import json
import os
from datetime import datetime, timezone
from .hybrid_inspection import valid_bbox


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def apply_corrections(source, output, patches, reviewer):
    """patch: source_page, bbox(normalized), old_text, new_text, approved, err_id.

    Rectangle must be selected/reviewed by a person. Raster replacement is visual,
    not a change to CAD geometry. PDF redaction removes old text inside the box.
    """
    if os.path.normcase(os.path.realpath(source)) == os.path.normcase(os.path.realpath(output)):
        raise ValueError("修订输出不能覆盖原文件")
    if os.path.exists(output):
        raise ValueError("修订输出已存在，请选择新的版本文件名")
    if not reviewer or not str(reviewer).strip() or not patches:
        raise ValueError("需要复核人和非空修订列表")
    for patch in patches:
        if not isinstance(patch, dict) or patch.get("approved") is not True:
            raise ValueError("每项修订必须明确 approved=true")
        if not valid_bbox(patch.get("bbox")):
            raise ValueError("必须提供复核后的整页归一化 bbox")
        if not isinstance(patch.get("new_text"), str) or not patch["new_text"].strip():
            raise ValueError("修正值不能为空")
        page = patch.get("source_page")
        if not isinstance(page, int) or isinstance(page, bool) or page < 1:
            raise ValueError("页码必须是正整数")
    before_hash = sha256(source)
    for patch in patches:
        expected = patch.get("expected_source_sha256")
        if expected and expected != before_hash:
            raise ValueError("原文件已变更，必须重新复核")
    is_pdf = source.lower().endswith(".pdf")
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    if is_pdf:
        if not output.lower().endswith(".pdf"):
            raise ValueError("PDF修订输出必须为PDF")
        import fitz
        with fitz.open(source) as doc:
            # Validate all boxes and fit all replacement text before mutating pages.
            for patch in patches:
                if patch["source_page"] > len(doc):
                    raise ValueError("修订页码超出PDF范围")
                if doc[patch["source_page"] - 1].rotation:
                    raise ValueError("旋转PDF页面请先归一化方向，再复核修订位置")
            for patch in patches:
                page = doc[patch["source_page"] - 1]
                x0, y0, x1, y1 = patch["bbox"]
                rect = fitz.Rect(x0 * page.rect.width, y0 * page.rect.height,
                                 x1 * page.rect.width, y1 * page.rect.height)
                page.add_redact_annot(rect, fill=(1, 1, 1))
                page.apply_redactions()
                font = "china-s" if any(ord(c) > 127 for c in patch["new_text"]) else "helv"
                size = min(12, rect.height * 0.55)
                fitted = False
                while size >= 3:
                    if page.insert_textbox(rect, patch["new_text"], fontsize=size, fontname=font,
                                           color=(0.8, 0, 0)) >= 0:
                        fitted = True
                        break
                    size -= 0.5
                if not fitted:
                    raise ValueError("修订文字无法装入 bbox，请扩大框选区域")
            doc.save(output, garbage=4, deflate=True)
    else:
        if any(p["source_page"] != 1 for p in patches):
            raise ValueError("图片修订只支持第1页")
        if not output.lower().endswith(".png"):
            raise ValueError("图片修订输出必须为PNG")
        from PIL import Image, ImageDraw, ImageFont
        with Image.open(source) as original:
            image = original.convert("RGB")
        draw = ImageDraw.Draw(image)
        font_cache = {}
        for patch in patches:
            x0, y0, x1, y1 = patch["bbox"]
            box = tuple(round(v * (image.width if i % 2 == 0 else image.height))
                        for i, v in enumerate((x0, y0, x1, y1)))
            text = patch["new_text"]
            font_path = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "msyh.ttc")
            font = None
            for size in range(max(3, min(64, box[3] - box[1])), 2, -1):
                if size not in font_cache:
                    font_cache[size] = (ImageFont.truetype(font_path, size)
                                        if os.path.exists(font_path) else ImageFont.load_default())
                candidate = font_cache[size]
                bounds = draw.textbbox((0, 0), text, font=candidate)
                if bounds[2] - bounds[0] <= box[2] - box[0] and bounds[3] - bounds[1] <= box[3] - box[1]:
                    font = candidate
                    break
            if font is None:
                raise ValueError("修订文字无法装入 bbox")
            draw.rectangle(box, fill="white", outline="#b00020")
            draw.text((box[0], box[1] - bounds[1]), text, fill="#b00020", font=font)
        image.save(output)
    journal = {"source": os.path.abspath(source), "output": os.path.abspath(output),
               "source_sha256": before_hash, "output_sha256": sha256(output),
               "reviewer": reviewer, "timestamp": datetime.now(timezone.utc).isoformat(),
               "patches": patches, "scope": "text annotation replacement; CAD geometry unchanged"}
    with open(output + ".audit.json", "w", encoding="utf-8") as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)
    return journal
