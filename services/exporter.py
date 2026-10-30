"""用例导出 Excel"""
"""用例导出 Excel"""
from datetime import datetime
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from models import WebTestCase


# 导出列定义（按用户要求的字段）
EXPORT_COLUMNS = [
    ("标题", "title", 50),
    ("前置条件", "precondition", 40),
    ("测试步骤", "steps", 50),
    ("预期结果", "expected", 40),
]


def _query_cases(keyword="", source="", ids=None, doc_name="", doc_version=""):
    from models import db
    query = WebTestCase.query
    if ids is not None:
        query = query.filter(WebTestCase.id.in_(ids))
    else:
        if doc_name:
            query = query.filter(WebTestCase.doc_name == doc_name)
        if doc_version:
            query = query.filter(WebTestCase.doc_version == doc_version)
        if keyword:
            like = f"%{keyword}%"
            query = query.filter(db.or_(
                WebTestCase.title.like(like),
                WebTestCase.tags.like(like),
                WebTestCase.project.like(like),
            ))
        if source:
            query = query.filter(WebTestCase.source == source)
    return query.order_by(WebTestCase.id.asc()).all()




def export_cases_to_excel(keyword="", source="", ids=None,doc_name="", doc_version="") -> tuple:
    """
    导出用例到 Excel。
    - 传 ids：只导出这些 id
    - 不传 ids：按 keyword/source 筛选（都为空则导出全部）
    返回 (BytesIO, filename)
    """
    cases = _query_cases(keyword, source, ids, doc_name, doc_version)

    wb = Workbook()
    ws = wb.active
    ws.title = "测试用例"

    # ---------- 样式 ----------
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell_align = Alignment(vertical="top", wrap_text=True)

    thin = Side(border_style="thin", color="D0D7DE")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ---------- 表头 ----------
    for col_idx, (label, _, width) in enumerate(EXPORT_COLUMNS, start=1):
        c = ws.cell(row=1, column=col_idx, value=label)
        c.font = header_font
        c.fill = header_fill
        c.alignment = header_align
        c.border = border
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.row_dimensions[1].height = 24

    # ---------- 数据 ----------
    for row_idx, case in enumerate(cases, start=2):
        for col_idx, (_, field, _) in enumerate(EXPORT_COLUMNS, start=1):
            value = getattr(case, field, "") or ""
            c = ws.cell(row=row_idx, column=col_idx, value=value)
            c.alignment = cell_align
            c.border = border

    # ---------- 冻结首行 ----------
    ws.freeze_panes = "A2"

    # ---------- 输出 ----------
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"测试用例_{timestamp}.xlsx"

    return buf, filename


