"""双向审计：正向（幻觉检测）+ 反向（漏抽检测）"""
import re
from pathlib import Path
import pymysql
from pymysql.cursors import DictCursor


def audit_md_file(md_file_path, doc_name, doc_version, db_config, exclude_ids=None):
    """
    返回 (report_text, result)
    result = {
        "header_ok": bool,
        "total_evi": int,
        "e4_e5_count": int,
        "used_block_ids": [...],
        "invalid_ids": [...],
        "leak_blocks": [{"id":..., "content_text":...}, ...],
        "has_leak": bool,
    }
    exclude_ids: 不需要用例覆盖的块（概述、元数据等）
    """
    exclude_ids = set(exclude_ids or [])
    md_file = Path(md_file_path)
    content = md_file.read_text(encoding="utf-8")

    report_lines = []
    report_lines.append("# 测试用例双向覆盖审计报告\n")
    report_lines.append(f"审计文件：{md_file.name}\n")

    result = {
        "header_ok": False,
        "total_evi": 0,
        "e4_e5_count": 0,
        "used_block_ids": [],
        "invalid_ids": [],
        "leak_blocks": [],
        "has_leak": False,
    }

    # 1. 表头校验
    header_pattern = re.compile(
        r"标题\*.*?优先级\*.*?负责人.*?标签.*?所属项目.*?所属用例集.*?"
        r"用例类型.*?前置条件.*?测试步骤.*?预期结果.*?证据来源.*?证据等级.*?证据块ID"
    )
    result["header_ok"] = bool(header_pattern.search(content))
    if result["header_ok"]:
        report_lines.append("✅ 完整表头校验通过（含证据块ID列）")
    else:
        report_lines.append("❌ 表头不匹配！缺少【证据块ID】列")

    # 2. 证据等级
    evi_level_list = re.findall(r"\|\s*(E[1-5])\s*\|", content, re.MULTILINE)
    result["total_evi"] = len(evi_level_list)
    result["e4_e5_count"] = sum(1 for lev in evi_level_list if lev in ("E4", "E5"))
    report_lines.append(f"✅ 共解析到 {result['total_evi']} 条用例证据")
    if result["e4_e5_count"] > 0:
        report_lines.append(f" 发现 {result['e4_e5_count']} 条 E4/E5 推测类用例，请人工确认")

    # 3. 提取 block_id
    blockid_all = re.findall(r"\|\s*(\d+(?:;\d+)*)\s*\|$", content, re.MULTILINE)
    used_block_ids = set()
    for id_str in blockid_all:
        if id_str.strip():
            for bid in id_str.split(";"):
                if bid.strip().isdigit():
                    used_block_ids.add(int(bid.strip()))
    result["used_block_ids"] = sorted(used_block_ids)

    report_lines.append(f"\n本次用例引用的 block_id：{result['used_block_ids']}")

    # 4. 连库做双向审计
    conn = pymysql.connect(
        host=db_config["host"], user=db_config["user"],
        password=db_config["password"], port=db_config["port"],
        database=db_config["database"], charset="utf8mb4",
        cursorclass=DictCursor, autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            # 正向
            for bid in used_block_ids:
                cur.execute("SELECT id FROM source_block WHERE id=%s", (bid,))
                if not cur.fetchone():
                    result["invalid_ids"].append(bid)

            if result["invalid_ids"]:
                report_lines.append(f"❌ 正向审计：发现不存在的 block_id（AI 幻觉）：{result['invalid_ids']}")
            else:
                report_lines.append("✅ 正向审计：所有引用 block_id 全部在 source_block 存在")

            # 反向
            if used_block_ids:
                id_str = ",".join(str(i) for i in sorted(used_block_ids))
                sql = f"""SELECT id, content_text FROM source_block
                          WHERE doc_name=%s AND doc_version=%s AND id NOT IN ({id_str})"""
                cur.execute(sql, (doc_name, doc_version))
                leaks = cur.fetchall()
                # 排除掉不需要用例的块
                leaks = [b for b in leaks if b["id"] not in exclude_ids]
                result["leak_blocks"] = [{"id": b["id"], "content_text": b["content_text"]} for b in leaks]
                result["has_leak"] = len(leaks) > 0

                if leaks:
                    report_lines.append(f" 反向审计：检测到 {len(leaks)} 个需求块没被引用（漏抽）")
                    for b in leaks:
                        report_lines.append(f"    block_id:{b['id']} {b['content_text'][:80]}...")
                else:
                    report_lines.append("✅ 反向审计：全部需求块均已被引用，无漏抽")

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM source_block WHERE doc_name=%s AND doc_version=%s",
                (doc_name, doc_version)
            )
            total = cur.fetchone()["cnt"]
            report_lines.append(f"\n源文档 {doc_name} / {doc_version} 共 {total} 个 source_block")
    finally:
        conn.close()

    return "\n".join(report_lines), result