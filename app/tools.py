"""Agent 可以调用的受控业务工具。"""

from pathlib import Path
from typing import Any

from app.database import get_order_by_id


def query_order_tool(
    order_id: str,
    db_path: str | Path,
) -> dict[str, Any] | None:
    """
    查询订单工具。

    Agent 只能调用这个受控函数，不能生成 SQL 后直接操作数据库。
    这样可以限制权限并复用 database.py 的异常处理。
    """
    return get_order_by_id(order_id, db_path)
