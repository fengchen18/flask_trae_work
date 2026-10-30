"""md 导入：从 Trae 生成的 md 中解析表格 → 入库"""
import re
from models import db, WebTestCase


# 表头列名 → 模型字段名
COLUMN_MAP = {
    "标题": "title",
    "优先级": "priority",
    "负责人": "owner",
    "标签": "tags",
    "所属项目": "project",
    "所属用例集": "case_set",
    "用例类型": "case_type",
    "前置条件": "precondition",
    "测试步骤": "steps",
    "预期结果": "expected",
    "证据来源": "evidence_source",
    "证据等级": "evidence_level",
    "证据块ID": "evi_block_ids",
}


def _clean_header(cell: str) -> str:
    """去掉表头里的 * 和空格"""
    return re.sub(r"[\*\s]", "", cell.strip())


def parse_md_table(content: str):
    """
    解析 markdown 表格，返回 [dict, ...]
    只解析第一个匹配 13 列表头的表
    """
    lines = content.splitlines()
    header_line_idx = -1
    header_cells = []

    # 找表头行：包含"标题"和"优先级"
    for i, line in enumerate(lines):
        if "标题" in line and "优先级" in line and line.strip().startswith("|"):
            header_line_idx = i
            header_cells = [_clean_header(c) for c in line.strip().strip("|").split("|")]
            break

    if header_line_idx == -1:
        return []

    # 跳过分隔行（|---|---|）
    data_start = header_line_idx + 2
    rows = []

    for i in range(data_start, len(lines)):
        line = lines[i].strip()
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(header_cells):
            continue

        row = {}
        for col, val in zip(header_cells, cells):
            field = COLUMN_MAP.get(col)
            if field:
                row[field] = val
        rows.append(row)

    return rows


def import_md_file(file_path, doc_name="", doc_version=""):
    """
    导入 md 文件到数据库
    :return: (成功数, 总解析数)
    """
    from pathlib import Path
    content = Path(file_path).read_text(encoding="utf-8")
    rows = parse_md_table(content)

    success = 0
    for row in rows:
        if not row.get("title"):
            continue
        tc = WebTestCase(
            title=row.get("title", ""),
            priority=row.get("priority", ""),
            owner=row.get("owner", ""),
            tags=row.get("tags", ""),
            project=row.get("project", ""),
            case_set=row.get("case_set", ""),
            case_type=row.get("case_type", ""),
            precondition=row.get("precondition", ""),
            steps=row.get("steps", ""),
            expected=row.get("expected", ""),
            evidence_source=row.get("evidence_source", ""),
            evidence_level=row.get("evidence_level", ""),
            evi_block_ids=row.get("evi_block_ids", ""),
            doc_name=doc_name,
            doc_version=doc_version,
            source="import",
        )
        db.session.add(tc)
        success += 1

    db.session.commit()
    return success, len(rows)