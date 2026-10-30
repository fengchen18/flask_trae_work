# """Flask Web 平台主入口"""
# import os
# import uuid
# from pathlib import Path
#
# from flask import (
#     Flask, render_template, request, redirect, url_for,
#     jsonify, Response, flash, abort,
# )
# from werkzeug.utils import secure_filename
#
# from config import Config
# from models import db, WebTestCase
# from services.importer import import_md_file
# from services.trae_service import start_generate_task, TASKS, TASKS_LOCK
#
#
# app = Flask(__name__)
# app.config.from_object(Config)
# Config.init_dirs()
#
# db.init_app(app)
#
# with app.app_context():
#     db.create_all()
#
#
# # ============================================================
# # 页面：首页 → 重定向到用例列表
# # ============================================================
# @app.route("/")
# def index():
#     return redirect(url_for("case_list"))
#
#
# # ============================================================
# # 页面：用例列表（分页 + 搜索）
# # ============================================================
# @app.route("/cases")
# def case_list():
#     page = request.args.get("page", 1, type=int)
#     keyword = request.args.get("q", "", type=str).strip()
#     source = request.args.get("source", "", type=str).strip()
#
#     query = WebTestCase.query
#     if keyword:
#         like = f"%{keyword}%"
#         query = query.filter(
#             db.or_(
#                 WebTestCase.title.like(like),
#                 WebTestCase.tags.like(like),
#                 WebTestCase.project.like(like),
#             )
#         )
#     if source:
#         query = query.filter(WebTestCase.source == source)
#
#     pagination = query.order_by(WebTestCase.id.desc()).paginate(
#         page=page, per_page=Config.PER_PAGE, error_out=False
#     )
#
#     return render_template(
#         "cases/list.html",
#         pagination=pagination,
#         cases=pagination.items,
#         keyword=keyword,
#         source=source,
#     )
#
#
# from services.exporter import export_cases_to_excel
# from flask import send_file
#
#
# @app.route("/cases/export")
# def case_export():
#     from services.exporter import export_cases_to_excel
#     from flask import send_file
#
#     keyword = request.args.get("q", "", type=str).strip()
#     source = request.args.get("source", "", type=str).strip()
#     ids_str = request.args.get("ids", "", type=str).strip()
#
#     ids = None
#     if ids_str:
#         ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
#         if not ids:
#             return "没有有效的选中 ID", 400
#
#     try:
#         buf, filename = export_cases_to_excel(keyword, source, ids)
#     except Exception as e:
#         import traceback
#         print(f"[导出] 失败：{traceback.format_exc()}", flush=True)
#         return f"导出失败：{e}", 500
#
#     return send_file(
#         buf,
#         as_attachment=True,
#         download_name=filename,
#         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#     )
#
#
# from services.devops_client import DevOpsClient
#
# # 推送生成的用例到devops平台
# @app.route("/cases/push-devops", methods=["POST"])
# def case_push_devops():
#     from models import WebTestCase, db
#     from services.devops_client import DevOpsClient
#
#     keyword = request.form.get("q", "").strip()
#     source = request.form.get("source", "").strip()
#     test_set_id = request.form.get("test_set_id", "").strip() or None
#     # 获取前端传的勾选id列表
#     case_ids = request.form.getlist("case_ids")
#
#     query = WebTestCase.query
#     # 如果前端传了勾选ID，优先按ID筛选
#     if case_ids:
#         # case_ids是字符串数组，in_可以直接接收
#         query = query.filter(WebTestCase.id.in_(case_ids))
#     else:
#         # 兜底：没有勾选时，按搜索条件筛选全部（和导出逻辑对齐）
#         if keyword:
#             like = f"%{keyword}%"
#             query = query.filter(db.or_(
#                 WebTestCase.title.like(like),
#                 WebTestCase.tags.like(like),
#                 WebTestCase.project.like(like),
#             ))
#         if source:
#             query = query.filter(WebTestCase.source == source)
#
#     cases = query.order_by(WebTestCase.id.asc()).all()
#
#     if not cases:
#         return jsonify({"ok": False, "msg": "没有符合条件的用例"})
#
#     try:
#         client = DevOpsClient()
#         result = client.push_cases(cases, test_set_id=test_set_id)
#
#         if result.get("code") == 0:
#             ids = result.get("data", [])
#             return jsonify({
#                 "ok": True,
#                 "msg": f"成功推送 {len(ids)} 条用例到 DevOps",
#                 "ids": ids,
#             })
#         else:
#             return jsonify({
#                 "ok": False,
#                 "msg": f"推送失败：{result.get('msg') or '未知错误'}",
#                 "detail": result,
#             })
#     except Exception as e:
#         import traceback
#         tb = traceback.format_exc()
#         print(f"[DevOps 推送] 失败：{tb}", flush=True)
#         return jsonify({
#             "ok": False,
#             "msg": f"请求异常：{e}",
#             "detail": tb,
#         })
#
#
# # ============================================================
# # 页面：新增用例
# # ============================================================
# @app.route("/cases/new", methods=["GET", "POST"])
# def case_new():
#     if request.method == "POST":
#         tc = WebTestCase(
#             title=request.form.get("title", "").strip(),
#             priority=request.form.get("priority", "").strip(),
#             owner=request.form.get("owner", "").strip(),
#             tags=request.form.get("tags", "").strip(),
#             project=request.form.get("project", "").strip(),
#             case_set=request.form.get("case_set", "").strip(),
#             case_type=request.form.get("case_type", "").strip(),
#             precondition=request.form.get("precondition", ""),
#             steps=request.form.get("steps", ""),
#             expected=request.form.get("expected", ""),
#             evidence_source=request.form.get("evidence_source", ""),
#             evidence_level=request.form.get("evidence_level", ""),
#             evi_block_ids=request.form.get("evi_block_ids", ""),
#             doc_name=request.form.get("doc_name", ""),
#             doc_version=request.form.get("doc_version", ""),
#             source="manual",
#         )
#         db.session.add(tc)
#         db.session.commit()
#         flash("用例新增成功", "success")
#         return redirect(url_for("case_list"))
#
#     return render_template("cases/form.html", case=None)
#
#
# # ============================================================
# # 页面：编辑用例
# # ============================================================
# @app.route("/cases/<int:case_id>/edit", methods=["GET", "POST"])
# def case_edit(case_id):
#     tc = WebTestCase.query.get_or_404(case_id)
#
#     if request.method == "POST":
#         tc.title = request.form.get("title", "").strip()
#         tc.priority = request.form.get("priority", "").strip()
#         tc.owner = request.form.get("owner", "").strip()
#         tc.tags = request.form.get("tags", "").strip()
#         tc.project = request.form.get("project", "").strip()
#         tc.case_set = request.form.get("case_set", "").strip()
#         tc.case_type = request.form.get("case_type", "").strip()
#         tc.precondition = request.form.get("precondition", "")
#         tc.steps = request.form.get("steps", "")
#         tc.expected = request.form.get("expected", "")
#         tc.evidence_source = request.form.get("evidence_source", "")
#         tc.evidence_level = request.form.get("evidence_level", "")
#         tc.evi_block_ids = request.form.get("evi_block_ids", "")
#         tc.doc_name = request.form.get("doc_name", "")
#         tc.doc_version = request.form.get("doc_version", "")
#         db.session.commit()
#         flash("用例更新成功", "success")
#         return redirect(url_for("case_list"))
#
#     return render_template("cases/form.html", case=tc)
#
#
# # ============================================================
# # 动作：删除用例
# # ============================================================
# @app.route("/cases/<int:case_id>/delete", methods=["POST"])
# def case_delete(case_id):
#     tc = WebTestCase.query.get_or_404(case_id)
#     db.session.delete(tc)
#     db.session.commit()
#     flash("用例已删除", "success")
#     return redirect(url_for("case_list"))
# # 批量删除
# @app.route("/cases/batch-delete", methods=["POST"])
# def case_batch_delete():
#     from models import WebTestCase, db
#     data = request.get_json(silent=True) or {}
#     ids = data.get("ids", [])
#     if not ids:
#         return jsonify({"ok": False, "msg": "没有选中任何用例"})
#     try:
#         count = WebTestCase.query.filter(WebTestCase.id.in_(ids)).delete(
#             synchronize_session=False
#         )
#         db.session.commit()
#         return jsonify({"ok": True, "msg": f"已删除 {count} 条", "count": count})
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({"ok": False, "msg": str(e)})
#
# # ============================================================
# # 页面：导入 md
# # ============================================================
# @app.route("/cases/import", methods=["GET", "POST"])
# def case_import():
#     if request.method == "POST":
#         f = request.files.get("file")
#         if not f or not f.filename:
#             flash("请选择 md 文件", "danger")
#             return redirect(url_for("case_import"))
#
#         filename = secure_filename(f.filename)
#         if not filename.lower().endswith((".md", ".markdown")):
#             flash("只支持 .md / .markdown 文件", "danger")
#             return redirect(url_for("case_import"))
#
#         save_path = Path(Config.UPLOAD_FOLDER) / f"{uuid.uuid4().hex}_{filename}"
#         f.save(str(save_path))
#
#         doc_name = request.form.get("doc_name", "").strip()
#         doc_version = request.form.get("doc_version", "").strip()
#
#         success, total = import_md_file(save_path, doc_name, doc_version)
#         flash(f"导入完成：成功 {success} 条 / 共解析 {total} 条", "success")
#         return redirect(url_for("case_list"))
#
#     return render_template("cases/import.html")
#
#
# # ============================================================
# # 页面：AI 生成
# # ============================================================
# @app.route("/cases/generate", methods=["GET", "POST"])
# def case_generate():
#     if request.method == "POST":
#         f = request.files.get("file")
#         if not f or not f.filename:
#             return jsonify({"ok": False, "msg": "请上传 docx 文件"})
#
#         filename = secure_filename(f.filename)
#         if not filename.lower().endswith(".docx"):
#             return jsonify({"ok": False, "msg": "只支持 .docx 文件"})
#
#         save_path = Path(Config.UPLOAD_FOLDER) / f"{uuid.uuid4().hex}_{filename}"
#         f.save(str(save_path))
#
#         doc_name = request.form.get("doc_name", "").strip() or filename
#         doc_version = request.form.get("doc_version", "").strip() or "V1.0.0"
#
#         task_id = start_generate_task(str(save_path), doc_name, doc_version, app)
#         return jsonify({"ok": True, "task_id": task_id})
#
#     return render_template("cases/generate.html")
#
#
# # ============================================================
# # SSE：实时推送生成进度
# # ============================================================
# @app.route("/cases/generate/stream/<task_id>")
# def case_generate_stream(task_id):
#     with TASKS_LOCK:
#         q = TASKS.get(task_id)
#     if not q:
#         return jsonify({"ok": False, "msg": "任务不存在"}), 404
#
#     def event_stream():
#         while True:
#             try:
#                 item = q.get(timeout=60)
#             except Exception:
#                 yield "data: {\"kind\":\"ping\"}\n\n"
#                 continue
#
#             if item.get("kind") == "end":
#                 yield "data: {\"kind\":\"end\"}\n\n"
#                 break
#
#             payload = {
#                 "kind": item.get("kind"),
#                 "msg": item.get("msg", ""),
#             }
#             # 如果是 stage 事件，把 stage 字段也带出去
#             if item.get("stage"):
#                 payload["stage"] = item["stage"]
#             import json as _json
#             yield f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"
#
#     return Response(event_stream(), mimetype="text/event-stream",
#                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
#
# from services.trae_service import (
#     start_generate_task, followup_task, TASKS, TASKS_LOCK,
# )
#
#
# @app.route("/cases/generate/followup", methods=["POST"])
# def case_generate_followup():
#     """追问：复用同一个 task 的会话"""
#     data = request.get_json(silent=True) or {}
#     task_id = (data.get("task_id") or "").strip()
#     question = (data.get("question") or "").strip()
#
#     if not task_id or not question:
#         return jsonify({"ok": False, "msg": "参数不完整"})
#
#     with TASKS_LOCK:
#         if task_id not in TASKS:
#             return jsonify({"ok": False, "msg": "任务不存在或已过期"})
#
#     followup_task(task_id, question, app)
#     return jsonify({"ok": True, "task_id": task_id})
#
# from services.trae_service import (
#     start_generate_task, followup_task, confirm_import_task,
#     TASKS, TASKS_LOCK,
# )
#
#
# @app.route("/cases/generate/confirm", methods=["POST"])
# def case_generate_confirm():
#     """用户确认入库"""
#     data = request.get_json(silent=True) or {}
#     task_id = (data.get("task_id") or "").strip()
#     if not task_id:
#         return jsonify({"ok": False, "msg": "缺少 task_id"})
#     with TASKS_LOCK:
#         if task_id not in TASKS:
#             return jsonify({"ok": False, "msg": "任务不存在"})
#     confirm_import_task(task_id, app)
#     return jsonify({"ok": True})
#
#
# @app.route("/cases/generate/discard", methods=["POST"])
# def case_generate_discard():
#     """用户放弃，不入库"""
#     data = request.get_json(silent=True) or {}
#     task_id = (data.get("task_id") or "").strip()
#     print(f"[TASK {task_id}] [用户放弃] 不入库", flush=True)
#     return jsonify({"ok": True})
#
#
# @app.errorhandler(Exception)
# def handle_exception(e):
#     """所有未捕获异常都返回 JSON，方便前端看到真正错误"""
#     import traceback
#     tb = traceback.format_exc()
#     print(f"[未捕获异常] {tb}", flush=True)
#     return jsonify({
#         "ok": False,
#         "msg": f"服务端异常：{type(e).__name__}: {e}",
#         "detail": tb,
#     }), 500
#
# # ============================================================
# # 启动
# # ============================================================
# # if __name__ == "__main__":
# #     app.run(host="127.0.0.1", port=5000, debug=True, threaded=True,use_reloader=False)
# if __name__ == "__main__":
#     # 启动时预热：尝试拿一次 token
#     try:
#         from services.devops_auth import get_token
#         get_token()
#         print("[启动] DevOps token 已就绪")
#     except Exception as e:
#         print(f"[启动] DevOps 预登录失败（不影响主服务）：{e}")
#
#     app.run(host="127.0.0.1", port=5000, debug=True, threaded=True, use_reloader=False)

"""Flask Web 平台主入口"""
import os
import uuid
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, Response, flash, abort, send_file,
)
from werkzeug.utils import secure_filename

from config import Config
from models import db, WebTestCase, Expert
from services.importer import import_md_file
from services.exporter import export_cases_to_excel
from services.trae_service import (
    start_generate_task, followup_task, confirm_import_task,
    TASKS, TASKS_LOCK, push,
)
from services.devops_client import DevOpsClient


app = Flask(__name__)
app.config.from_object(Config)
Config.init_dirs()

db.init_app(app)

with app.app_context():
    # 这一步会自动创建还没存在的新表（比如 expert 表）
    db.create_all()

    # ===== 自动迁移：幂等，重复运行无副作用 =====
    from sqlalchemy import text

    # 1. web_test_case 表的迁移
    for col, ddl in [
        ("case_set_id", "ALTER TABLE web_test_case ADD COLUMN case_set_id INT NULL"),
        ("requirement_doc_id", "ALTER TABLE web_test_case ADD COLUMN requirement_doc_id INT NULL"),
        ("test_point_id", "ALTER TABLE web_test_case ADD COLUMN test_point_id INT NULL"),
        ("status", "ALTER TABLE web_test_case ADD COLUMN status VARCHAR(20) DEFAULT 'draft'")
    ]:
        try:
            with db.engine.begin() as conn:
                conn.execute(text(ddl))
            print(f"[迁移] web_test_case 添加列 {col}")
        except Exception:
            pass

    # 2. test_point 表的迁移
    for col, ddl in [
        ("intent", "ALTER TABLE test_point ADD COLUMN intent TEXT NULL"),
        ("scene", "ALTER TABLE test_point ADD COLUMN scene VARCHAR(100) NULL"),
        ("is_attention", "ALTER TABLE test_point ADD COLUMN is_attention BOOLEAN DEFAULT FALSE"),
        ("method", "ALTER TABLE test_point ADD COLUMN method VARCHAR(50) NULL"),
        ("expert_opinion", "ALTER TABLE test_point ADD COLUMN expert_opinion VARCHAR(50) NULL"),
        ("expert_advice", "ALTER TABLE test_point ADD COLUMN expert_advice TEXT NULL"),
        ("expert_name", "ALTER TABLE test_point ADD COLUMN expert_name VARCHAR(100) NULL"),

    ]:
        try:
            with db.engine.begin() as conn:
                conn.execute(text(ddl))
            print(f"[迁移] test_point 添加列 {col}")
        except Exception:
            pass

    # 3. expert 表的迁移（如果之前已经建过表，这里把两个新字段补上）
    # 3. expert 表的迁移
    for col, ddl in [
        # 修改 avatar 的默认值为普通字符串
        ("avatar", "ALTER TABLE expert ADD COLUMN avatar VARCHAR(50) DEFAULT 'default'"),
        ("language", "ALTER TABLE expert ADD COLUMN language VARCHAR(20) DEFAULT '中文'")
    ]:
        try:
            with db.engine.begin() as conn:
                conn.execute(text(ddl))
            print(f"[迁移] expert 添加列 {col}")
        except Exception as e:
            print(f"[迁移] expert 添加列 {col} 失败/已存在：{e}") # 把 pass 改成 print

    # ===== 数据迁移：只在首次运行（requirement_doc 空表）时执行 =====
    from models import RequirementDoc, CaseSet
    if RequirementDoc.query.count() == 0:
        try:
            existing_docs = db.session.query(
                WebTestCase.doc_name, WebTestCase.doc_version
            ).filter(WebTestCase.doc_name.isnot(None)).filter(
                WebTestCase.doc_name != ""
            ).distinct().all()

            for doc_name, doc_version in existing_docs:
                doc = RequirementDoc.query.filter_by(
                    doc_name=doc_name, doc_version=doc_version
                ).first()
                if not doc:
                    doc = RequirementDoc(doc_name=doc_name, doc_version=doc_version or "")
                    db.session.add(doc)
                    db.session.flush()

                cs = CaseSet.query.filter_by(name=doc_name).first()
                if not cs:
                    cs = CaseSet(name=doc_name)
                    db.session.add(cs)
                    db.session.flush()

                WebTestCase.query.filter_by(
                    doc_name=doc_name, doc_version=doc_version
                ).update({
                    "requirement_doc_id": doc.id,
                    "case_set_id": cs.id,
                }, synchronize_session=False)

            db.session.commit()
            print(f"[迁移] 首次数据迁移完成，处理了 {len(existing_docs)} 份文档")
        except Exception as e:
            db.session.rollback()
            print(f"[迁移] 失败：{e}")
    # 已有数据则跳过

def get_trae_models():
    """动态调用 traecli models 获取当前支持的模型列表给专家团队配置大模型使用"""
    import subprocess
    from config import Config
    try:
        res = subprocess.run(
            [Config.CLI_BIN, "models"],
            capture_output=True, text=True, encoding="utf-8", timeout=10
        )
        # 解析输出，去掉空行和无关的提示语
        models = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if line and not line.startswith(("Usage", "Flags", "Available", "Aliases")):
                models.append(line)
        return models if models else ["Doubao-Seed-Evolving"]
    except Exception:
        return ["Doubao-Seed-Evolving", "GLM-5.3", "DeepSeek-V4.1-Flash"] # 兜底

@app.route("/devops/test-sets")
def devops_test_sets():
    """获取 DevOps 用例集目录树（用于前端选择目标目录）"""
    try:
        client = DevOpsClient()
        result = client.get_test_set_tree()
        if result.get("code") != 0:
            return jsonify({"ok": False, "msg": result.get("msg") or "获取失败"})
        return jsonify({"ok": True, "data": result.get("data", [])})
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[DevOps 目录树] 失败：{tb}", flush=True)
        return jsonify({"ok": False, "msg": str(e), "detail": tb})

@app.route("/case-sets/tree")
def case_sets_tree():
    """返回用例集树（JSON）"""
    from models import CaseSet, WebTestCase
    from sqlalchemy import func

    # 统计每个用例集下的用例数
    cnt_rows = db.session.query(
        WebTestCase.case_set_id, func.count(WebTestCase.id)
    ).group_by(WebTestCase.case_set_id).all()
    cnt_map = {cid: c for cid, c in cnt_rows if cid}

    all_sets = CaseSet.query.order_by(CaseSet.sort_order, CaseSet.id).all()

    # 建树
    nodes = {s.id: {
        "id": s.id, "name": s.name, "parent_id": s.parent_id,
        "count": cnt_map.get(s.id, 0), "children": [],
    } for s in all_sets}

    roots = []
    for s in all_sets:
        node = nodes[s.id]
        if s.parent_id and s.parent_id in nodes:
            nodes[s.parent_id]["children"].append(node)
        else:
            roots.append(node)

    return jsonify({"ok": True, "data": roots})


@app.route("/case-sets/create", methods=["POST"])
def case_set_create():
    from models import CaseSet
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    parent_id = data.get("parent_id")
    if not name:
        return jsonify({"ok": False, "msg": "名称不能为空"})
    cs = CaseSet(name=name, parent_id=parent_id)
    db.session.add(cs)
    db.session.commit()
    return jsonify({"ok": True, "data": cs.to_dict()})


@app.route("/case-sets/<int:cs_id>/rename", methods=["POST"])
def case_set_rename(cs_id):
    from models import CaseSet
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "msg": "名称不能为空"})
    cs = CaseSet.query.get_or_404(cs_id)
    cs.name = name
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/case-sets/<int:cs_id>/delete", methods=["POST"])
def case_set_delete(cs_id):
    from models import CaseSet, WebTestCase
    cs = CaseSet.query.get_or_404(cs_id)
    # 把该用例集下的用例设为"未分类"
    WebTestCase.query.filter_by(case_set_id=cs_id).update(
        {"case_set_id": None}, synchronize_session=False
    )
    db.session.delete(cs)
    db.session.commit()
    return jsonify({"ok": True})

# ============================================================
# 页面：首页 → 需求文档列表
# ============================================================
@app.route("/")
def index():
    return redirect(url_for("doc_list"))


# ============================================================
# 页面：需求文档列表
# ============================================================
@app.route("/docs")
def doc_list():
    """需求文档存档列表"""
    from models import RequirementDoc, WebTestCase
    from sqlalchemy import func

    docs = db.session.query(
        RequirementDoc,
        func.count(WebTestCase.id).label("case_cnt"),
    ).outerjoin(
        WebTestCase, WebTestCase.requirement_doc_id == RequirementDoc.id
    ).group_by(
        RequirementDoc.id
    ).order_by(
        RequirementDoc.uploaded_at.desc()
    ).all()

    docs_data = []
    for doc, cnt in docs:
        docs_data.append({
            "id": doc.id,
            "doc_name": doc.doc_name,
            "doc_version": doc.doc_version,
            "uploaded_at": doc.uploaded_at,
            "case_cnt": cnt,
        })

    return render_template("docs/list.html", docs=docs_data)


@app.route("/docs/<int:doc_id>/delete", methods=["POST"])
def doc_delete(doc_id):
    from models import RequirementDoc
    doc = RequirementDoc.query.get_or_404(doc_id)
    db.session.delete(doc)
    db.session.commit()
    flash("需求文档已删除", "success")
    return redirect(url_for("doc_list"))


# ==========================================
# 测试点流水线路由
# ==========================================
from services.test_point_service import extract_points_task, generate_from_points_task


@app.route("/test-points/extract", methods=["POST"])
def api_extract_points():
    """触发提取测试点"""
    data = request.json
    doc_name = data.get("doc_name")
    doc_version = data.get("doc_version")
    docx_path = data.get("docx_path")  # 实际可以用你存在库里的

    from services.trae_service import create_task
    task_id = create_task()

    import threading
    threading.Thread(
        target=extract_points_task,
        args=(task_id, docx_path, doc_name, doc_version, app, push),
        daemon=True
    ).start()
    return jsonify({"ok": True, "task_id": task_id})





@app.route("/test-points/<int:point_id>/status", methods=["POST"])
def api_update_point_status(point_id):
    """更新测试点状态（通过/拒绝）"""
    from models import TestPoint, db
    data = request.json
    status = data.get("status")  # approved / rejected

    # 修复：使用 db.session.get
    tp = db.session.get(TestPoint, point_id)
    if not tp:
        return jsonify({"ok": False, "msg": "测试点不存在"}), 404

    tp.status = status
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/test-points/generate-cases", methods=["POST"])
def api_generate_cases_from_points():
    """触发扩写用例"""
    data = request.json
    point_ids = data.get("ids", [])
    if not point_ids:
        return jsonify({"ok": False, "msg": "请选择测试点"})

    from services.trae_service import create_task
    task_id = create_task()

    import threading
    threading.Thread(
        target=generate_from_points_task,
        args=(task_id, point_ids, app, push),
        daemon=True
    ).start()
    return jsonify({"ok": True, "task_id": task_id})


# @app.route("/test-points/list")
# def test_point_list_page():
#     from models import TestPoint, RequirementDoc
#     from services.preprocess import ConnectMysql
#
#     # 需关注排前面，然后按ID排序
#     points = TestPoint.query.order_by(TestPoint.is_attention.desc(), TestPoint.id.asc()).all()
#     experts = Expert.query.all()  # <--- 新增这行
#
#     # 获取真实原文
#     db_config = {"host": "127.0.0.1", "user": "root", "password": "wlw123456", "port": 3306, "database": "my_project"}
#     db_conn = ConnectMysql(**db_config)
#
#     points_data = []
#     scene_counts = {}
#     matrix_data = {}
#
#     for p in points:
#         p_dict = p.to_dict()
#         # 拼接真实原文
#         quotes = []
#         if p.evidence_ids:
#             for bid in p.evidence_ids.split(";"):
#                 bid = bid.strip()
#                 if bid.isdigit():
#                     res = db_conn.query_sql("SELECT content_text FROM source_block WHERE id=%s", args=(int(bid),))
#                     if res:
#                         quotes.append(f"[Block {bid}] {res[0]['content_text']}")
#         p_dict["quotes"] = "\n".join(quotes) if quotes else "无原文依据（AI推导）"
#         points_data.append(p_dict)
#
#         # 统计
#         scene_counts[p.scene] = scene_counts.get(p.scene, 0) + 1
#         if p.scene not in matrix_data:
#             matrix_data[p.scene] = {}
#         cat = p.category if p.category != 'UI' else '界面'
#         matrix_data[p.scene][cat] = matrix_data[p.scene].get(cat, 0) + 1
#
#     db_conn.close()
#
#     approved_count = sum(1 for p in points if p.status == 'approved')
#     pending_count = len(points) - approved_count
#
#     return render_template(
#         "test_points/list.html",
#         points=points_data,
#         experts=experts,  # <--- 传给模板
#         scene_counts=scene_counts,
#         matrix_data=matrix_data,
#         approved_count=approved_count,
#         pending_count=pending_count
#     )
@app.route("/test-points/list")
def test_point_list_page():
    from models import TestPoint, Expert
    from services.preprocess import ConnectMysql

    # 需关注排前面，然后按ID排序
    points = TestPoint.query.order_by(TestPoint.is_attention.desc(), TestPoint.id.asc()).all()

    # 获取真实原文
    db_config = {"host": "127.0.0.1", "user": "root", "password": "wlw123456", "port": 3306, "database": "my_project"}
    db_conn = ConnectMysql(**db_config)

    points_data = []
    scene_counts = {}
    matrix_data = {}

    for p in points:
        p_dict = p.to_dict()
        # 拼接真实原文
        quotes = []
        if p.evidence_ids:
            for bid in p.evidence_ids.split(";"):
                bid = bid.strip()
                if bid.isdigit():
                    res = db_conn.query_sql("SELECT content_text FROM source_block WHERE id=%s", args=(int(bid),))
                    if res:
                        quotes.append(f"[Block {bid}] {res[0]['content_text']}")
        p_dict["quotes"] = "\n".join(quotes) if quotes else "无原文依据（AI推导）"
        points_data.append(p_dict)

        # 统计
        scene = p.scene or "通用场景"
        scene_counts[scene] = scene_counts.get(scene, 0) + 1
        if scene not in matrix_data:
            matrix_data[scene] = {}
        cat = p.category if p.category != 'UI' else '界面'
        matrix_data[scene][cat] = matrix_data[scene].get(cat, 0) + 1

    db_conn.close()

    # ====== 新增：按场景分组 ======
    grouped_points = {}
    for p in points_data:
        scene = p["scene"] or "通用场景"
        if scene not in grouped_points:
            grouped_points[scene] = []
        grouped_points[scene].append(p)

    approved_count = sum(1 for p in points if p.status == 'approved')
    pending_count = len(points) - approved_count

    return render_template(
        "test_points/list.html",
        grouped_points=grouped_points,  # 传分组后的数据
        points=points_data,  # 依然传全量，用于顶部统计
        experts=Expert.query.all(),
        scene_counts=scene_counts,
        matrix_data=matrix_data,
        approved_count=approved_count,
        pending_count=pending_count
    )


# 新增一个“采纳建议”的接口（把状态改为通过，或者撤销需关注）
@app.route("/test-points/<int:point_id>/adopt-advice", methods=["POST"])
def api_adopt_advice(point_id):
    from models import TestPoint, db

    tp = db.session.get(TestPoint, point_id)
    if not tp: return jsonify({"ok": False, "msg": "不存在"}), 404
    if tp.expert_opinion == "建议通过":
        tp.status = "approved"
    elif tp.expert_opinion == "建议拒绝":
        tp.status = "rejected"
    # 如果专家说需要关注，也可以采纳
    # tp.is_attention = True
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/test-points/<int:point_id>/regenerate", methods=["POST"])
def api_regenerate_test_point(point_id):
    """根据用户意见，让大模型重写测试点"""
    from models import TestPoint, db
    data = request.json
    user_idea = data.get("idea", "")

    tp = db.session.get(TestPoint, point_id)
    if not tp: return jsonify({"ok": False, "msg": "不存在"}), 404

    # 同步调用大模型重写，因为只重写一条，速度很快
    import subprocess
    from config import Config

    prompt = f"""你是一个高级测试工程师。请根据用户的意见，重写以下测试点。
【原测试点】：{tp.content}
【专家建议】：{tp.expert_advice or '无'}
【用户修改意见】：{user_idea}

请直接输出重写后的【测试点标题】（不要解释，不要引号，只输出一句话）。"""

    # 默认用 Doubao 或者系统默认，你可以换成用户指定的模型
    cmd = [Config.CLI_BIN, "--print", "--permission-mode", "bypass_permissions", prompt]
    proc = subprocess.run(cmd, cwd=Config.TRAE_WORKSPACE, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")

    new_content = proc.stdout.strip()
    if new_content:
        tp.content = new_content
        # 重置专家意见和需关注状态，重新进入待评审
        tp.expert_opinion = ""
        tp.expert_advice = ""
        tp.is_attention = False
        tp.status = "pending"
        db.session.commit()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "AI 重写失败"})


@app.route("/test-points/batch-regenerate", methods=["POST"])
def api_batch_regenerate_test_points():
    """根据用户意见，批量让大模型重写测试点"""
    from models import TestPoint, db
    data = request.json
    ids = data.get("ids", [])
    user_idea = data.get("idea", "")

    if not ids or not user_idea:
        return jsonify({"ok": False, "msg": "请选择测试点并输入修改意见"})

    points = TestPoint.query.filter(TestPoint.id.in_(ids)).all()
    if not points:
        return jsonify({"ok": False, "msg": "未找到测试点"})

    tp_text = "\n".join([f"- ID:{p.id} 原内容:{p.content} 意图:{p.intent}" for p in points])

    prompt = f"""你是一个高级测试工程师。请根据用户的修改意见，批量重写以下测试点。
【用户修改意见】：{user_idea}

输出必须为 JSON 数组，格式如下：
[
  {{"id": 1, "content": "重写后的测试点标题", "intent": "重写后的测试意图"}}
]

======== 测试点清单 ========
{tp_text}
======== 结束 ========
"""
    import subprocess, json
    from config import Config

    # 调用默认模型（你可以根据需要在 config 里配置一个默认的改写模型）
    cmd = [Config.CLI_BIN, "--print", "--permission-mode", "bypass_permissions", prompt]
    proc = subprocess.run(cmd, cwd=Config.TRAE_WORKSPACE, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")

    output = proc.stdout
    if not output:
        return jsonify({"ok": False, "msg": "AI 重写失败，模型无输出"})

    json_str = output.strip()
    if json_str.startswith("```json"):
        json_str = json_str[7:-3].strip()
    elif json_str.startswith("```"):
        json_str = json_str[3:-3].strip()

    try:
        results = json.loads(json_str)
        for item in results:
            tp = TestPoint.query.get(item["id"])
            if tp:
                tp.content = item.get("content", tp.content)
                tp.intent = item.get("intent", tp.intent)
                # 重写后重置所有评审状态
                tp.expert_opinion = ""
                tp.expert_advice = ""
                tp.is_attention = False
                tp.status = "pending"
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"JSON解析失败: {e}"})

@app.route("/test-points/batch-confirm", methods=["POST"])
def api_batch_confirm_test_points():
    """集中确认/修改测试点,及生成测试点后，自动收集测试点中的一些问题，让用户一次性看完"""
    from models import TestPoint, db
    data = request.json
    ids = data.get("ids", [])
    idea = data.get("idea", "")

    if not ids or not idea:
        return jsonify({"ok": False, "msg": "请选择测试点并输入确认意见"})

    points = TestPoint.query.filter(TestPoint.id.in_(ids)).all()
    if not points:
        return jsonify({"ok": False, "msg": "未找到测试点"})

    tp_text = "\n".join([f"- ID:{p.id} 原内容:{p.content} (问题:{p.expert_opinion or '需关注/无原文'})" for p in points])

    prompt = f"""你是一个高级测试工程师。用户对你之前生成的测试点提出了集中确认意见。
请根据用户的回复，重写这些测试点，消除歧义并使其符合规范。

【用户的统一回复】：
{idea}

输出必须为 JSON 数组，格式如下：
[
  {{"id": 1, "content": "修改后的测试点标题", "intent": "修改后的测试意图"}}
]

======== 待确认测试点清单 ========
{tp_text}
======== 结束 ========
"""
    import subprocess, json
    from config import Config

    cmd = [Config.CLI_BIN, "--print", "--permission-mode", "bypass_permissions", prompt]
    proc = subprocess.run(cmd, cwd=Config.TRAE_WORKSPACE, capture_output=True, text=True, encoding="utf-8", errors="replace")

    output = proc.stdout
    if not output:
        return jsonify({"ok": False, "msg": "AI 处理失败，无输出"})

    # 容错提取 JSON
    import re
    json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', output, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        start_idx = output.find('[')
        end_idx = output.rfind(']')
        json_str = output[start_idx:end_idx+1] if start_idx != -1 and end_idx != -1 else output

    try:
        results = json.loads(json_str)
        for item in results:
            tp = db.session.get(TestPoint, item["id"])
            if tp:
                tp.content = item.get("content", tp.content)
                tp.intent = item.get("intent", tp.intent)
                # 确认后，清除警告状态
                tp.expert_opinion = ""
                tp.expert_advice = ""
                tp.is_attention = False
                tp.status = "pending"
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"JSON解析失败: {e}"})

@app.route("/test-points/<int:point_id>/update", methods=["POST"])
def api_update_test_point(point_id):
    """手动编辑测试点"""
    from models import TestPoint, db
    data = request.json
    tp = db.session.get(TestPoint, point_id)
    if not tp: return jsonify({"ok": False, "msg": "不存在"}), 404
    tp.content = data.get("content", tp.content)
    tp.intent = data.get("intent", tp.intent)
    tp.scene = data.get("scene", tp.scene)
    tp.category = data.get("category", tp.category)
    tp.priority = data.get("priority", tp.priority)
    tp.evidence_ids = data.get("evidence_ids", tp.evidence_ids)

    # 编辑后重置状态
    tp.expert_opinion = ""
    tp.is_attention = False
    tp.status = "pending"
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/test-points/expert-review", methods=["POST"])
def api_expert_review_points():
    data = request.json
    point_ids = data.get("ids", [])
    expert_id = data.get("expert_id")

    if not point_ids or not expert_id:
        return jsonify({"ok": False, "msg": "请选择测试点和专家"})

    from services.test_point_service import expert_review_task
    from services.trae_service import create_task, push
    task_id = create_task()
    import threading
    threading.Thread(
        target=expert_review_task,
        args=(task_id, point_ids, expert_id, app, push),
        daemon=True
    ).start()
    return jsonify({"ok": True, "task_id": task_id})  # <--- 返回 task_id

@app.route("/test-points/<int:point_id>/delete", methods=["POST"])
def api_delete_test_point(point_id):
    """删除单个测试点"""
    from models import TestPoint, db
    tp = db.session.get(TestPoint, point_id)
    if not tp: return jsonify({"ok": False, "msg": "不存在"}), 404
    db.session.delete(tp)
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/test-points/batch-delete", methods=["POST"])
def api_batch_delete_test_points():
    """批量删除测试点"""
    from models import TestPoint, db
    data = request.json
    ids = data.get("ids", [])
    if ids:
        TestPoint.query.filter(TestPoint.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
    return jsonify({"ok": True})
# ============================================================
# 页面：用例列表（按用例集筛选）
# ============================================================
@app.route("/cases")
def case_list():
    page = request.args.get("page", 1, type=int)
    keyword = request.args.get("q", "", type=str).strip()
    source = request.args.get("source", "", type=str).strip()
    cs_id = request.args.get("case_set_id", "", type=str).strip()

    # ===== 新增：获取分页大小 =====
    per_page = request.args.get("per_page", 20, type=int)
    if per_page not in [10, 20, 25, 50, 100]:
        per_page = 20
    # ==============================

    query = WebTestCase.query

    if cs_id == "none":
        # 未分类
        query = query.filter(WebTestCase.case_set_id.is_(None))
    elif cs_id and cs_id.isdigit():
        query = query.filter(WebTestCase.case_set_id == int(cs_id))

    if keyword:
        like = f"%{keyword}%"
        query = query.filter(db.or_(
            WebTestCase.title.like(like),
            WebTestCase.tags.like(like),
            WebTestCase.project.like(like),
        ))
    if source:
        query = query.filter(WebTestCase.source == source)

    pagination = query.order_by(WebTestCase.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template(
        "cases/list.html",
        pagination=pagination,
        cases=pagination.items,
        keyword=keyword,
        source=source,
        cs_id=cs_id,
        per_page=per_page  # ===== 传递给模板 =====
    )


# ============================================================
# 导出 Excel
# ============================================================
@app.route("/cases/export")
def case_export():
    keyword = request.args.get("q", "", type=str).strip()
    source = request.args.get("source", "", type=str).strip()
    doc_name = request.args.get("doc_name", "", type=str).strip()
    doc_version = request.args.get("doc_version", "", type=str).strip()
    ids_str = request.args.get("ids", "", type=str).strip()

    ids = None
    if ids_str:
        ids = [int(x) for x in ids_str.split(",") if x.strip().isdigit()]
        if not ids:
            return "没有有效的选中 ID", 400

    try:
        buf, filename = export_cases_to_excel(
            keyword, source, ids, doc_name, doc_version
        )
    except Exception as e:
        import traceback
        print(f"[导出] 失败：{traceback.format_exc()}", flush=True)
        return f"导出失败：{e}", 500

    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ============================================================
# 推送生成的用例到 DevOps 平台
# ============================================================
@app.route("/cases/push-devops", methods=["POST"])
def case_push_devops():
    keyword = request.form.get("q", "").strip()
    source = request.form.get("source", "").strip()
    doc_name = request.form.get("doc_name", "").strip()
    doc_version = request.form.get("doc_version", "").strip()
    test_set_id = request.form.get("test_set_id", "").strip() or None
    test_set_path = request.form.get("test_set_path", "").strip() or None
    case_ids = request.form.getlist("case_ids")

    query = WebTestCase.query

    if case_ids:
        # 转成 int，避免类型不匹配
        try:
            id_list = [int(x) for x in case_ids if str(x).isdigit()]
        except Exception:
            id_list = []
        if not id_list:
            return jsonify({"ok": False, "msg": "传入的 case_ids 无效"})
        query = query.filter(WebTestCase.id.in_(id_list))
    else:
        # 兜底：按当前筛选条件
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

    cases = query.order_by(WebTestCase.id.asc()).all()

    if not cases:
        return jsonify({"ok": False, "msg": "没有符合条件的用例"})

    try:
        client = DevOpsClient()
        result = client.push_cases(cases, test_set_id=test_set_id, test_set_path=test_set_path)

        if result.get("code") == 0:
            ids = result.get("data", [])
            return jsonify({
                "ok": True,
                "msg": f"成功推送 {len(ids)} 条用例到 DevOps",
                "ids": ids,
            })
        else:
            return jsonify({
                "ok": False,
                "msg": f"推送失败：{result.get('msg') or '未知错误'}",
                "detail": result,
            })
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[DevOps 推送] 失败：{tb}", flush=True)
        return jsonify({
            "ok": False,
            "msg": f"请求异常：{e}",
            "detail": tb,
        })


# ============================================================
# 页面：新增用例
# ============================================================
@app.route("/cases/new", methods=["GET", "POST"])
def case_new():
    if request.method == "POST":
        tc = WebTestCase(
            title=request.form.get("title", "").strip(),
            priority=request.form.get("priority", "").strip(),
            owner=request.form.get("owner", "").strip(),
            tags=request.form.get("tags", "").strip(),
            project=request.form.get("project", "").strip(),
            case_set=request.form.get("case_set", "").strip(),
            case_type=request.form.get("case_type", "").strip(),
            precondition=request.form.get("precondition", ""),
            steps=request.form.get("steps", ""),
            expected=request.form.get("expected", ""),
            evidence_source=request.form.get("evidence_source", ""),
            evidence_level=request.form.get("evidence_level", ""),
            evi_block_ids=request.form.get("evi_block_ids", ""),
            doc_name=request.form.get("doc_name", ""),
            doc_version=request.form.get("doc_version", ""),
            source="manual",
        )
        db.session.add(tc)
        db.session.commit()
        flash("用例新增成功", "success")
        return redirect(url_for("case_list"))

    return render_template("cases/form.html", case=None)


# ============================================================
# 页面：编辑用例
# ============================================================
@app.route("/cases/<int:case_id>/edit", methods=["GET", "POST"])
def case_edit(case_id):
    tc = WebTestCase.query.get_or_404(case_id)

    if request.method == "POST":
        tc.title = request.form.get("title", "").strip()
        tc.priority = request.form.get("priority", "").strip()
        tc.owner = request.form.get("owner", "").strip()
        tc.tags = request.form.get("tags", "").strip()
        tc.project = request.form.get("project", "").strip()
        tc.case_set = request.form.get("case_set", "").strip()
        tc.case_type = request.form.get("case_type", "").strip()
        tc.precondition = request.form.get("precondition", "")
        tc.steps = request.form.get("steps", "")
        tc.expected = request.form.get("expected", "")
        tc.evidence_source = request.form.get("evidence_source", "")
        tc.evidence_level = request.form.get("evidence_level", "")
        tc.evi_block_ids = request.form.get("evi_block_ids", "")
        tc.doc_name = request.form.get("doc_name", "")
        tc.doc_version = request.form.get("doc_version", "")
        db.session.commit()
        flash("用例更新成功", "success")
        return redirect(url_for("case_list"))

    return render_template("cases/form.html", case=tc)

# 编辑用例里面的查看证据块详情
# @app.route("/api/source-block/<int:block_id>")
# def get_source_block(block_id):
#     """查询需求源块原文，用于前端弹窗展示"""
#     from services.preprocess import ConnectMysql
#
#
#     # 使用 config 里的数据库配置
#     db_config = {
#         "host": "127.0.0.1", "user": "root",
#         "password": "wlw123456", "port": 3306,
#         "database": "my_project",
#     }
#     try:
#         db = ConnectMysql(**db_config)
#         res = db.query_sql("SELECT id, content_text FROM source_block WHERE id=%s", args=(block_id,))
#         db.close()
#
#         if res:
#             return jsonify({"ok": True, "data": res[0]})
#         else:
#             return jsonify({"ok": False, "msg": "未找到该证据块，可能是废弃数据"})
#     except Exception as e:
#         return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/cases/<int:case_id>/evidences")
def get_case_evidences(case_id):
    """获取某条用例下挂载的所有证据实体"""
    from models import Evidence
    evi_list = Evidence.query.filter_by(test_case_id=case_id).all()
    return jsonify({"ok": True, "data": [e.to_dict() for e in evi_list]})

# ============================================================
# 动作：删除用例
# ============================================================
@app.route("/cases/<int:case_id>/delete", methods=["POST"])
def case_delete(case_id):
    tc = WebTestCase.query.get_or_404(case_id)
    db.session.delete(tc)
    db.session.commit()
    flash("用例已删除", "success")
    return redirect(url_for("case_list"))


# 批量删除
# @app.route("/cases/batch-delete", methods=["POST"])
# def case_batch_delete():
#     data = request.get_json(silent=True) or {}
#     ids = data.get("ids", [])
#     if not ids:
#         return jsonify({"ok": False, "msg": "没有选中任何用例"})
#     try:
#         count = WebTestCase.query.filter(WebTestCase.id.in_(ids)).delete(
#             synchronize_session=False
#         )
#         db.session.commit()
#         return jsonify({"ok": True, "msg": f"已删除 {count} 条", "count": count})
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({"ok": False, "msg": str(e)})
@app.route("/cases/batch-delete", methods=["POST"])
def case_batch_delete():
    from models import WebTestCase, Evidence, db
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])

    if not ids:
        return jsonify({"ok": False, "msg": "没有选中任何用例"})

    try:
        # 1. 先删除关联的 Evidence 实体数据，解除外键约束
        Evidence.query.filter(Evidence.test_case_id.in_(ids)).delete(synchronize_session=False)

        # 2. 再删除主表 web_test_case 的数据
        count = WebTestCase.query.filter(WebTestCase.id.in_(ids)).delete(
            synchronize_session=False
        )

        db.session.commit()
        return jsonify({"ok": True, "msg": f"已删除 {count} 条用例及其关联证据", "count": count})
    except Exception as e:
        db.session.rollback()
        import traceback
        print(f"[批量删除] 异常：{traceback.format_exc()}", flush=True)
        return jsonify({"ok": False, "msg": str(e)})


# ============================================================
# 页面：导入 md
# ============================================================
@app.route("/cases/import", methods=["GET", "POST"])
def case_import():
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("请选择 md 文件", "danger")
            return redirect(url_for("case_import"))

        filename = secure_filename(f.filename)
        if not filename.lower().endswith((".md", ".markdown")):
            flash("只支持 .md / .markdown 文件", "danger")
            return redirect(url_for("case_import"))

        save_path = Path(Config.UPLOAD_FOLDER) / f"{uuid.uuid4().hex}_{filename}"
        f.save(str(save_path))

        doc_name = request.form.get("doc_name", "").strip()
        doc_version = request.form.get("doc_version", "").strip()

        success, total = import_md_file(save_path, doc_name, doc_version)
        flash(f"导入完成：成功 {success} 条 / 共解析 {total} 条", "success")
        return redirect(url_for("case_list"))

    return render_template("cases/import.html")


# ============================================================
# 页面：AI 生成
# ============================================================
# @app.route("/cases/generate", methods=["GET", "POST"])
# def case_generate():
#     if request.method == "POST":
#         f = request.files.get("file")
#         if not f or not f.filename:
#             return jsonify({"ok": False, "msg": "请上传 docx 文件"})
#
#         filename = secure_filename(f.filename)
#         if not filename.lower().endswith(".docx"):
#             return jsonify({"ok": False, "msg": "只支持 .docx 文件"})
#
#         save_path = Path(Config.UPLOAD_FOLDER) / f"{uuid.uuid4().hex}_{filename}"
#         f.save(str(save_path))
#
#         doc_name = request.form.get("doc_name", "").strip() or filename
#         doc_version = request.form.get("doc_version", "").strip() or "V1.0.0"
#
#         # ===== 新增：自动创建需求文档存档 + 用例集 =====
#         from models import RequirementDoc, CaseSet
#
#         doc = RequirementDoc.query.filter_by(
#             doc_name=doc_name, doc_version=doc_version
#         ).first()
#         if not doc:
#             doc = RequirementDoc(
#                 doc_name=doc_name, doc_version=doc_version,
#                 file_path=str(save_path),
#             )
#             db.session.add(doc)
#
#         cs = CaseSet.query.filter_by(name=doc_name).first()
#         if not cs:
#             cs = CaseSet(name=doc_name)
#             db.session.add(cs)
#
#         db.session.commit()
#
#         task_id = start_generate_task(str(save_path), doc_name, doc_version, app)
#         return jsonify({"ok": True, "task_id": task_id})
#
#     return render_template("cases/generate.html")
@app.route("/cases/generate", methods=["GET", "POST"])
def case_generate():
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"ok": False, "msg": "请上传 docx 文件"})

        filename = secure_filename(f.filename)
        if not filename.lower().endswith(".docx"):
            return jsonify({"ok": False, "msg": "只支持 .docx 文件"})

        save_path = Path(Config.UPLOAD_FOLDER) / f"{uuid.uuid4().hex}_{filename}"
        f.save(str(save_path))

        doc_name = request.form.get("doc_name", "").strip() or filename
        doc_version = request.form.get("doc_version", "").strip() or "V1.0.0"

        # ===== 自动创建需求文档存档 + 用例集 =====
        from models import RequirementDoc, CaseSet
        doc = RequirementDoc.query.filter_by(doc_name=doc_name, doc_version=doc_version).first()
        if not doc:
            doc = RequirementDoc(doc_name=doc_name, doc_version=doc_version, file_path=str(save_path))
            db.session.add(doc)

        cs = CaseSet.query.filter_by(name=doc_name).first()
        if not cs:
            cs = CaseSet(name=doc_name)
            db.session.add(cs)
        db.session.commit()

        # ===== 1. 先执行切块（同步执行，很快） =====
        from services.preprocess import preprocess_docx
        db_config = {"host": "127.0.0.1", "user": "root", "password": "wlw123456", "port": 3306,
                     "database": "my_project"}
        try:
            preprocess_docx(str(save_path), doc_name, doc_version, Config.BLOCK_LIST_FILE, db_config)
        except Exception as e:
            return jsonify({"ok": False, "msg": f"解析需求文档失败: {e}"})

        # ===== 2. 触发【提取测试点】任务（而不是直接生成用例） =====
        from services.test_point_service import extract_points_task
        from services.trae_service import create_task
        import threading

        task_id = create_task()
        threading.Thread(
            target=extract_points_task,
            args=(task_id, str(save_path), doc_name, doc_version, app, push),
            daemon=True
        ).start()

        return jsonify({"ok": True, "task_id": task_id})

    return render_template("cases/generate.html")


# ============================================================
# SSE：实时推送生成进度
# ============================================================
@app.route("/cases/generate/stream/<task_id>")
def case_generate_stream(task_id):
    with TASKS_LOCK:
        q = TASKS.get(task_id)
    if not q:
        return jsonify({"ok": False, "msg": "任务不存在"}), 404

    def event_stream():
        import json as _json
        while True:
            try:
                item = q.get(timeout=60)
            except Exception:
                yield "data: {\"kind\":\"ping\"}\n\n"
                continue

            payload = dict(item)
            payload.pop("ts", None)
            yield f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"

            if item.get("kind") == "end":
                break

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/cases/generate/followup", methods=["POST"])
def case_generate_followup():
    """追问：复用同一个 task 的会话"""
    data = request.get_json(silent=True) or {}
    task_id = (data.get("task_id") or "").strip()
    question = (data.get("question") or "").strip()

    if not task_id or not question:
        return jsonify({"ok": False, "msg": "参数不完整"})

    with TASKS_LOCK:
        if task_id not in TASKS:
            return jsonify({"ok": False, "msg": "任务不存在或已过期"})

    followup_task(task_id, question, app)
    return jsonify({"ok": True, "task_id": task_id})


@app.route("/cases/generate/confirm", methods=["POST"])
def case_generate_confirm():
    """用户确认入库"""
    data = request.get_json(silent=True) or {}
    task_id = (data.get("task_id") or "").strip()
    if not task_id:
        return jsonify({"ok": False, "msg": "缺少 task_id"})
    with TASKS_LOCK:
        if task_id not in TASKS:
            return jsonify({"ok": False, "msg": "任务不存在"})
    confirm_import_task(task_id, app)
    return jsonify({"ok": True})


@app.route("/cases/generate/discard", methods=["POST"])
def case_generate_discard():
    """用户放弃，不入库"""
    data = request.get_json(silent=True) or {}
    task_id = (data.get("task_id") or "").strip()
    print(f"[TASK {task_id}] [用户放弃] 不入库", flush=True)
    return jsonify({"ok": True})


# ==========================================
# 专家团队管理
# ==========================================
@app.route("/experts")
def expert_list():
    from models import Expert
    experts = Expert.query.order_by(Expert.id.asc()).all()
    return render_template("experts/list.html", experts=experts)


@app.route("/experts/new", methods=["GET", "POST"])
def expert_new():
    from models import Expert, db
    if request.method == "POST":
        expert = Expert(
            name=request.form.get("name"),
            description=request.form.get("description"),
            model_name=request.form.get("model_name"),
            soul_md=request.form.get("soul_md"),
            avatar=request.form.get("avatar", "🤖"),
            language=request.form.get("language", "中文")
        )
        db.session.add(expert)
        db.session.commit()
        flash("专家创建成功", "success")
        return redirect(url_for("expert_list"))

    models = get_trae_models()
    return render_template("experts/form.html", expert=None, models=models)


@app.route("/experts/<int:expert_id>/edit", methods=["GET", "POST"])
def expert_edit(expert_id):
    from models import Expert, db
    expert = Expert.query.get_or_404(expert_id)
    if request.method == "POST":
        expert.name = request.form.get("name")
        expert.description = request.form.get("description")
        expert.model_name = request.form.get("model_name")
        expert.soul_md = request.form.get("soul_md")
        expert.avatar = request.form.get("avatar", expert.avatar)
        expert.language = request.form.get("language", expert.language)
        db.session.commit()
        flash("专家更新成功", "success")
        return redirect(url_for("expert_list"))

    models = get_trae_models()
    return render_template("experts/form.html", expert=expert, models=models)


@app.route("/experts/<int:expert_id>/delete", methods=["POST"])
def expert_delete(expert_id):
    from models import Expert, db
    expert = Expert.query.get_or_404(expert_id)
    db.session.delete(expert)
    db.session.commit()
    return redirect(url_for("expert_list"))


@app.errorhandler(Exception)
def handle_exception(e):
    """所有未捕获异常都返回 JSON，方便前端看到真正错误"""
    import traceback
    tb = traceback.format_exc()
    print(f"[未捕获异常] {tb}", flush=True)
    return jsonify({
        "ok": False,
        "msg": f"服务端异常：{type(e).__name__}: {e}",
        "detail": tb,
    }), 500


# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    try:
        from services.devops_auth import get_token
        get_token()
        print("[启动] DevOps token 已就绪")
    except Exception as e:
        print(f"[启动] DevOps 预登录失败（不影响主服务）：{e}")

    # app.run(host="127.0.0.1", port=5000, debug=True, threaded=True, use_reloader=False) #只允许同一台电脑内部自己访问，不允许局域网、cpolar 隧道、其他机器访问
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True, use_reloader=False) #0.0.0.0.0表示监听这台机器上所有可用网卡，不管请求来自本机回环、局域网还是 cpolar 隧道转发，都接收。