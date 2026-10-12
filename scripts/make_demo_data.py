# -*- coding: utf-8 -*-
"""生成演示数据：一份两页的《发动机零部件明细表》PDF + 一张图片样本 + 对应人工标注。

用于在拿到真实数据集之前端到端验证流水线与评测链路。
运行: python -X utf8 scripts/make_demo_data.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # PyMuPDF

_LATIN_RE = re.compile(r"[A-Za-z0-9\.\-\s/%()°:]+")


def insert_mixed(page, x, y, text, size=9):
    """中英文混排插入：中文用 china-s，西文/数字用 helv，避免全角字母稀疏难看。"""
    buf = ""
    is_latin = None
    for ch in str(text):
        ch_latin = _LATIN_RE.match(ch) is not None
        if is_latin is None or ch_latin == is_latin:
            buf += ch
            is_latin = ch_latin
            continue
        x = _flush(page, x, y, buf, is_latin, size)
        buf, is_latin = ch, ch_latin
    if buf:
        _flush(page, x, y, buf, is_latin, size)


def _flush(page, x, y, seg, is_latin, size):
    if not seg:
        return x
    font = "helv" if is_latin else "china-s"
    page.insert_text((x, y), seg, fontname=font, fontsize=size)
    if is_latin:
        try:
            return x + fitz.get_text_length(seg, fontname="helv", fontsize=size)
        except Exception:
            return x + 0.55 * size * len(seg)
    return x + size * len(seg)  # CJK 全角近似等宽

# (序号, 图号, 名称中文, 名称英文, 规格, 材料, 数量, 单位, 备注, 分类, 装配位置)
ROWS = [
    ("1",  "ENG-BLK-001", "气缸体", "Cylinder Block",   "直列四缸",   "铸铁 HT250",   "1",  "件", "",             "机体与气缸盖",   "发动机主体"),
    ("2",  "ENG-HD-002",  "气缸盖", "Cylinder Head",    "DOHC 16V",  "铝合金 A356",  "1",  "件", "",             "机体与气缸盖",   "气缸体上方"),
    ("3",  "ENG-PST-003", "活塞",   "Piston",           "Φ86×60mm",  "铝合金 4032",  "4",  "件", "",             "曲柄连杆机构",   "气缸体内"),
    ("4",  "ENG-RNG-004", "活塞环", "Piston Ring",      "三件组",     "合金钢",       "12", "件", "每活塞3件",     "曲柄连杆机构",   "活塞环槽"),
    ("5",  "ENG-CRD-005", "连杆",   "Connecting Rod",   "锻造成型",   "锻钢 40Cr",    "4",  "件", "",             "曲柄连杆机构",   "活塞与曲轴间"),
    ("6",  "ENG-CRS-006", "曲轴",   "Crankshaft",       "五主轴颈",   "锻钢 42CrMo",  "1",  "件", "动平衡校验",   "曲柄连杆机构",   "主轴承座"),
    ("7",  "ENG-VLV-007", "进气门", "Intake Valve",     "Φ32mm",     "耐热钢",       "4",  "件", "",             "配气机构",       "气缸盖进气侧"),
    ("8",  "ENG-VLV-008", "排气门", "Exhaust Valve",    "Φ28mm",     "耐热合金",     "4",  "件", "",             "配气机构",       "气缸盖排气侧"),
    ("9",  "ENG-CAM-009", "凸轮轴", "Camshaft",         "双顶置",     "合金铸铁",     "2",  "件", "",             "配气机构",       "气缸盖上部"),
    ("10", "ENG-INJ-010", "喷油器", "Fuel Injector",    "多孔高压",   "",             "4",  "件", "",             "燃油供给系统",   "进气道"),
    ("11", "ENG-OMP-011", "机油泵", "Oil Pump",         "转子式",     "",             "1",  "件", "",             "润滑系统",       "油底壳内"),
    ("12", "ENG-WTP-012", "水泵",   "Water Pump",       "离心式",     "铝合金",       "1",  "件", "",             "冷却系统",       "缸体前端"),
]

PAGE_W, PAGE_H = 595, 842  # A4 竖版
MARGIN = 42
COLS = [("序号", 34), ("图号", 92), ("名称", 62), ("规格", 66), ("材料", 76), ("数量", 34), ("单位", 34), ("备注", 90)]
ROW_H = 22
TITLE_H = 60


def _table_width():
    return sum(w for _, w in COLS)


def build_pdf(path):
    doc = fitz.open()
    # ---------------- 第 1 页：零部件明细表 ----------------
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    insert_mixed(page, MARGIN, 46, "XX490 汽油发动机  零部件明细表", size=15)
    insert_mixed(page, MARGIN, 62, "图号: XX490-ZM-01    版本: B    共 12 项", size=8.5)

    x0 = MARGIN
    y0 = TITLE_H
    total_w = _table_width()
    # 表格线
    for r in range(len(ROWS) + 2):
        y = y0 + r * ROW_H
        page.draw_line((x0, y), (x0 + total_w, y), color=(0, 0, 0), width=0.6)
    x = x0
    for _, w in COLS:
        x += w
        page.draw_line((x, y0), (x, y0 + (len(ROWS) + 1) * ROW_H), color=(0, 0, 0), width=0.6)
    # 表头
    x = x0
    for name, w in COLS:
        insert_mixed(page, x + 4, y0 + 15, name, size=9)
        x += w
    # 数据行
    for i, row in enumerate(ROWS):
        y = y0 + (i + 1) * ROW_H + 15
        x = x0
        values = [row[0], row[1], row[2], row[4], row[5], row[6], row[7], row[8]]
        for (name, w), v in zip(COLS, values):
            insert_mixed(page, x + 4, y, v, size=8.5)
            x += w
    foot = y0 + (len(ROWS) + 1) * ROW_H + 30
    insert_mixed(page, MARGIN, foot, "编制: 王工    校对: 李工    日期: 2026-09-01", size=8.5)

    # ---------------- 第 2 页：装配示意图（简化） ----------------
    page2 = doc.new_page(width=PAGE_W, height=PAGE_H)
    insert_mixed(page2, MARGIN, 46, "XX490 总装示意图（简化）", size=14)
    cx, cy = PAGE_W / 2, 300
    page2.draw_rect(fitz.Rect(cx - 150, cy - 110, cx + 150, cy + 110), color=(0, 0, 0), width=1.2)
    page2.draw_circle((cx - 60, cy - 40), 34, color=(0, 0, 0), width=1.0)
    page2.draw_circle((cx + 60, cy - 40), 34, color=(0, 0, 0), width=1.0)
    page2.draw_circle((cx - 60, cy + 50), 34, color=(0, 0, 0), width=1.0)
    page2.draw_circle((cx + 60, cy + 50), 34, color=(0, 0, 0), width=1.0)
    page2.draw_line((cx - 90, cy), (cx + 90, cy), color=(0, 0, 0), width=2.0)
    labels = [("3 活塞 (x4)", cx - 60, cy - 90), ("6 曲轴", cx, cy + 16),
              ("9 凸轮轴 (x2)", cx, cy - 132), ("11 机油泵", cx - 150, cy + 140),
              ("12 水泵", cx + 90, cy + 140), ("7/8 气门 (x4/x4)", cx + 130, cy - 60)]
    for text, lx, ly in labels:
        insert_mixed(page2, lx - 20, ly, text, size=9)
    insert_mixed(page2, MARGIN, PAGE_H - 60,
                 "注: 序号与第 1 页明细表对应；本页仅为装配关系示意。", size=8.5)
    doc.save(path)
    doc.close()


def ground_truth():
    return {
        "document_id": None,  # 由调用方填写
        "components": [
            {"item_no": int(r[0]), "part_number": r[1], "name_zh": r[2], "name_en": r[3],
             "category": r[9], "specification": r[4], "material": r[5],
             "quantity": int(r[6]), "unit": r[7], "position": r[10],
             "supplier": "", "remark": r[8], "source_page": 1}
            for r in ROWS
        ],
    }


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raw_dir = os.path.join(root, "data", "raw")
    anno_dir = os.path.join(root, "data", "annotations")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(anno_dir, exist_ok=True)

    pdf_path = os.path.join(raw_dir, "demo_engine_bom.pdf")
    build_pdf(pdf_path)
    print("生成 PDF: %s" % pdf_path)

    # 图片样本：把明细表页渲染成 PNG，验证图片输入链路
    img_path = os.path.join(raw_dir, "demo_engine_parts_page.png")
    with fitz.open(pdf_path) as doc:
        pix = doc[0].get_pixmap(dpi=150)
        pix.save(img_path)
    print("生成图片: %s" % img_path)

    gt = ground_truth()
    for doc_id, source in (("demo_engine_bom", "demo_engine_bom.pdf"),
                           ("demo_engine_parts_page", "demo_engine_parts_page.png")):
        payload = dict(gt)
        payload["document_id"] = doc_id
        payload["source_file"] = source
        out = os.path.join(anno_dir, doc_id + ".json")
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("生成标注: %s (%d 个元器件)" % (out, len(payload["components"])))


if __name__ == "__main__":
    main()
