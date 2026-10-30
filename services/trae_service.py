"""AI 生成服务：生成 → 审计 → 自动修复 → 等用户确认 → 入库"""
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

from config import Config
from models import db, WebTestCase, Evidence
from services.importer import parse_md_table
from services.preprocess import preprocess_docx
from services.auditor import audit_md_file
from services.cross_validator import cross_validate, format_cross_report

MAX_FIX_ROUNDS = 1           # 自动修复最多几轮
EXCLUDE_BLOCK_IDS = {32, 33, 45}   # 不需要用例覆盖的块（概述/元数据）


TASKS = {}
TASKS_LOCK = threading.Lock()

TASK_SESSIONS = {}
TASK_SESSIONS_LOCK = threading.Lock()

# 每个任务的上下文（md 路径、doc_name、block 清单等）
TASK_CONTEXT = {}
TASK_CONTEXT_LOCK = threading.Lock()


def create_task() -> str:
    import uuid
    task_id = uuid.uuid4().hex[:12]
    with TASKS_LOCK:
        TASKS[task_id] = queue.Queue()
    return task_id


def register_session(task_id: str, session_id: str):
    with TASK_SESSIONS_LOCK:
        TASK_SESSIONS[task_id] = session_id


def get_session(task_id: str):
    with TASK_SESSIONS_LOCK:
        return TASK_SESSIONS.get(task_id)


def set_context(task_id: str, **kwargs):
    with TASK_CONTEXT_LOCK:
        TASK_CONTEXT.setdefault(task_id, {}).update(kwargs)


def get_context(task_id: str):
    with TASK_CONTEXT_LOCK:
        return TASK_CONTEXT.get(task_id, {})


def push(task_id: str, msg: str, kind: str = "log"):
    with TASKS_LOCK:
        q = TASKS.get(task_id)
    if q:
        q.put({"kind": kind, "msg": msg, "ts": time.time()})
    print(f"[TASK {task_id}] {msg}", flush=True)


def push_stage(task_id: str, stage: str):
    """推送阶段变化，前端根据 stage 显示不同 UI"""
    with TASKS_LOCK:
        q = TASKS.get(task_id)
    if q:
        q.put({"kind": "stage", "stage": stage, "ts": time.time()})
    print(f"[TASK {task_id}] [STAGE] {stage}", flush=True)


def end_stream(task_id: str):
    """当前 SSE 流结束（不代表任务结束，可能还在等用户输入）"""
    with TASKS_LOCK:
        q = TASKS.get(task_id)
    if q:
        q.put({"kind": "end", "ts": time.time()})


def _is_binary_like(s: str) -> bool:
    if not s:
        return False
    if "\ufffd" in s or "\\ufffd" in s:
        return True
    bad = sum(1 for ch in s if ord(ch) < 32 and ch not in "\n\r\t")
    return bad > 5 or bad / max(len(s), 1) > 0.01


def _call_cli_streaming(task_id, prompt, timeout,
                        session_id=None, resume_session_id=None,model_name=None):
    # Python 脚本 -> 唤起本地的 traecli.exe -> traecli 用本地的秘钥去向云端发请求 -> 返回结果给 Python。
    cmd = [
        Config.CLI_BIN,
        "--print",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--permission-mode", "bypass_permissions",
    ]
    if model_name:
        cmd.extend(["-c", f"model.name={model_name}"])  # 新增：支持指定模型
    if resume_session_id:
        cmd.append(f"--resume={resume_session_id}")
    elif session_id:
        cmd.append(f"--session-id={session_id}")
    cmd.append(prompt)

    proc = subprocess.Popen(
        cmd,
        cwd=Config.TRAE_WORKSPACE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    final_text_parts = []
    final_result = ""
    in_thinking = False
    in_content = False

    def read_stdout():
        nonlocal in_thinking, in_content, final_result
        try:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.rstrip("\n")
                if not line or _is_binary_like(line):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")
                if etype == "stream_event":
                    delta = event.get("delta", {}) or {}
                    think = delta.get("reasoning_content", "")
                    if think and not _is_binary_like(think):
                        if not in_thinking:
                            push(task_id, "\n[思考] ", kind="delta")
                            in_thinking = True
                            in_content = False
                        push(task_id, think, kind="delta")
                    text = delta.get("content", "")
                    if text and not _is_binary_like(text):
                        if not in_content:
                            push(task_id, "\n\n[正文] ", kind="delta")
                            in_content = True
                            in_thinking = False
                        push(task_id, text, kind="delta")
                        final_text_parts.append(text)
                elif etype == "tool_use":
                    push(task_id, f"\n\n[工具] {event.get('name','?')}", kind="log")
                elif etype == "result":
                    raw = event.get("result", "") or ""
                    if not _is_binary_like(raw):
                        final_result = raw
                    push(task_id, f"\n[完成] 耗时 {event.get('duration_ms',0)}ms", kind="log")
        except Exception as e:
            push(task_id, f"\n[stdout异常] {e}", kind="log")

    def read_stderr():
        try:
            for line in iter(proc.stderr.readline, ""):
                if not line.strip() or "[stdout-guard]" in line:
                    continue
                if not _is_binary_like(line):
                    push(task_id, f"[stderr] {line.rstrip()}", kind="log")
        except Exception:
            pass

    t_out = threading.Thread(target=read_stdout, daemon=True)
    t_err = threading.Thread(target=read_stderr, daemon=True)
    t_out.start()
    t_err.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        push(task_id, f"\n[CLI] 超时（{timeout}s）", kind="log")
        return 1, ""

    t_out.join(timeout=5)
    t_err.join(timeout=5)

    # 在 return 前，如果是非 0 退出，把错误打出来
    if proc.returncode != 0:
        push(task_id, f"[CLI错误] 模型调用失败，请检查模型名是否正确。", kind="log")

    return proc.returncode, final_result or "".join(final_text_parts)


# ============================================================
# 核心：生成 + 审计 + 自动修复（不入库）
# ============================================================
# def _do_generate_and_audit(task_id, docx_path, doc_name, doc_version, db_config):
#     """执行生成 + 循环审计自动修复，返回 (success, md_output, last_result)"""
#     workspace = Path(Config.TRAE_WORKSPACE)
#     md_output = workspace / f"测试用例_{doc_name.replace('.docx', '')}.md"
#     if md_output.exists():
#         md_output.unlink()
#
#     block_list_content = ""
#     bl_path = Path(Config.BLOCK_LIST_FILE)
#     if bl_path.exists():
#         block_list_content = bl_path.read_text(encoding="utf-8")
#
#     session_id = get_session(task_id)
#
#     last_result = None
#
#     for attempt in range(MAX_FIX_ROUNDS + 1):
#         round_tag = f"第 {attempt + 1} 轮" if attempt > 0 else "首轮"
#
#         # --- CLI 生成 / 修复 ---
#         push_stage(task_id, "GENERATING")
#         push(task_id, f"\n[CLI] {round_tag}：正在调用 TraeCode CLI...", kind="log")
#
#         if attempt == 0:
#             prompt = f"""请使用项目技能 testcase，严格按以下要求生成测试用例：
#
# 1. 需求文档路径：{docx_path}
# 2. **不要用 Bash 工具（cat/ls/grep）读取文件，直接用 Python + python-docx 或 Read 工具读取。**
# 3. block_id 清单已附在下方，生成用例时【证据块ID】列只能使用清单中真实存在的 block_id，禁止编造。
# 4. 按照 testcase 技能的规范，先输出"待确认问题清单"，再输出测试用例表格。
# 5. 把生成的完整 markdown 内容写入：{md_output}
#
# ======== block_id 清单 ========
# {block_list_content}
# ======== 清单结束 ========
# """
#             rc, _ = _call_cli_streaming(task_id, prompt, Config.CLI_TIMEOUT, session_id=session_id)
#         else:
#             leak_desc = "\n".join(
#                 f"- block_id:{b['id']}：{b['content_text'][:120]}"
#                 for b in last_result["leak_blocks"]
#             )
#             prompt = f"""上一版测试用例存在反向审计漏抽，以下 {len(last_result['leak_blocks'])} 个需求块没有被任何用例引用：
#
# {leak_desc}
#
# 请**重新生成完整的测试用例文件**（覆盖原文件，不要追加），要求：
# 1. 保留上一版已有的、有效的用例。
# 2. 为上面每一个漏抽的 block_id 至少补充 1 条测试用例，并在【证据块ID】列引用。
# 3. 表头、格式、规范同前。
# 4. 写入同一路径：{md_output}
# """
#             rc, _ = _call_cli_streaming(task_id, prompt, Config.CLI_TIMEOUT, resume_session_id=session_id)
#
#         if rc != 0 or not md_output.exists():
#             push(task_id, f"[错误] CLI 失败（rc={rc}）", kind="log")
#             return False, md_output, None
#
#         # --- 审计 ---
#         push_stage(task_id, "AUDITING")
#         push(task_id, f"\n[AUDIT] {round_tag}：执行双向审计...", kind="log")
#         report_text, result = audit_md_file(
#             md_file_path=str(md_output),
#             doc_name=doc_name, doc_version=doc_version,
#             db_config=db_config, exclude_ids=EXCLUDE_BLOCK_IDS,
#         )
#         last_result = result
#
#         push(task_id, "\n========== 审计报告 ==========\n", kind="log")
#         for line in report_text.splitlines():
#             push(task_id, line + "\n", kind="log")
#
#         if not result["has_leak"]:
#             push(task_id, f"\n[AUDIT] {round_tag}：无漏抽，审计通过", kind="log")
#             return True, md_output, result
#         elif attempt < MAX_FIX_ROUNDS:
#             push(task_id, f"\n[AUDIT] {round_tag}：{len(result['leak_blocks'])} 个漏抽，"
#                           f"进入第 {attempt + 2} 轮修复...", kind="log")
#         else:
#             push(task_id, f"\n[AUDIT] 已达最大轮次（{MAX_FIX_ROUNDS}），仍有 "
#                           f"{len(result['leak_blocks'])} 个漏抽，请用户决策", kind="log")
#
#     return True, md_output, last_result

def _do_generate_and_audit(task_id, docx_path, doc_name, doc_version, db_config):
    """执行生成 + 循环审计自动修复，返回 (success, md_output, last_result)"""
    workspace = Path(Config.TRAE_WORKSPACE)
    md_output = workspace / f"测试用例_{doc_name.replace('.docx', '')}.md"
    if md_output.exists():
        md_output.unlink()

    block_list_content = ""
    bl_path = Path(Config.BLOCK_LIST_FILE)
    if bl_path.exists():
        block_list_content = bl_path.read_text(encoding="utf-8")

    session_id = get_session(task_id)

    last_result = None

    # MAX_FIX_ROUNDS 已经在文件顶部定义为 1，所以这里是 0, 1 两次循环
    for attempt in range(MAX_FIX_ROUNDS + 1):
        round_tag = f"第 {attempt + 1} 轮" if attempt > 0 else "首轮"

        # --- CLI 生成 / 修复 ---
        push_stage(task_id, "GENERATING")
        push(task_id, f"\n[CLI] {round_tag}：正在调用 TraeCode CLI...", kind="log")

        if attempt == 0:
            # 首轮：绝对禁止读文件，只认 block 文本
            prompt = f"""请使用项目技能 testcase，严格按以下要求生成测试用例：

**【绝对禁令】**
1. **严禁去读取原始 docx 文件！严禁使用 Bash 或 Python 写任何临时脚本！**
2. 本次任务的所有需求上下文已附在下方，你只需要基于下方文本进行推导。
3. 如果你缺少基线信息，可以直接提问，但绝对不要去摸原文件。

**【生成要求】**
1. 基于下方【需求源块清单】，先输出"待确认问题清单"，再输出测试用例表格。
2. 用例的【证据块ID】列只能使用清单中真实存在的 block_id，禁止编造。
3. 把生成的完整 markdown 内容写入：{md_output}

======== 需求源块清单 ========
{block_list_content}
======== 清单结束 ========
"""
            rc, _ = _call_cli_streaming(task_id, prompt, Config.CLI_TIMEOUT, session_id=session_id)
        else:
            # 修复轮：给出漏抽的块，要求精准补充
            leak_desc = "\n".join(
                f"- block_id:{b['id']}：{b['content_text'][:150]}"
                for b in last_result["leak_blocks"]
            )
            prompt = f"""上一版测试用例存在反向审计漏抽，以下 {len(last_result['leak_blocks'])} 个需求块没有被任何用例引用：

{leak_desc}

请**重新生成完整的测试用例文件**（覆盖原文件，不要追加），要求：
1. 保留上一版已有的、有效的用例。
2. 为上面每一个漏抽的 block_id 至少补充 1 条测试用例，并在【证据块ID】列引用。
3. 表头、格式、规范同前。
4. **依然严禁去读取原始 docx 文件，直接基于上述漏抽文本补充即可。**
5. 写入同一路径：{md_output}
"""
            rc, _ = _call_cli_streaming(task_id, prompt, Config.CLI_TIMEOUT, resume_session_id=session_id)

        if rc != 0 or not md_output.exists():
            push(task_id, f"[错误] CLI 失败（rc={rc}）", kind="log")
            return False, md_output, None

        # --- 审计 ---
        push_stage(task_id, "AUDITING")
        push(task_id, f"\n[AUDIT] {round_tag}：执行双向审计...", kind="log")
        report_text, result = audit_md_file(
            md_file_path=str(md_output),
            doc_name=doc_name, doc_version=doc_version,
            db_config=db_config, exclude_ids=EXCLUDE_BLOCK_IDS,
        )
        last_result = result

        push(task_id, "\n========== 审计报告 ==========\n", kind="log")
        for line in report_text.splitlines():
            push(task_id, line + "\n", kind="log")

        if not result["has_leak"]:
            push(task_id, f"\n[AUDIT] {round_tag}：无漏抽，审计通过", kind="log")
            return True, md_output, result
        elif attempt < MAX_FIX_ROUNDS:
            push(task_id, f"\n[AUDIT] {round_tag}：{len(result['leak_blocks'])} 个漏抽，"
                          f"进入第 {attempt + 2} 轮修复...", kind="log")
        else:
            # 如果是最后一轮还有漏抽，不再强行让 AI 重写，直接交给用户
            push(task_id, f"\n[AUDIT] 已达最大轮次（{MAX_FIX_ROUNDS}），仍有 "
                          f"{len(result['leak_blocks'])} 个漏抽。请人工决定是否继续通过对话补充。", kind="log")

    return True, md_output, last_result

# ============================================================
# 后台线程入口
# ============================================================
def _run_generate(task_id, docx_path, doc_name, doc_version, app):
    with app.app_context():
        try:
            push(task_id, f"[开始] 文档：{doc_name} / {doc_version}", kind="log")

            db_config = {
                "host": "127.0.0.1", "user": "root",
                "password": "wlw123456", "port": 3306,
                "database": "my_project",
            }
            set_context(
                task_id,
                docx_path=docx_path, doc_name=doc_name,
                doc_version=doc_version, db_config=db_config,
            )

            # --- 步骤 1：preprocess ---
            push_stage(task_id, "PREPROCESSING")
            push(task_id, "[1/4] 正在解析 docx 并写入 source_block...", kind="log")
            try:
                block_list = preprocess_docx(
                    docx_path=docx_path, doc_name=doc_name,
                    doc_version=doc_version,
                    block_list_file=Config.BLOCK_LIST_FILE,
                    db_config=db_config,
                )
                push(task_id, f"[1/4] 完成，共入库 {len(block_list)} 个 source_block", kind="log")
            except Exception as e:
                import traceback
                push(task_id, f"[1/4] 失败：{e}\n{traceback.format_exc()}", kind="log")
                push_stage(task_id, "ERROR")
                return

            # --- 步骤 2~3：生成 + 审计（自动修复） ---
            session_id = f"web-{task_id}"
            register_session(task_id, session_id)
            push(task_id, "[2/4] 生成用例 + 双向审计...", kind="log")

            success, md_output, result = _do_generate_and_audit(
                task_id, docx_path, doc_name, doc_version, db_config
            )
            if not success or not md_output.exists():
                push_stage(task_id, "ERROR")
                return

            # set_context(task_id, md_output=str(md_output), last_result=result)
            import os
            file_stat = {}
            if md_output.exists():
                st = os.stat(md_output)
                file_stat = {"mtime": st.st_mtime, "size": st.st_size}

            set_context(
                task_id,
                md_output=str(md_output),
                last_result=result,
                file_stat=file_stat,  # ← 关键：初始化文件状态
            )
            # --- 步骤 4：异构交叉验证（可选） ---
            if Config.ENABLE_CROSS_VALIDATION:
                push_stage(task_id, "CROSS_VALIDATING")
                push(task_id, "[4/5] 启动异构交叉验证...", kind="log")

                cross_result = cross_validate(
                    task_id=task_id,
                    md_path=str(md_output),
                    docx_path=docx_path,
                    push_fn=push,
                )

                cross_report_text = format_cross_report(cross_result)
                for line in cross_report_text.splitlines():
                    push(task_id, line + "\n", kind="log")

                cross_report_path = Path(Config.TRAE_WORKSPACE) / "cross_validation_report.md"
                cross_report_path.write_text(cross_report_text, encoding="utf-8")

                set_context(task_id, cross_result=cross_result)

                if not cross_result["passed"]:
                    push(task_id, "\n异构验证未全部通过，建议根据上方报告继续调整。", kind="log")
                else:
                    push(task_id, "\n异构验证全部通过。", kind="log")

            # --- 步骤 5：等待用户确认 ---
            push(task_id, "\n[5/5] 请确认是否入库，或输入修改意见继续调整。", kind="log")
            push_stage(task_id, "WAITING_CONFIRM")

        except Exception as e:
            import traceback
            print(f"[TASK {task_id}] [异常]\n{traceback.format_exc()}", flush=True)
            push(task_id, f"[异常] {e}", kind="log")
            push_stage(task_id, "ERROR")
        finally:
            # 注意：这里只结束 SSE 流，不销毁任务
            end_stream(task_id)


# ============================================================
# 追问：用户输入意见 → CLI 修改 → 再审 → 再等
# ============================================================
def followup_task(task_id: str, question: str, app):
    def _run():
        with app.app_context():
            try:
                ctx = get_context(task_id)
                session_id = get_session(task_id)
                if not session_id or not ctx:
                    push(task_id, "[错误] 会话不存在或已过期，请重新生成", kind="log")
                    return

                md_output = ctx.get("md_output")
                doc_name = ctx.get("doc_name")
                doc_version = ctx.get("doc_version")
                db_config = ctx.get("db_config")

                push(task_id, f"\n[用户意见] {question}\n", kind="log")
                push_stage(task_id, "REVISING")

                prompt = f"""用户发来以下内容：

                {question}

                请你先判断用户意图：

                A. 如果用户只是**提问/询问**（例如"有什么要确认的"、"这个用例对吗"）：
                   → 你只需要在对话里**直接回答**，不要修改、不要重写 md 文件。

                B. 如果用户明确给了**修改意见**（例如"1=名单制，2=50000"、"把 xxx 改成 yyy"）：
                   → 你按意见修改测试用例，**输出完整版本覆盖原文件**（不要追加），路径：{md_output}。
                   → 保持表头、格式、规范一致。

                **重要**：判断为 A 时，禁止调用任何文件写入工具；判断为 B 时才写文件。
                """

                rc, _ = _call_cli_streaming(task_id, prompt, Config.CLI_TIMEOUT, resume_session_id=session_id)
                if rc != 0 or not md_output or not Path(md_output).exists():
                    push(task_id, f"[错误] CLI 修改失败（rc={rc}）", kind="log")
                    push_stage(task_id, "WAITING_CONFIRM")
                    return

                # 修改后重新审计
                # push_stage(task_id, "AUDITING")
                # push(task_id, "\n[AUDIT] 修改后重新审计...", kind="log")
                # 判断文件是否被修改过（用 mtime + 大小 粗略判断）
                import os
                file_changed = False
                if md_output and Path(md_output).exists():
                    stat = os.stat(md_output)
                    prev = ctx.get("file_stat", {})
                    if prev.get("mtime") != stat.st_mtime or prev.get("size") != stat.st_size:
                        file_changed = True
                    # 更新
                    set_context(task_id, file_stat={"mtime": stat.st_mtime, "size": stat.st_size})

                if not file_changed:
                    push(task_id, "\n[AUDIT] 文件未变化（用户只是提问），跳过审计", kind="log")
                    push(task_id, "\n继续等待你确认或输入修改意见。", kind="log")
                    push_stage(task_id, "WAITING_CONFIRM")
                    return

                # 修改后重新审计
                push_stage(task_id, "AUDITING")
                push(task_id, "\n[AUDIT] 文件已修改，重新审计...", kind="log")
                report_text, result = audit_md_file(
                    md_file_path=md_output,
                    doc_name=doc_name, doc_version=doc_version,
                    db_config=db_config, exclude_ids=EXCLUDE_BLOCK_IDS,
                )
                push(task_id, "\n========== 审计报告 ==========\n", kind="log")
                for line in report_text.splitlines():
                    push(task_id, line + "\n", kind="log")

                set_context(task_id, last_result=result)

                if result["has_leak"]:
                    push(task_id, f"\n仍有 {len(result['leak_blocks'])} 个漏抽，"
                                  f"可继续输入意见或直接确认入库。", kind="log")
                else:
                    push(task_id, "\n规则审计通过。", kind="log")

                # --- 异构交叉验证 ---
                if Config.ENABLE_CROSS_VALIDATION:
                    push_stage(task_id, "CROSS_VALIDATING")
                    cross_result = cross_validate(
                        task_id=task_id,
                        md_path=md_output,
                        docx_path=ctx.get("docx_path", ""),
                        push_fn=push,
                    )
                    cross_report_text = format_cross_report(cross_result)
                    for line in cross_report_text.splitlines():
                        push(task_id, line + "\n", kind="log")

                    cross_report_path = Path(Config.TRAE_WORKSPACE) / "cross_validation_report.md"
                    cross_report_path.write_text(cross_report_text, encoding="utf-8")

                    set_context(task_id, cross_result=cross_result)

                    if not cross_result["passed"]:
                        push(task_id, "\n 异构验证未全部通过，建议继续调整。", kind="log")
                    else:
                        push(task_id, "\n✅ 异构验证全部通过。请确认是否入库，或继续调整。", kind="log")
                else:
                    push(task_id, "\n请确认是否入库，或继续调整。", kind="log")

                push_stage(task_id, "WAITING_CONFIRM")

            except Exception as e:
                import traceback
                push(task_id, f"[异常] {e}\n{traceback.format_exc()}", kind="log")
                push_stage(task_id, "WAITING_CONFIRM")
            finally:
                end_stream(task_id)

    threading.Thread(target=_run, daemon=True).start()

def _get_valid_block_ids(doc_name, doc_version, db_config):
    """查询某个文档版本下所有合法的 source_block.id 集合"""
    import pymysql
    conn = pymysql.connect(
        host=db_config["host"], user=db_config["user"],
        password=db_config["password"], port=db_config["port"],
        database=db_config["database"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor, autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM source_block WHERE doc_name=%s AND doc_version=%s",
                (doc_name, doc_version)
            )
            return {row["id"] for row in cur.fetchall()}
    finally:
        conn.close()


# ============================================================
# 确认入库
# ============================================================
def confirm_import_task(task_id: str, app):
    def _run():
        with app.app_context():
            try:
                ctx = get_context(task_id)
                if not ctx:
                    push(task_id, "[错误] 上下文不存在", kind="log")
                    return

                md_output = ctx.get("md_output")
                doc_name = ctx.get("doc_name")
                doc_version = ctx.get("doc_version")
                db_config = ctx.get("db_config")

                if not md_output or not Path(md_output).exists():
                    push(task_id, "[错误] md 文件不存在", kind="log")
                    return
                if not db_config:
                    push(task_id, "[错误] 缺少数据库配置", kind="log")
                    return

                push_stage(task_id, "IMPORTING")
                push(task_id, "\n[入库] 正在解析 md 并写入 web_test_case...", kind="log")

                content = Path(md_output).read_text(encoding="utf-8")
                rows = parse_md_table(content)

                # ---------- P0-2：Schema 校验前置，拿合法 block_id 集合 ----------
                valid_ids = _get_valid_block_ids(doc_name, doc_version, db_config)
                push(task_id, f"[入库] 该文档版本合法 block_id 共 {len(valid_ids)} 个：{sorted(valid_ids)}", kind="log")

                total = 0
                skipped_e4e5 = []
                skipped_hallucination = []
                to_insert = []

                for row in rows:
                    if not row.get("title"):
                        continue
                    total += 1

                    title_short = row["title"][:50]

                    # ---------- P0-1：E4/E5 拦截 ----------
                    level = (row.get("evidence_level") or "").strip().upper()
                    if level in ("E4", "E5"):
                        skipped_e4e5.append(f"[{level}] {title_short}")
                        continue

                    # ---------- P0-2：Schema 校验（幻觉 block_id 拦截） ----------
                    ids_str = (row.get("evi_block_ids") or "").strip()
                    parsed_ids = []
                    if ids_str:
                        for x in ids_str.split(";"):
                            x = x.strip()
                            if x.isdigit():
                                parsed_ids.append(int(x))

                    invalid_ids = [i for i in parsed_ids if i not in valid_ids]
                    if invalid_ids:
                        skipped_hallucination.append(
                            f"幻觉ID {invalid_ids} - {title_short}"
                        )
                        continue

                    to_insert.append(row)

                # ---------- 拦截详情 ----------
                if skipped_e4e5:
                    push(task_id, f"\n[入库]  拦截 {len(skipped_e4e5)} 条 E4/E5 推测类用例：", kind="log")
                    for item in skipped_e4e5:
                        push(task_id, f"  - {item}", kind="log")

                if skipped_hallucination:
                    push(task_id, f"\n[入库]  拦截 {len(skipped_hallucination)} 条含幻觉 block_id 的用例：", kind="log")
                    for item in skipped_hallucination:
                        push(task_id, f"  - {item}", kind="log")

                # ---------- 清旧 + 入库 ----------
                deleted = WebTestCase.query.filter_by(
                    doc_name=doc_name, doc_version=doc_version, source="ai"
                ).delete(synchronize_session=False)
                db.session.commit()
                if deleted:
                    push(task_id, f"[入库] 已清理旧记录 {deleted} 条", kind="log")

                # ========== 新增：查询本次入库要关联的 需求文档 + 用例集 ==========
                from models import RequirementDoc, CaseSet

                doc = RequirementDoc.query.filter_by(
                    doc_name=doc_name, doc_version=doc_version
                ).first()
                if not doc:
                    # 兜底：如果 AI 生成时没建，这里补建
                    doc = RequirementDoc(doc_name=doc_name, doc_version=doc_version or "")
                    db.session.add(doc)
                    db.session.flush()
                    push(task_id, f"[入库] 补建需求文档存档 id={doc.id}", kind="log")

                cs = CaseSet.query.filter_by(name=doc_name).first()
                if not cs:
                    cs = CaseSet(name=doc_name)
                    db.session.add(cs)
                    db.session.flush()
                    push(task_id, f"[入库] 补建用例集 id={cs.id}", kind="log")

                push(task_id, f"[入库] 关联需求文档 id={doc.id}，用例集 id={cs.id}", kind="log")
                # ================================================================

                # count = 0
                # for row in to_insert:
                #     tc = WebTestCase(
                #         title=row.get("title", ""),
                #         priority=row.get("priority", ""),
                #         owner=row.get("owner", ""),
                #         tags=row.get("tags", ""),
                #         project=row.get("project", ""),
                #         case_set=row.get("case_set", ""),
                #         case_type=row.get("case_type", ""),
                #         precondition=row.get("precondition", ""),
                #         steps=row.get("steps", ""),
                #         expected=row.get("expected", ""),
                #         evidence_source=row.get("evidence_source", ""),
                #         evidence_level=row.get("evidence_level", ""),
                #         evi_block_ids=row.get("evi_block_ids", ""),
                #         doc_name=doc_name, doc_version=doc_version, source="ai",
                #         requirement_doc_id=doc.id,      # ← 新增
                #         case_set_id=cs.id,               # ← 新增
                #     )
                #     db.session.add(tc)
                #     count += 1
                # db.session.commit()

                count = 0
                for row in to_insert:
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
                        doc_name=doc_name, doc_version=doc_version, source="ai",
                        requirement_doc_id=doc.id,
                        case_set_id=cs.id,
                    )
                    db.session.add(tc)
                    db.session.flush()  # 必须先 flush 拿到 tc.id，才能关联 Evidence

                    # ========== 新增：将字符串转化为 Evidence 实体 ==========
                    ids_str = (row.get("evi_block_ids") or "").strip()
                    if ids_str:
                        for bid in ids_str.split(";"):
                            bid = bid.strip()
                            if bid.isdigit():
                                # 从 source_block 查出原文和 hash 锚定
                                import pymysql
                                conn = pymysql.connect(
                                    host=db_config["host"], user=db_config["user"],
                                    password=db_config["password"], port=db_config["port"],
                                    database=db_config["database"], charset="utf8mb4",
                                    cursorclass=pymysql.cursors.DictCursor, autocommit=True,
                                )
                                try:
                                    with conn.cursor() as cur:
                                        cur.execute("SELECT content_text, content_hash FROM source_block WHERE id=%s", (int(bid),))
                                        sb = cur.fetchone()
                                        if sb:
                                            evi = Evidence(
                                                test_case_id=tc.id,
                                                source_block_id=int(bid),
                                                quote=sb["content_text"],  # 真·事实实体：存原文快照
                                                content_hash=sb["content_hash"],
                                                evidence_level=row.get("evidence_level", "")
                                            )
                                            db.session.add(evi)
                                finally:
                                    conn.close()
                    # ========================================================

                    count += 1
                db.session.commit()

                # ---------- 汇总 ----------
                push(task_id, "\n[入库] ══════ 汇总 ══════", kind="log")
                push(task_id, f"[入库] 解析总数：{total} 条", kind="log")
                push(task_id, f"[入库] 成功入库：{count} 条", kind="log")
                push(task_id, f"[入库] 拦截 E4/E5：{len(skipped_e4e5)} 条", kind="log")
                push(task_id, f"[入库] 拦截幻觉 ID：{len(skipped_hallucination)} 条", kind="log")
                push_stage(task_id, "DONE")

            except Exception as e:
                import traceback
                push(task_id, f"[异常] {e}\n{traceback.format_exc()}", kind="log")
            finally:
                end_stream(task_id)

    threading.Thread(target=_run, daemon=True).start()

# def confirm_import_task(task_id: str, app):
#     def _run():
#         with app.app_context():
#             try:
#                 ctx = get_context(task_id)
#                 if not ctx:
#                     push(task_id, "[错误] 上下文不存在", kind="log")
#                     return
#
#                 md_output = ctx.get("md_output")
#                 doc_name = ctx.get("doc_name")
#                 doc_version = ctx.get("doc_version")
#
#                 if not md_output or not Path(md_output).exists():
#                     push(task_id, "[错误] md 文件不存在", kind="log")
#                     return
#
#                 push_stage(task_id, "IMPORTING")
#                 push(task_id, "\n[入库] 正在解析 md 并写入 web_test_case...", kind="log")
#
#                 content = Path(md_output).read_text(encoding="utf-8")
#                 rows = parse_md_table(content)
#
#                 # 先清旧
#                 deleted = WebTestCase.query.filter_by(
#                     doc_name=doc_name, doc_version=doc_version, source="ai"
#                 ).delete(synchronize_session=False)
#                 db.session.commit()
#                 if deleted:
#                     push(task_id, f"[入库] 已清理旧记录 {deleted} 条", kind="log")
#
#                 count = 0
#                 for row in rows:
#                     if not row.get("title"):
#                         continue
#                     tc = WebTestCase(
#                         title=row.get("title", ""),
#                         priority=row.get("priority", ""),
#                         owner=row.get("owner", ""),
#                         tags=row.get("tags", ""),
#                         project=row.get("project", ""),
#                         case_set=row.get("case_set", ""),
#                         case_type=row.get("case_type", ""),
#                         precondition=row.get("precondition", ""),
#                         steps=row.get("steps", ""),
#                         expected=row.get("expected", ""),
#                         evidence_source=row.get("evidence_source", ""),
#                         evidence_level=row.get("evidence_level", ""),
#                         evi_block_ids=row.get("evi_block_ids", ""),
#                         doc_name=doc_name, doc_version=doc_version, source="ai",
#                     )
#                     db.session.add(tc)
#                     count += 1
#                 db.session.commit()
#
#                 push(task_id, f"[入库] 完成，共入库 {count} 条用例", kind="log")
#                 push_stage(task_id, "DONE")
#
#             except Exception as e:
#                 import traceback
#                 push(task_id, f"[异常] {e}\n{traceback.format_exc()}", kind="log")
#             finally:
#                 end_stream(task_id)
#
#     threading.Thread(target=_run, daemon=True).start()


def start_generate_task(docx_path, doc_name, doc_version, app):
    task_id = create_task()
    threading.Thread(
        target=_run_generate,
        args=(task_id, docx_path, doc_name, doc_version, app),
        daemon=True,
    ).start()
    return task_id