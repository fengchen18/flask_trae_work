"""全局配置"""
import os

class Config:
    # MySQL 连接（复用你的 my_project 库）
    SQLALCHEMY_DATABASE_URI = "mysql+pymysql://root:wlw123456@127.0.0.1:3306/my_project?charset=utf8mb4"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "change-this-in-production"

    # 上传目录
    UPLOAD_FOLDER = r"G:\traework\web_uploads"

    # Trae CLI 相关,本地trae work程序位置
    CLI_BIN = r"C:\Users\admin\AppData\Local\trae-cli\bin\traecli.exe"
    TRAE_WORKSPACE = r"G:\traework"
    BLOCK_LIST_FILE = r"G:\traework\block_list.txt"
    CLI_TIMEOUT = 1800  # 秒

    # 分页
    PER_PAGE = 20

    # ===== 异构交叉验证配置 =====
    # 生成模型（主模型）
    GENERATE_MODEL = "Doubao-Seed-Evolving"

    # 审计模型列表（异构模型，与生成模型不同）命令traecli models  可查支持的模型
    AUDIT_MODELS = [
        {"name": "GLM-5.3", "label": "智谱GLM"},
        {"name": "DeepSeek-V4.1-Flash", "label": "DeepSeek"},
    ]

    # 启用异构交叉验证
    ENABLE_CROSS_VALIDATION = True

    # 交叉验证审计的超时（秒）
    CROSS_AUDIT_TIMEOUT = 600

    @staticmethod
    def init_dirs():
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

    # ===== DevOps 平台配置 =====
    # 登录账号（Playwright 自动登录用）
    DEVOPS_USERNAME = "chenfeng"
    DEVOPS_PASSWORD = "Ab123456"

    # devops平台地址 & 基础参数
    # DEVOPS_BASE_URL = "http://60.166.4.238:30008"
    DEVOPS_BASE_URL = "http://218.22.25.8:30008"
    DEVOPS_APP_CODE = "devops"
    DEVOPS_ORG_ID = "2588053279164260352"
    DEVOPS_INSTANCE_ID = "32"
    DEVOPS_RESOURCE_CODE = "project_scrum"
    DEVOPS_ISSUES_TYPE_ID = "111"
    DEVOPS_AMP_SIGN = "f23d647ce0bd9b1883509d91538decb"

    # 目标目录 ID（Excel 转 JSON 时用的 id，不直接填到 Excel 里）
    DEVOPS_DEFAULT_TEST_SET_ID = "317503"

    # ===== Excel 导入模板 =====
    # 官方 .xls 模板用 Excel 另存为 .xlsx 后放这个路径
    DEVOPS_TEMPLATE_PATH = r"G:\traework\devops_template.xlsx"

    # ===== Excel 里填的【名称】（不是 ID）=====
    DEVOPS_ASSIGNED_NAME = "陈峰"  # 负责人姓名
    DEVOPS_TAG_NAME = "活动专区"  # 标签名称
    DEVOPS_PROJECT_NAME = "活动专区"  # 所属项目名称
    # 把用例集名称改成完整路径
    DEVOPS_TEST_SET_NAME = "活动专区/2026年/资金有礼点金升级V1.0"  # 所属用例集名称

    # ===== 优先级映射（Excel 里要中文）=====
    DEVOPS_PRIORITY_NAME_MAP = {
        "P0": "紧急",
        "P1": "高",
        "P2": "中",
        "P3": "低",
    }

    # ===== 以下字段暂时保留，Excel 通道用不上，但代码别处可能引用 =====
    DEVOPS_DEFAULT_ASSIGNED_ID = "2588129424689782784"  # 陈峰的 id
    DEVOPS_DEFAULT_TAG_ID = "3227347366607056896"  # 活动专区 tag
    DEVOPS_PRIORITY_MAP = {  # 旧 JSON 通道用，暂时留着
        "P0": "4",
        "P1": "3",
        "P2": "2",
        "P3": "1",
    }