import os
from pathlib import Path

from dotenv import load_dotenv


# 项目根目录，而不是当前终端所在目录。
BASE_DIR = Path(__file__).resolve().parent.parent

# 本地开发时从项目根目录的 .env 加载配置。
# 生产环境仍应优先使用平台注入的环境变量，不提交真实密钥。
load_dotenv(BASE_DIR / ".env")

# 允许部署环境通过环境变量指定数据库；
# 未配置时使用项目 data 目录下的 orders.db。
DEFAULT_DATABASE_PATH = BASE_DIR / "data" / "orders.db"

DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH", str(DEFAULT_DATABASE_PATH))
).expanduser().resolve()


# 信息提取器模式：
# rule     完全离线，适合测试和无密钥环境；
# deepseek 调用 DeepSeek，失败时自动降级到规则提取器。
INFORMATION_EXTRACTOR_MODE = os.getenv(
    "INFORMATION_EXTRACTOR_MODE",
    "rule",
).strip().lower()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv(
    "DEEPSEEK_BASE_URL",
    "https://api.deepseek.com",
).rstrip("/")
DEEPSEEK_MODEL = os.getenv(
    "DEEPSEEK_MODEL",
    "deepseek-chat",
).strip()
DEEPSEEK_TIMEOUT_SECONDS = float(
    os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "20")
)

# 只用于演示人工客服接口的最小权限边界。未配置时，状态更新接口不可用。
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()
