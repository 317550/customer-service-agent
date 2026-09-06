import os
from pathlib import Path


# 项目根目录，而不是当前终端所在目录。
BASE_DIR = Path(__file__).resolve().parent.parent

# 允许部署环境通过环境变量指定数据库；
# 未配置时使用项目 data 目录下的 orders.db。
DEFAULT_DATABASE_PATH = BASE_DIR / "data" / "orders.db"

DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH", str(DEFAULT_DATABASE_PATH))
).expanduser().resolve()