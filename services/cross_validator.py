"""异构交叉验证：调用不同模型对测试用例做独立审计"""
import json
import subprocess
import threading
import time
from pathlib import Path
import concurrent.futures
from config import Config


def _call_cli_with_model(task_id, prompt, model_name, timeout, push_fn):
    """
    用指定模型调用 CLI 做一次性审计（非流式，只需要最终结果）。
    返回 (returncode, 输出文本)
    """
    cmd = [
        Config.CLI_BIN,
        "--print",
        "-c", f"model.name={model_name}",
        "--output-format", "text",
        "--permission-mode", "bypass_permissions",
        prompt,
    ]

    push_fn(task_id, f"[交叉验证] 调用模型 {model_name}...", kind="log")

    proc = subprocess.Popen(
        cmd,
        cwd=Config.TRAE_WORKSPACE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        push_fn(task_id, f"[交叉验证] {model_name} 超时（{timeout}s）", kind="log")
        return 1, ""

    if proc.returncode != 0 and stderr:
        push_fn(task_id, f"[交叉验证] {model_name} stderr: {stderr[:500]}", kind="log")

    return proc.returncode, stdout or ""


AUDIT_PROMPT_TEMPLATE = """你是一个独立的需求审计专家。请对以下测试用例文件进行审计，**不要修改文件**，只输出审计结论。

请从以下维度审计：
1. **需求覆盖完整性**：测试用例是否覆盖了需求文档中的所有业务场景？有没有遗漏？
2. **用例合理性**：测试步骤和预期结果是否合理？有没有逻辑错误或矛盾？
3. **证据链完整性**：每条用例的证据块ID引用是否合理？有没有该引用但没引用的？
4. **边界场景**：关键业务规则（如资产门槛、积分发放）的边界值是否覆盖？

文件路径：{md_path}
需求源文件路径：{docx_path}

请按以下格式输出结论（严格遵守）：
## 审计结论
- 覆盖完整性：[通过/不通过]
- 用例合理性：[通过/不通过] 
- 证据链完整性：[通过/不通过]
- 边界场景：[通过/不通过]

## 发现的问题
1. [问题描述]
2. [问题描述]

## 总体评价
[一句话总结]
"""


# def cross_validate(task_id, md_path, docx_path, push_fn):
#     """
#     用多个异构模型对 md 做独立审计。
#     返回：{
#         "passed": bool,           # 所有模型是否都通过
#         "reports": [              # 每个模型的报告
#             {"model": "GLM-5.3", "passed": bool, "report": "...", "duration": 12.3},
#             ...
#         ],
#         "summary": "..."          # 汇总文本
#     }
#     """
#     models = Config.AUDIT_MODELS
#     if not models:
#         return {"passed": True, "reports": [], "summary": "未配置审计模型，跳过交叉验证"}
#
#     push_fn(task_id, f"\n[交叉验证] 启动异构审计，共 {len(models)} 个模型", kind="log")
#
#     reports = []
#     for m in models:
#         model_name = m["name"]
#         model_label = m["label"]
#         start = time.time()
#
#         prompt = AUDIT_PROMPT_TEMPLATE.format(
#             md_path=md_path, docx_path=docx_path,
#         )
#         # 把 md 内容也附上，避免模型要读文件
#         md_content = Path(md_path).read_text(encoding="utf-8") if Path(md_path).exists() else ""
#         # 截断到 15000 字符，避免超出上下文
#         if len(md_content) > 15000:
#             md_content = md_content[:15000] + "\n\n... (truncated)"
#
#         full_prompt = f"{prompt}\n\n===== 测试用例内容 =====\n{md_content}\n===== 内容结束 ====="
#
#         rc, output = _call_cli_with_model(
#             task_id, full_prompt, model_name,
#             Config.CROSS_AUDIT_TIMEOUT, push_fn,
#         )
#         duration = time.time() - start
#
#         passed = False
#         if rc == 0 and output:
#             # 判断是否通过：检查结论里有没有"不通过"
#             has_fail = "不通过" in output
#             passed = not has_fail
#         else:
#             passed = None  # 无法判断
#
#         reports.append({
#             "model": model_name,
#             "label": model_label,
#             "passed": passed,
#             "report": output[:3000] if output else "",
#             "duration": round(duration, 1),
#             "error": None if rc == 0 else f"返回码 {rc}",
#         })
#
#         status = "✅ 通过" if passed is True else ("❌ 未通过" if passed is False else " 异常")
#         push_fn(task_id, f"[交叉验证] {model_label}（{model_name}）：{status}，耗时 {duration:.0f}s", kind="log")
#
#     # 汇总
#     all_passed = all(r["passed"] is True for r in reports if r["passed"] is not None)
#     any_failed = any(r["passed"] is False for r in reports)
#     any_error = any(r["passed"] is None for r in reports)
#
#     if any_failed:
#         summary = " 有模型未通过，请查看下方详细报告"
#     elif any_error:
#         summary = " 部分模型异常，其余通过"
#     else:
#         summary = "✅ 所有模型审计通过"
#
#     push_fn(task_id, f"\n[交叉验证] 汇总：{summary}", kind="log")
#
#     return {"passed": all_passed, "reports": reports, "summary": summary}

# 不要用 Prompt 传全文，直接让 CLI 自己去读本地的 md 文件！
# def cross_validate(task_id, md_path, docx_path, push_fn):
#     models = Config.AUDIT_MODELS
#     if not models:
#         return {"passed": True, "reports": [], "summary": "未配置审计模型"}
#
#     push_fn(task_id, f"\n[交叉验证] 启动异构审计，共 {len(models)} 个模型", kind="log")
#
#     reports = []
#     for m in models:
#         model_name = m["name"]
#         model_label = m["label"]
#         start = time.time()
#
#         # 核心改动：不让 Python 读文件，让 CLI 自己读文件
#         prompt = f"""你是一个独立的需求审计专家。请对以下测试用例文件进行审计，**不要修改文件**，只输出审计结论。
#
# 1. 请使用文件读取工具读取这个绝对路径的测试用例文件：{md_path}
# 2. 仔细审查其覆盖完整性、用例合理性、证据链完整性、边界场景。
# 3. 请按以下格式输出结论（严格遵守）：
# ## 审计结论
# - 覆盖完整性：[通过/不通过]
# - 用例合理性：[通过/不通过]
# - 证据链完整性：[通过/不通过]
# - 边界场景：[通过/不通过]
#
# ## 发现的问题
# （列出具体问题）
# """
#
#         rc, output = _call_cli_with_model(
#             task_id, prompt, model_name,
#             Config.CROSS_AUDIT_TIMEOUT, push_fn,
#         )
#         duration = time.time() - start
#
#         passed = False
#         if rc == 0 and output:
#             has_fail = "不通过" in output
#             passed = not has_fail
#         else:
#             passed = None
#
#         # 过滤掉 CLI 吐出的乱码（如 undefined）
#         clean_output = output.replace("undefined", "") if output else ""
#
#         reports.append({
#             "model": model_name,
#             "label": model_label,
#             "passed": passed,
#             "report": clean_output[:3000],
#             "duration": round(duration, 1),
#             "error": None if rc == 0 else f"返回码 {rc}",
#         })
#
#         status = "✅ 通过" if passed is True else ("❌ 未通过" if passed is False else "⚠️ 异常")
#         push_fn(task_id, f"[交叉验证] {model_label}（{model_name}）：{status}，耗时 {duration:.0f}s", kind="log")
#
#     # 汇总结果（原有逻辑）
#     all_passed = all(r["passed"] is True for r in reports if r["passed"] is not None)
#     any_failed = any(r["passed"] is False for r in reports)
#     any_error = any(r["passed"] is None for r in reports)
#
#     if any_failed:
#         summary = "⚠️ 有模型未通过，请查看下方详细报告"
#     elif any_error:
#         summary = "⚠️ 部分模型异常，其余通过"
#     else:
#         summary = "✅ 所有模型审计通过"
#
#     push_fn(task_id, f"\n[交叉验证] 汇总：{summary}", kind="log")
#     return {"passed": all_passed, "reports": reports, "summary": summary}
def cross_validate(task_id, md_path, docx_path, push_fn):
    models = Config.AUDIT_MODELS
    if not models:
        return {"passed": True, "reports": [], "summary": "未配置审计模型"}

    push_fn(task_id, f"\n[交叉验证] 启动异构审计，共 {len(models)} 个模型并发执行", kind="log")

    def run_single_model(m):
        model_name = m["name"]
        model_label = m["label"]
        start = time.time()

        prompt = f"""你是一个独立的需求审计专家。请对测试用例文件进行审计，**不要修改文件**，只输出审计结论。

1. 请读取该绝对路径：{md_path}
2. 审查维度：覆盖完整性、用例合理性、证据链完整性、边界场景。
3. 输出格式：
## 审计结论
- 覆盖完整性：[通过/不通过]
- 用例合理性：[通过/不通过] 
- 证据链完整性：[通过/不通过]
- 边界场景：[通过/不通过]

## 发现的问题
（列出具体问题）
"""
        rc, output = _call_cli_with_model(task_id, prompt, model_name, Config.CROSS_AUDIT_TIMEOUT, push_fn)
        duration = time.time() - start

        passed = False
        if rc == 0 and output:
            # 只认明确带有中括号的判定，避免正文里的普通字眼误判
            has_fail = "不通过" in output or "Fail" in output
            passed = not has_fail
        else:
            passed = None

        # 干掉 undefined 和 AI 的废话尾巴
        if output:
            clean_output = str(output).replace("undefined", "")
            clean_output = clean_output.replace("Done. Concise.", "").replace("Done.", "").strip()
        else:
            clean_output = ""

        return {
            "model": model_name,
            "label": model_label,
            "passed": passed,
            "report": clean_output[:4000],
            "duration": round(duration, 1),
            "error": None if rc == 0 else f"返回码 {rc}",
        }

    reports = []
    # ===== 核心改动：并发执行 =====
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(models)) as executor:
        future_to_model = {executor.submit(run_single_model, m): m for m in models}

        for future in concurrent.futures.as_completed(future_to_model):
            m = future_to_model[future]
            try:
                report = future.result()
                reports.append(report)
                status = "✅ 通过" if report["passed"] is True else (
                    "❌ 未通过" if report["passed"] is False else "⚠️ 异常")
                push_fn(task_id, f"[交叉验证] {report['label']}（{report['model']}）：{status}，耗时 {report['duration']}s",
                        kind="log")
            except Exception as exc:
                push_fn(task_id, f"[交叉验证] {m['label']} 执行异常: {exc}", kind="log")

    # 按初始顺序重新排好
    model_order = {m["name"]: i for i, m in enumerate(models)}
    reports.sort(key=lambda x: model_order.get(x["model"], 0))

    # 汇总
    all_passed = all(r["passed"] is True for r in reports if r["passed"] is not None)
    any_failed = any(r["passed"] is False for r in reports)

    if any_failed:
        summary = "⚠️ 有模型提出修改意见，可参考下方报告"
    else:
        summary = "✅ 所有模型审计通过"

    push_fn(task_id, f"\n[交叉验证] 汇总：{summary}", kind="log")
    return {"passed": all_passed, "reports": reports, "summary": summary}

def format_cross_report(result):
    """把交叉验证结果格式化成可读文本"""
    lines = ["\n========== 异构交叉验证报告 ==========\n"]
    lines.append(f"参与模型：{len(result['reports'])} 个\n")

    for r in result["reports"]:
        lines.append(f"\n--- {r['label']}（{r['model']}）---")
        if r["error"]:
            lines.append(f"状态： 异常（{r['error']}），耗时 {r['duration']}s")
        elif r["passed"]:
            lines.append(f"状态：✅ 通过，耗时 {r['duration']}s")
        else:
            lines.append(f"状态：❌ 未通过，耗时 {r['duration']}s")
        if r["report"]:
            lines.append(f"\n{r['report']}\n")

    lines.append(f"\n{result['summary']}")
    return "\n".join(lines)