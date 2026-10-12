# -*- coding: utf-8 -*-
"""BOM 导出：JSON / CSV（Excel 友好 utf-8-sig）/ XLSX（需 openpyxl）。"""
import csv
import json
import os
import time
from typing import Any, Dict, List, Optional

from .schema import BomDocument

CSV_HEADERS = {
    "item_no": "序号", "part_number": "图号/件号", "name_zh": "名称(中文)", "name_en": "名称(英文)",
    "category": "功能系统", "specification": "规格型号", "material": "材料",
    "quantity": "数量", "weight": "重量(g)", "unit": "单位", "position": "装配位置", "supplier": "供应商",
    "remark": "备注", "needs_review": "待核实", "review_reasons": "核实原因",
    "source_page": "来源页", "confidence": "置信度",
}

# 对外导出列：置信度为模型自报的未校准分值，界面已隐藏，导出文件同步移除；
# JSON 结构仍保留该字段（评测与 min_confidence 过滤需要）。
EXPORT_COLUMNS = [k for k in CSV_HEADERS if k != "confidence"]


def export_bom(bom: BomDocument, out_prefix: str, formats: List[str]) -> List[str]:
    """按格式导出；out_prefix 为不含扩展名的前缀。返回生成的文件路径列表。

    目标文件被占用（如正在 Excel 中打开）时自动改用带时间戳的备用文件名，
    单个格式失败不影响其他格式。
    """
    written: List[str] = []
    for fmt in [str(f).lower() for f in formats]:
        path = "%s.%s" % (out_prefix, fmt)
        try:
            written.append(_write_one(bom, fmt, path))
        except PermissionError:
            alt = "%s_%s.%s" % (out_prefix, time.strftime("%H%M%S"), fmt)
            try:
                written.append(_write_one(bom, fmt, alt))
                print("[warn] %s 被占用（可能正在 Excel 中打开），已改存为 %s" % (path, alt))
            except OSError as exc:
                print("[warn] 导出失败 %s: %s" % (path, exc))
        except OSError as exc:
            print("[warn] 导出失败 %s: %s" % (path, exc))
    return written


def _write_one(bom: BomDocument, fmt: str, path: str) -> str:
    if fmt == "json":
        write_json(bom, path)
    elif fmt == "csv":
        write_csv(bom, path)
    elif fmt == "xlsx":
        write_xlsx(bom, path)
    else:
        print("[warn] 忽略未知导出格式: %r" % fmt)
        return ""
    return path


def write_json(bom: BomDocument, path: str) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(bom.to_dict(), f, ensure_ascii=False, indent=2, allow_nan=False)


def display_value(key: str, value: Any) -> Any:
    """导出展示格式化：重量整数值去掉小数点，置信度保留两位，待核实/核实原因转文本。"""
    if value is None:
        return ""
    if key == "weight" and isinstance(value, float) and value.is_integer():
        return int(value)
    if key == "confidence" and isinstance(value, float):
        return round(value, 2)
    if key == "needs_review":
        return "是" if value else ""
    if key == "review_reasons":
        if isinstance(value, (list, tuple)):
            return "；".join(str(v) for v in value if str(v).strip())
        return str(value or "")
    return value


def write_csv(bom: BomDocument, path: str) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([CSV_HEADERS[k] for k in EXPORT_COLUMNS])
        for c in bom.components:
            d = c.to_dict()
            writer.writerow([display_value(k, d[k]) for k in EXPORT_COLUMNS])


def write_xlsx(bom: BomDocument, path: str) -> None:
    try:
        from openpyxl import Workbook  # type: ignore
    except ImportError:
        print("[warn] 未安装 openpyxl，跳过 XLSX 导出（pip install openpyxl）")
        return
    _ensure_parent(path)
    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append([CSV_HEADERS[k] for k in EXPORT_COLUMNS])
    for c in bom.components:
        d = c.to_dict()
        ws.append([display_value(k, d[k]) for k in EXPORT_COLUMNS])
    if bom.assembly:
        from .assembly import assembly_rows
        tree = wb.create_sheet('装配层级')
        tree.append(['节点', '父节点', '层级', '件号', '名称', '父项用量', '证据页码', '证据', '复核状态'])
        for row in assembly_rows(bom.assembly, [c.to_dict() for c in bom.components]):
            tree.append(row)
    wb.save(path)


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
