"""DevOps 自动登录 + Token 缓存管理"""
import json
import time
import threading
from pathlib import Path

from config import Config


# Token 缓存文件（持久化，重启服务不用重新登录）
_TOKEN_CACHE_FILE = Path(Config.TRAE_WORKSPACE) / ".devops_token.json"


class DevOpsAuthManager:
    """单例：管理 token，过期自动重新登录"""
    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self.token = None
        self.expire_ms = 0
        self._login_lock = threading.Lock()
        self._load_cache()
        # 后台自动刷新线程
        threading.Thread(target=self._auto_refresh_loop, daemon=True).start()

    def _load_cache(self):
        if _TOKEN_CACHE_FILE.exists():
            try:
                data = json.loads(_TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
                self.token = data.get("token")
                self.expire_ms = data.get("expire_ms", 0)
                print(f"[DevOpsAuth] 已加载缓存 token")
            except Exception as e:
                print(f"[DevOpsAuth] 缓存读取失败：{e}")

    def _save_cache(self):
        try:
            _TOKEN_CACHE_FILE.write_text(
                json.dumps({"token": self.token, "expire_ms": self.expire_ms}),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[DevOpsAuth] 缓存写入失败：{e}")

    def is_valid(self):
        """token 是否有效（留 5 分钟安全余量）"""
        if not self.token:
            return False
        return time.time() * 1000 < self.expire_ms - 5 * 60 * 1000

    def get_token(self):
        """获取有效 token，过期自动重新登录"""
        if self.is_valid():
            return self.token

        with self._login_lock:
            # 双重检查（防止并发重复登录）
            if self.is_valid():
                return self.token

            print("[DevOpsAuth] token 失效，自动登录中...")
            token, expire_ms = self._login_with_playwright()
            self.token = token
            self.expire_ms = expire_ms
            self._save_cache()
            print(f"[DevOpsAuth] 登录成功，token 已缓存")
            return token

    def _login_with_playwright(self):
        """用 Playwright 登录，拦截 /noCode/login 响应拿 token"""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # 优先用系统 Chrome；没有就下载 chromium
            try:
                browser = p.chromium.launch(headless=True, channel="chrome")
            except Exception:
                browser = p.chromium.launch(headless=True)

            context = browser.new_context()
            page = context.new_page()

            token_data = {}

            def on_response(response):
                if "/noCode/login" in response.url and response.status == 200:
                    try:
                        data = response.json()
                        if data.get("code") == 0:
                            token_data["token"] = data["data"]["token"]
                            token_data["expire_ms"] = int(data["data"]["expireTime"])
                            print("[DevOpsAuth] 已拦截到登录响应")
                    except Exception as e:
                        print(f"[DevOpsAuth] 解析登录响应失败：{e}")

            page.on("response", on_response)

            try:
                print(f"[DevOpsAuth] 打开登录页：{Config.DEVOPS_BASE_URL}")
                page.goto(Config.DEVOPS_BASE_URL, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
                page.wait_for_timeout(2000)

                # 填账号
                page.fill('#username', Config.DEVOPS_USERNAME)

                # 填密码
                page.fill('#password', Config.DEVOPS_PASSWORD)

                # 点登录按钮
                btn = page.query_selector('button:has-text("登录")')
                if not btn:
                    btn = page.query_selector('button[type="submit"]')
                if btn:
                    btn.click()
                else:
                    page.keyboard.press("Enter")

                # 等 token（最多 30 秒）
                for _ in range(60):
                    if token_data.get("token"):
                        break
                    page.wait_for_timeout(500)

                if not token_data.get("token"):
                    # 失败截图，方便排查
                    shot = Path(Config.TRAE_WORKSPACE) / "devops_login_fail.png"
                    page.screenshot(path=str(shot))
                    raise RuntimeError(f"登录失败，未拿到 token。截图：{shot}")

                return token_data["token"], token_data["expire_ms"]

            finally:
                browser.close()

    def _auto_refresh_loop(self):
        """后台每 30 分钟检查一次，快过期就自动刷新"""
        while True:
            try:
                time.sleep(30 * 60)
                if not self.is_valid():
                    print("[DevOpsAuth] 后台检测到 token 即将失效，自动刷新")
                    self.get_token()
            except Exception as e:
                print(f"[DevOpsAuth] 后台刷新异常：{e}")


# 单例获取
_auth_manager = None

def get_auth_manager():
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = DevOpsAuthManager()
    return _auth_manager

def get_token():
    """供外部调用：拿一个有效 token"""
    return get_auth_manager().get_token()