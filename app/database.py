"""
这里使用 contextmanager，是为了确保成功或失败后数据库连接都会关闭：

with open_database(db_path) as connection:

它比每个函数都重复写：

connection = ...
try:
    ...
finally:
    connection.close()

更适合后续扩展。
"""
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class DatabaseOperationError(RuntimeError):
    """数据库无法连接或执行查询时抛出的应用异常。"""


class DuplicateOrderError(ValueError):
    """订单号违反唯一约束时抛出的业务异常。"""


@contextmanager
def open_database(
    db_path: str | Path,
) -> Iterator[sqlite3.Connection]:
    """创建并确保关闭数据库连接。"""

    try:
        connection = sqlite3.connect(
            str(db_path),
            timeout=5,
        )
    except sqlite3.Error as exc:
        logger.exception("无法连接订单数据库")
        raise DatabaseOperationError("无法连接订单数据库") from exc

    connection.row_factory = sqlite3.Row

    try:
        yield connection
    finally:
        connection.close()


def init_db(db_path: str | Path) -> None:
    """初始化订单表。"""

    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open_database(database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE NOT NULL,
                    customer_id TEXT NOT NULL,
                    product TEXT NOT NULL,
                    amount REAL NOT NULL CHECK (amount >= 0),
                    status TEXT NOT NULL
                )
                """
            )
            connection.commit()
    except DatabaseOperationError:
        raise
    except sqlite3.Error as exc:
        logger.exception("初始化订单表失败")
        raise DatabaseOperationError("初始化订单表失败") from exc


def insert_order(
    order: dict[str, Any],
    db_path: str | Path,
) -> int:
    """插入订单，并返回数据库主键。"""

    try:
        with open_database(db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO orders (
                    order_id,
                    customer_id,
                    product,
                    amount,
                    status
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    order["order_id"],
                    order["customer_id"],
                    order["product"],
                    order["amount"],
                    order["status"],
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    except sqlite3.IntegrityError as exc:
        raise DuplicateOrderError(
            f"订单号已经存在：{order['order_id']}"
        ) from exc

    except (sqlite3.Error, KeyError) as exc:
        logger.exception("插入订单失败")
        raise DatabaseOperationError("插入订单失败") from exc


def get_order_by_id(
    order_id: str,
    db_path: str | Path,
) -> dict[str, Any] | None:
    """按照唯一订单号查询订单。"""

    try:
        with open_database(db_path) as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    order_id,
                    customer_id,
                    product,
                    amount,
                    status
                FROM orders
                WHERE order_id = ?
                """,
                (order_id,),
            ).fetchone()

    except DatabaseOperationError:
        raise
    except sqlite3.Error as exc:
        logger.exception(
            "查询订单失败，order_id=%s",
            order_id,
        )
        raise DatabaseOperationError("查询订单失败") from exc

    return dict(row) if row is not None else None