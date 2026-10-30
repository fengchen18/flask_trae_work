import json
import re
from pathlib import Path
from config import Config
from models import db, TestPoint, WebTestCase, RequirementDoc
from services.trae_service import _call_cli_streaming, push, push_stage


def extract_points_task(task_id, docx_path, doc_name, doc_version, app, push_fn):
    """调用大模型提取测试点（不生成完整用例）"""
    with app.app_context():
        try:
            doc = RequirementDoc.query.filter_by(doc_name=doc_name, doc_version=doc_version).first()
            if not doc:
                push_fn(task_id, "[错误] 找不到需求文档记录", kind="log")
                return

            # 读取我们之前切好的块
            bl_content = Path(Config.BLOCK_LIST_FILE).read_text(encoding="utf-8")

            prompt = f"""请使用项目技能 testcase，作为测试专家，基于以下需求源块提取【测试点】。
            请不要写完整的测试用例，只需要提取精炼的测试点。

            要求：
            1. 输出格式必须为 JSON 数组，每个元素包含：
               - scene: 所属业务场景（如：首页核心、悬浮按钮、挽留弹窗、跨场景等，用来给测试点分类）
               - method: 测试设计方法（必须是：场景法、边界值、等价类、判定表、状态迁移、错误推测 之一）
               - content: 测试点标题（一句话）
               - intent: 测试意图
               - category: 测试类型（功能/边界/异常/UI）
               - priority: 优先级（P0/P1/P2）
               - evidence_ids: 对应的 block_id，多个用分号隔开。**如果纯属推导，无法关联到具体块，请留空字符串！**
            2. 测试点要尽可能细致，覆盖正向、反向、边界。
            3. **必须严格输出纯 JSON 格式，不要包含任何 markdown 代码块标识。**

            ======== 需求源块清单 ========
            {bl_content}
            ======== 清单结束 ========
            """
            push_fn(task_id, "[测试点提取] 正在调用模型分析需求...", kind="log")
            rc, output = _call_cli_streaming(task_id, prompt, 300, session_id=f"tp-{task_id}")

            if rc != 0:
                push_fn(task_id, "[测试点提取] 模型调用失败", kind="log")
                return

            # 解析 JSON（清理可能的 markdown 标记）
            json_str = output.strip()
            if json_str.startswith("```json"):
                json_str = json_str[7:-3].strip()
            elif json_str.startswith("```"):
                json_str = json_str[3:-3].strip()

            try:
                points_data = json.loads(json_str)
            except Exception as e:
                push_fn(task_id, f"[测试点提取] JSON 解析失败: {e}\n原始输出: {output[:500]}", kind="log")
                return

            # 入库
            count = 0
            for p in points_data:
                tp = TestPoint(
                    requirement_doc_id=doc.id,
                    content=p.get("content", ""),
                    scene=p.get("scene", "通用场景"),
                    method=p.get("method", ""),  # <--- 加上这个
                    intent=p.get("intent", ""),
                    category=p.get("category", "功能"),
                    priority=p.get("priority", "P1"),
                    evidence_ids=p.get("evidence_ids", ""),
                    status="pending"
                )
                db.session.add(tp)
                count += 1
            db.session.commit()

            push_fn(task_id, f"__EXTRACT_DONE__:{count}", kind="log")
            push_fn(task_id, f"[测试点提取] 完成，共提取 {count} 个测试点，请前往评审。", kind="log")

        except Exception as e:
            import traceback
            push_fn(task_id, f"[异常] {traceback.format_exc()}", kind="log")
        finally:
            from services.trae_service import end_stream
            end_stream(task_id)


def generate_from_points_task(task_id, point_ids, app, push_fn):
    """根据选中的测试点，扩写为完整用例"""
    from models import db, WebTestCase, Evidence, RequirementDoc, CaseSet
    from services.importer import parse_md_table
    import pymysql
    from pathlib import Path
    from config import Config

    with app.app_context():
        try:
            points = TestPoint.query.filter(TestPoint.id.in_(point_ids)).all()
            if not points:
                push_fn(task_id, "[错误] 未找到指定的测试点", kind="log")
                return

            # 组装测试点信息
            tp_text = "\n".join([f"- [{p.id}] {p.content} (证据块:{p.evidence_ids})" for p in points])

            prompt = f"""请使用项目技能 testcase，根据以下已通过评审的【测试点】，扩写为完整的测试用例。

要求：
1. 输出标准的 Markdown 表格（含标题、前置条件、测试步骤、预期结果、证据块ID等13列）。
2. 每个测试点至少生成 1 条详细用例，步骤必须包含具体的操作和数据验证。
3. 表头必须与之前规范一致。
4. 生成的用例会自动入库，请直接输出表格内容，不要额外废话。

======== 待扩写的测试点 ========
{tp_text}
======== 结束 ========
"""
            push_fn(task_id, "[用例生成] 正在扩写用例...", kind="log")
            rc, output = _call_cli_streaming(task_id, prompt, 600, session_id=f"gen-{task_id}")

            if rc != 0:
                push_fn(task_id, "[用例生成] 模型调用失败", kind="log")
                return

            # 解析 md 表格
            rows = parse_md_table(output)
            if not rows:
                push_fn(task_id, "[用例生成] 未解析到有效用例数据，请检查大模型输出格式", kind="log")
                return

            # 获取关联的需求文档和用例集
            doc = None
            if points[0].requirement_doc_id:
                doc = db.session.get(RequirementDoc, points[0].requirement_doc_id)

            doc_name = doc.doc_name if doc else "未知文档"
            doc_version = doc.doc_version if doc else ""

            cs = CaseSet.query.filter_by(name=doc_name).first()
            case_set_id = cs.id if cs else None

            # 数据库连接配置（用于查 source_block）
            db_config = {
                "host": "127.0.0.1", "user": "root",
                "password": "wlw123456", "port": 3306,
                "database": "my_project", "charset": "utf8mb4",
                "cursorclass": pymysql.cursors.DictCursor, "autocommit": True
            }
            conn = pymysql.connect(**db_config)

            count = 0
            try:
                for row in rows:
                    if not row.get("title"):
                        continue

                    # 【核心修复】将 <br> 标签替换为真正的换行符 \n
                    steps_clean = re.sub(r'<br\s*/?>', '\n', row.get("steps", ""), flags=re.IGNORECASE)
                    expected_clean = re.sub(r'<br\s*/?>', '\n', row.get("expected", ""), flags=re.IGNORECASE)

                    tc = WebTestCase(
                        title=row.get("title", ""),
                        priority=row.get("priority", ""),
                        owner=row.get("owner", ""),
                        tags=row.get("tags", ""),
                        project=row.get("project", ""),
                        case_set=row.get("case_set", ""),
                        case_type=row.get("case_type", ""),
                        precondition=row.get("precondition", ""),
                        # steps=row.get("steps", ""),
                        steps=steps_clean,
                        # expected=row.get("expected", ""),
                        expected_steps=expected_clean,
                        evidence_source=row.get("evidence_source", ""),
                        evidence_level=row.get("evidence_level", ""),
                        evi_block_ids=row.get("evi_block_ids", ""),
                        source="ai",
                        requirement_doc_id=doc.id if doc else None,
                        case_set_id=case_set_id,
                        test_point_id=points[0].id if points else None,
                        status="draft"  # 默认存入草稿箱
                    )
                    db.session.add(tc)
                    db.session.flush()  # 必须先 flush 拿到 tc.id

                    # 写入 Evidence 实体快照
                    ids_str = (row.get("evi_block_ids") or "").strip()
                    if ids_str:
                        for bid in ids_str.split(";"):
                            bid = bid.strip()
                            if bid.isdigit():
                                with conn.cursor() as cur:
                                    cur.execute("SELECT content_text, content_hash FROM source_block WHERE id=%s",
                                                (int(bid),))
                                    sb = cur.fetchone()
                                    if sb:
                                        evi = Evidence(
                                            test_case_id=tc.id,
                                            source_block_id=int(bid),
                                            quote=sb["content_text"],
                                            content_hash=sb["content_hash"],
                                            evidence_level=row.get("evidence_level", "")
                                        )
                                        db.session.add(evi)
                    count += 1
                db.session.commit()

                # 将选中的测试点状态标记为已处理（可选，已经通过的话其实不用改）
                for p in points:
                    p.status = "approved"
                db.session.commit()

            finally:
                conn.close()

            # 推送完成信号和统计
            push_fn(task_id, f"__GEN_DONE__:{count}", kind="log")
            push_fn(task_id, f"[用例生成] 完成，共生成 {count} 条草稿用例，已存入用例集【{doc_name}】。", kind="log")

        except Exception as e:
            import traceback
            push_fn(task_id, f"[异常] {traceback.format_exc()}", kind="log")
        finally:
            from services.trae_service import end_stream
            end_stream(task_id)


def expert_review_task(task_id, point_ids, expert_id, app, push_fn):
    from models import Expert
    import subprocess, json
    from config import Config

    with app.app_context():
        try:
            expert = Expert.query.get(expert_id)
            if not expert:
                push_fn(task_id, "专家不存在", kind="log")
                return

            points = TestPoint.query.filter(TestPoint.id.in_(point_ids)).all()
            total = len(points)
            sys_prompt = expert.soul_md or "你是一个严苛的测试专家。"

            push_fn(task_id, f"🤖 正在呼叫【{expert.name}】({expert.model_name})...", kind="log")

            pass_count, reject_count, unknown_count = 0, 0, 0
            batch_size = 5  # 每次发给大模型 5 个测试点，防止截断

            for i in range(0, total, batch_size):
                batch = points[i:i + batch_size]
                tp_text = "\n".join([f"- ID:{p.id} 标题:{p.content} 证据块:{p.evidence_ids}" for p in batch])

                prompt = f"""{sys_prompt}
                请对以下测试点进行评审。你必须严格按照以下规则输出结论和理由：
                1. 如果你判定为【建议通过】：你的建议内容必须以肯定为主。如果发现极小瑕疵，用“唯一小瑕疵是...但不影响有效性”结尾。绝对不要长篇大论！
                2. 如果你判定为【建议拒绝】：直接指出致命错误，不要废话。
                3. 如果你判定为【不确定】：指出需要澄清的核心疑点。

                【格式铁律】：**绝对禁止输出任何分析过程、解释性文字或客套话！你的回复必须且只能以 `[` 开头，以 `]` 结尾！直接输出纯 JSON 数组！**

                格式：
                [{{"id": 1, "opinion": "建议通过", "advice": "理由", "is_attention": false}}]

                ======== 测试点清单 ========
                {tp_text}
                ======== 结束 ========
                """
                cmd = [Config.CLI_BIN, "--print", "-c", f"model.name={expert.model_name}", "--permission-mode",
                       "bypass_permissions", prompt]
                proc = subprocess.run(cmd, cwd=Config.TRAE_WORKSPACE, capture_output=True, text=True, encoding="utf-8",
                                      errors="replace")

                output = proc.stdout
                if proc.returncode != 0 or not output:
                    push_fn(task_id, f"批次 {i // batch_size + 1} 模型无输出", kind="log")
                    continue

                json_str = output.strip()
                # if json_str.startswith("```json"):
                #     json_str = json_str[7:-3].strip()
                # elif json_str.startswith("```"):
                #     json_str = json_str[3:-3].strip()


                # === 加上这段正则提取 ===
                import re
                json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', json_str, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    start_idx = json_str.find('[')
                    end_idx = json_str.rfind(']')
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        json_str = json_str[start_idx:end_idx + 1]
                # ========================



                try:
                    results = json.loads(json_str)
                    for item in results:
                        tp = TestPoint.query.get(item["id"])
                        if tp:
                            tp.expert_name = expert.name
                            tp.expert_opinion = item.get("opinion", "")
                            tp.expert_advice = item.get("advice", "")
                            if item.get("is_attention"):
                                tp.is_attention = True

                            if tp.expert_opinion == "建议通过":
                                pass_count += 1
                            elif tp.expert_opinion == "建议拒绝":
                                reject_count += 1
                            else:
                                unknown_count += 1
                    db.session.commit()
                except Exception as e:
                    push_fn(task_id, f"JSON解析失败 (批次 {i // batch_size + 1}): {output[:100]}", kind="log")
                    continue

                # 推送进度
                current_done = min(i + batch_size, total)
                push_fn(task_id, f"__PROGRESS__:正在评审... 已完成 {current_done}/{total}", kind="log")

            push_fn(task_id, f"__DONE__:建议通过 {pass_count} · 建议拒绝 {reject_count} · 不确定 {unknown_count}",
                    kind="log")

        except Exception as e:
            push_fn(task_id, f"异常: {e}", kind="log")
        finally:
            from services.trae_service import end_stream
            end_stream(task_id)