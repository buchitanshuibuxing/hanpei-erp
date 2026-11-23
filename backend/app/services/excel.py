"""Excel 导入导出（openpyxl）：表头样式化、批量导入解析。"""
import io

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)


def export_excel(headers, rows, sheet_title="Sheet1"):
    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_title or "Sheet1")[:31]
    ws.append(list(headers))
    for c in ws[1]:
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center")
    for row in rows:
        ws.append(["" if v is None else v for v in row])
    for i, h in enumerate(headers, 1):
        width = min(42, max(11, len(str(h)) * 2 + 4))
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_excel(content: bytes, max_rows=20000):
    """读首个工作表，首行为表头；返回 dict 列表（键为表头文本）。"""
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    headers = []
    for r in rows:
        headers = [str(c).strip() if c is not None else "" for c in r]
        break
    out = []
    for r in rows:
        if len(out) >= max_rows:
            break
        if not any(c is not None and str(c).strip() != "" for c in r):
            continue
        item = {}
        for i, h in enumerate(headers):
            if h and i < len(r):
                item[h] = r[i]
        out.append(item)
    wb.close()
    return out, headers
