"""DevOps 平台客户端：完整复刻"Excel → check → import"三步流程"""
import time


import requests
from config import Config
from services.devops_auth import get_token


class DevOpsClient:
    def __init__(self):
        self.base_url = Config.DEVOPS_BASE_URL.rstrip("/")
        self.session = requests.Session()

    def _headers(self, content_type="application/json"):
        """通用请求头（严格对齐浏览器抓包）"""
        token = get_token()
        h = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Amp-App-Code": Config.DEVOPS_APP_CODE,
            "Amp-Organ-Id": Config.DEVOPS_ORG_ID,  # ← 关键：Organ 不是 Org
            "Amp-Resource-Instance-Id": Config.DEVOPS_INSTANCE_ID,
            "Amp-Resource-Type-Code": Config.DEVOPS_RESOURCE_CODE,
            "Amp-Sign": Config.DEVOPS_AMP_SIGN,
            "Authorization": token,
            "Cookie": f"token={token}",  # ← 顺手加上 token Cookie
        }
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _query_params(self):
        return {
            "issuesTypeId": Config.DEVOPS_ISSUES_TYPE_ID,
            "instanceId": Config.DEVOPS_INSTANCE_ID,
            "resourceCode": Config.DEVOPS_RESOURCE_CODE,
        }

    def get_test_set_tree(self):
        """
        获取devops平台用例集目录树。
        DevOps 返回的 issuesTypeId=112（用例集），不是 111（用例）。
        """
        url = f"{self.base_url}/api/track-issues/track/issues/test/set/tree"
        payload = {
            "issuesTypeId": "112",
            "orderBy": "createTime",
            "sequence": True,
            "search": {
                "belongToProject": {
                    "operator": "in",
                    "value": Config.DEVOPS_INSTANCE_ID,
                }
            },
        }
        resp = self.session.post(
            url, json=payload, headers=self._headers(), timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        # 给每个节点补上 full_path（Excel 导入时"所属用例集"列需要路径）
        def add_path(nodes, prefix=""):
            for n in nodes:
                full_path = f"{prefix}/{n['name']}" if prefix else n["name"]
                n["full_path"] = full_path
                if n.get("children"):
                    add_path(n["children"], full_path)

        add_path(data.get("data", []))
        return data
    # ==================================================
    # 1. 生成 Excel
    # ==================================================
    def _build_excel(self, cases, test_set_id=None, test_set_path=None):
        """基于平台官方模板生成 Excel"""
        from openpyxl import load_workbook
        from io import BytesIO
        from pathlib import Path
        import re

        template_path = Path(Config.DEVOPS_TEMPLATE_PATH)
        if not template_path.exists():
            raise FileNotFoundError(f"平台模板不存在：{template_path}")

        wb = load_workbook(str(template_path))
        ws = wb.active

        def clean(text):
            if not text:
                return ""
            text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
            text = re.sub(r"<[^>]+>", "", text)
            return text.strip()

        priority_map = Config.DEVOPS_PRIORITY_NAME_MAP
        assigned_name = Config.DEVOPS_ASSIGNED_NAME
        tag_name = Config.DEVOPS_TAG_NAME
        project_name = Config.DEVOPS_PROJECT_NAME
        # test_set_name = Config.DEVOPS_TEST_SET_NAME  # ← 现在是从 config 读的完整路径
        test_set_name = test_set_path or Config.DEVOPS_TEST_SET_NAME
        row = 2
        count = 0
        for c in cases:
            priority = (c.priority or "").strip().upper()
            priority_val = priority_map.get(priority, "中")

            ws.cell(row=row, column=1, value=clean(c.title))
            ws.cell(row=row, column=2, value=priority_val)
            ws.cell(row=row, column=3, value=assigned_name)
            ws.cell(row=row, column=4, value=tag_name)
            ws.cell(row=row, column=5, value=project_name)
            ws.cell(row=row, column=6, value=test_set_name)
            ws.cell(row=row, column=7, value=clean(c.case_type or "功能测试"))
            ws.cell(row=row, column=8, value=clean(c.precondition))
            ws.cell(row=row, column=9, value=clean(c.steps))
            ws.cell(row=row, column=10, value=clean(c.expected))
            row += 1
            count += 1

        debug_path = Path(Config.TRAE_WORKSPACE) / "devops_import_debug.xlsx"
        wb.save(str(debug_path))
        print(f"[DevOps] Excel 已生成：{debug_path}（{count} 条数据）", flush=True)

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    # ==================================================
    # 2. check 接口
    # ==================================================
    def _call_check(self, excel_buf, filename):
        """上传 Excel 到 check 接口，返回 importFieldValueDTOList 列表"""
        url = f"{self.base_url}/api/track-issues/track/issues/import/check"

        # multipart/form-data
        files = {
            "file": (
                filename,
                excel_buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        }
        data = {"issuesTypeId": Config.DEVOPS_ISSUES_TYPE_ID}

        # 注意：不传 Content-Type，让 requests 自动设置带 boundary 的 multipart
        resp = self.session.post(
            url,
            params=self._query_params(),
            files=files,
            data=data,
            headers=self._headers(content_type=None),
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()

        print(f"[DevOps] check 响应 code={result.get('code')}", flush=True)

        if result.get("code") != 0:
            raise RuntimeError(f"check 接口失败：{result.get('msg')}")

        data = result.get("data") or {}
        success_list = data.get("successList", []) or []
        failed_list = data.get("failedList", []) or []

        if failed_list:
            print(f"[DevOps]  校验失败 {len(failed_list)} 行：", flush=True)
            for f in failed_list[:5]:
                print(f"  - {f.get('title')}: {f.get('desc')}", flush=True)

        value_list = [item["importFieldValueDTOList"] for item in success_list]
        return value_list

    # ==================================================
    # 3. import 接口
    # ==================================================
    def _call_import(self, value_list):
        """把 check 返回的 valueList 传给 import 接口"""
        url = f"{self.base_url}/api/track-issues/track/issues/import"
        payload = {
            "issuesTypeId": Config.DEVOPS_ISSUES_TYPE_ID,
            "instanceId": Config.DEVOPS_INSTANCE_ID,
            "resourceCode": Config.DEVOPS_RESOURCE_CODE,
            "valueList": value_list,
        }

        resp = self.session.post(
            url,
            params=self._query_params(),
            json=payload,
            headers=self._headers(),
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    # ==================================================
    # 对外主入口
    # ==================================================
    def push_cases(self, cases, test_set_id=None, test_set_path=None):
        """
        完整三步流程：生成 Excel → check → import
        - test_set_id：目标用例集 ID（传给平台接口，用于日志/兜底）
        - test_set_path：目标用例集完整路径（如"活动专区/2026年/资金有礼点金升级V1.0"），
                         这是真正写进 Excel"所属用例集"列的值
        """
        if not cases:
            return {"code": -1, "msg": "没有用例要推送"}

        # test_set_id 兜底
        test_set_id = test_set_id or Config.DEVOPS_DEFAULT_TEST_SET_ID

        # ---- 1. 生成 Excel ----
        print(f"[DevOps] 生成 Excel，共 {len(cases)} 条，目标路径={test_set_path}...", flush=True)
        excel_buf = self._build_excel(cases, test_set_id, test_set_path)
        filename = f"cases_{int(time.time())}.xlsx"

        # ---- 2. check ----
        print(f"[DevOps] 调用 check 接口...", flush=True)
        value_list = self._call_check(excel_buf, filename)
        print(f"[DevOps] check 通过 {len(value_list)} 条", flush=True)

        if not value_list:
            return {"code": -1, "msg": "check 接口返回 0 条合法数据，请检查 Excel 格式"}

        # ---- 3. import ----
        print(f"[DevOps] 调用 import 接口，{len(value_list)} 条...", flush=True)
        result = self._call_import(value_list)
        print(f"[DevOps] import 返回：{result}", flush=True)
        return result
