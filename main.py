"""
# trae_service.py 和 cross_validator.py里Python 脚本 -> 唤起本地的 traecli.exe -> traecli 用本地的秘钥去向云端发请求 -> 返回结果给 Python。
flask_web/
├── app.py                     # 主入口
├── config.py                  # 配置
├── models.py                  # 数据模型
├── services/
│   ├── __init__.py
│   ├── importer.py            # md 导入
│   └── trae_service.py        # AI 生成（含任务队列）
├── templates/
│   ├── base.html
│   └── cases/
│       ├── list.html
│       ├── form.html
│       ├── import.html
│       └── generate.html
├── static/
│   └── css/style.css
└── requirements.txt


流程
docx 上传
  → preprocess（source_block 入库 + block_list.txt）
  → Doubao 生成 md
  → 规则审计（Python）
  → 有漏抽？自动修复 → 再审
  → 规则审计通过
  → ┌─ GLM-5.3 独立审计 ──┐
     └─ DeepSeek-V4-Pro ──┘
     → 输出 cross_validation_report.md
     → 前端显示"正在异构交叉验证..."
  → 等用户确认
  → 用户确认入库（E4/E5 拦截 + Schema 校验）

"""
"""临时测试：直接上传 devops_template.xlsx 到 DevOps"""
from app import app
from services.devops_client import DevOpsClient

with app.app_context():
    try:
        client = DevOpsClient()
        result = client.push_cases_from_template(
            r"G:\traework\devops_template.xlsx"
        )
        print("=" * 60)
        print("结果：", result)
        print("=" * 60)
    except Exception as e:
        import traceback
        print("失败：")
        traceback.print_exc()