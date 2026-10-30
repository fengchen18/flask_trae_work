# """从 docx 生成 source_block 入库 + 输出 block_list.txt（自包含，不依赖 test_yaml_cases）"""
# import hashlib
# from pathlib import Path
# from docx import Document
# import pymysql
# from pymysql.cursors import DictCursor
#
#
# class ConnectMysql:
#     """轻量 MySQL 连接类（从原项目内联过来的）"""
#     def __init__(self, host, user, password, port=3306, database=None, charset="utf8mb4"):
#         self.conn = pymysql.connect(
#             host=host, user=user, password=password, port=port,
#             database=database, charset=charset,
#             cursorclass=DictCursor, autocommit=True,
#         )
#         self.cursor = self.conn.cursor()
#
#     def execute_sql(self, sql, args=None):
#         self.cursor.execute(sql, args)
#         return self.cursor.rowcount
#
#     def query_sql(self, sql, args=None):
#         self.cursor.execute(sql, args)
#         return self.cursor.fetchall()
#
#     def close(self):
#         try:
#             if self.cursor: self.cursor.close()
#             if self.conn: self.conn.close()
#         except Exception:
#             pass
#
#
# def calc_sha256(text: str) -> str:
#     return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
#
#
# NOISE_KEYWORDS = [
#     "版本", "修订记录", "变更历史", "目录", "版权", "修改人",
#     "日期", "第*页", "历史版本", "审批", "签名", "文档说明"
# ]
#
#
# def preprocess_docx(docx_path, doc_name, doc_version, block_list_file, db_config):
#     """解析 docx → 入库 source_block → 输出 block_list.txt"""
#     doc = Document(docx_path)
#     db_conn = ConnectMysql(**db_config)
#
#     try:
#         # 幂等：先删旧记录
#         db_conn.execute_sql(
#             "DELETE FROM source_block WHERE doc_name=%s AND doc_version=%s",
#             args=(doc_name, doc_version)
#         )
#
#         # 段落
#         for para in doc.paragraphs:
#             txt = para.text.strip()
#             if len(txt) < 12:
#                 continue
#             if any(kw in txt for kw in NOISE_KEYWORDS):
#                 continue
#             h_val = calc_sha256(txt)
#             db_conn.execute_sql(
#                 "INSERT INTO source_block(doc_name,doc_version,content_text,content_hash) VALUES (%s,%s,%s,%s)",
#                 args=(doc_name, doc_version, txt, h_val)
#             )
#
#         # 表格
#         for table in doc.tables:
#             row_lines = []
#             for row in table.rows:
#                 cell_texts = [c.text.strip() for c in row.cells if c.text.strip()]
#                 if cell_texts:
#                     row_lines.append(" | ".join(cell_texts))
#             full_text = "\n".join(row_lines).strip()
#             if len(full_text) >= 20:
#                 h_val = calc_sha256(full_text)
#                 db_conn.execute_sql(
#                     "INSERT INTO source_block(doc_name,doc_version,content_text,content_hash) VALUES (%s,%s,%s,%s)",
#                     args=(doc_name, doc_version, full_text, h_val)
#                 )
#
#         # 查本次入库
#         block_list = db_conn.query_sql(
#             "SELECT id, content_text FROM source_block WHERE doc_name=%s AND doc_version=%s ORDER BY id ASC",
#             args=(doc_name, doc_version)
#         )
#
#         # 写清单文件
#         lines = [
#             f"文档名称：{doc_name}，版本：{doc_version}",
#             "【约束：生成测试用例时，证据块ID只能使用下面清单内的ID，禁止编造不存在的block_id；无匹配业务块填空】",
#         ]
#         for item in block_list:
#             short_text = item["content_text"][0:160].replace("\n", " ")
#             lines.append(f"block_id:{item['id']} 片段摘要：{short_text}")
#         Path(block_list_file).parent.mkdir(parents=True, exist_ok=True)
#         Path(block_list_file).write_text("\n".join(lines), encoding="utf-8")
#
#         return block_list
#     finally:
#         db_conn.close()
"""从 docx 生成 source_block 入库 + 输出 block_list.txt（自包含，不依赖 test_yaml_cases）"""
"""从 docx 生成 source_block 入库 + 输出 block_list.txt（彻底切碎版）"""
import hashlib
import re
from pathlib import Path
from docx import Document
import pymysql
from pymysql.cursors import DictCursor


class ConnectMysql:
    def __init__(self, host, user, password, port=3306, database=None, charset="utf8mb4"):
        self.conn = pymysql.connect(
            host=host, user=user, password=password, port=port,
            database=database, charset=charset,
            cursorclass=DictCursor, autocommit=True,
        )
        self.cursor = self.conn.cursor()

    def execute_sql(self, sql, args=None):
        self.cursor.execute(sql, args)
        return self.cursor.rowcount

    def query_sql(self, sql, args=None):
        self.cursor.execute(sql, args)
        return self.cursor.fetchall()

    def close(self):
        try:
            if self.cursor: self.cursor.close()
            if self.conn: self.conn.close()
        except Exception:
            pass


def calc_sha256(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


# NOISE_KEYWORDS = [
#     "版本", "修订记录", "变更历史", "目录", "版权", "修改人",
#     "日期", "第*页", "历史版本", "审批", "签名", "文档说明"
# ]

# 增加更苛刻的噪声词
NOISE_KEYWORDS = [
    "版本", "修订记录", "变更历史", "目录", "版权", "修改人",
    "日期", "第*页", "历史版本", "审批", "签名", "文档说明",
    "功能需求概述", "功能简述及功能目的", "用户对象及场景说明",
    "功能适用平台", "数据支持/数据来源", "业务规则", "功能需求描述"
]

def preprocess_docx(docx_path, doc_name, doc_version, block_list_file, db_config):
    doc = Document(docx_path)
    db_conn = ConnectMysql(**db_config)
    processed_hashes = set()

    def clean_and_split_text(text):
        """清洗文本并切分：替换 <br> 并按标点切碎"""
        if not text:
            return []
        # 【关键修复】把 HTML 的换行标签统一替换为真正的换行符
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

        # 按换行、句号、分号、问号、感叹号切碎
        parts = re.split(r'[\n。；？！]', text)
        return [p.strip() for p in parts]

    def insert_block(text):
        text = text.strip()
        if len(text) < 8:  # 过滤过短的碎片
            return
        if any(kw in text for kw in NOISE_KEYWORDS):
            return
        # 【新增】过滤掉类似 "四、" "1、" "6.1" 这种纯章节标题
        if re.match(r'^[一二三四五六七八九十0-9\.\s、]+$', text):
            return
        h_val = calc_sha256(text)
        if h_val in processed_hashes:
            return
        processed_hashes.add(h_val)
        db_conn.execute_sql(
            "INSERT INTO source_block(doc_name,doc_version,content_text,content_hash) VALUES (%s,%s,%s,%s)",
            args=(doc_name, doc_version, text, h_val)
        )

    try:
        # 幂等：先删旧记录
        db_conn.execute_sql(
            "DELETE FROM source_block WHERE doc_name=%s AND doc_version=%s",
            args=(doc_name, doc_version)
        )

        # 1. 处理普通段落
        for para in doc.paragraphs:
            for sent in clean_and_split_text(para.text):
                insert_block(sent)

        # 2. 处理表格（因为需求详情全在单元格里，所以要深入单元格）
        for table in doc.tables:
            for row in table.rows:
                # 遍历每个单元格
                for cell in row.cells:
                    cell_text = cell.text.strip()
                    if not cell_text:
                        continue

                    # 如果单元格很短（比如表头、需求ID），直接存成一行
                    if len(cell_text) <= 30:
                        insert_block(cell_text)
                    else:
                        # 如果单元格很长，执行切碎逻辑
                        for sent in clean_and_split_text(cell_text):
                            insert_block(sent)

        # 查本次入库
        block_list = db_conn.query_sql(
            "SELECT id, content_text FROM source_block WHERE doc_name=%s AND doc_version=%s ORDER BY id ASC",
            args=(doc_name, doc_version)
        )

        # 写清单文件（直接把纯文本喂给 AI，禁止它去读原文件）
        lines = [
            f"文档名称：{doc_name}，版本：{doc_version}",
            "【约束：证据块ID只能使用下面清单内的ID，禁止编造；请直接基于以下文本生成用例，严禁去读取原始 docx 文件】\n",
        ]
        for item in block_list:
            full_text = item["content_text"].replace("\n", " ").strip()
            lines.append(f"block_id:{item['id']} | 内容：{full_text}")

        Path(block_list_file).parent.mkdir(parents=True, exist_ok=True)
        Path(block_list_file).write_text("\n".join(lines), encoding="utf-8")

        return block_list
    finally:
        db_conn.close()