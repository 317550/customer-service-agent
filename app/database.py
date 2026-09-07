"""
为什么 sessions.order_id 没有设置外键？

因为用户可能先说出一个错误或尚未验证的订单号。会话状态应该能够暂时保存原始输入，等订单查询节点再判断订单是否存在。

如果直接设置外键，用户输入不存在的订单号时，状态都无法保存，不利于继续追问或纠正。
"""
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


logger = logging.getLogger(__name__)


class DatabaseOperationError(RuntimeError):
    """数据库连接或执行操作失败时抛出的应用异常。"""


class DuplicateOrderError(ValueError):
    """订单号违反唯一约束时抛出的业务异常。"""


def utc_now() -> str:
    """
    返回 UTC时间的 ISO 8601字符串。

    统一使用 UTC，避免服务器部署到不同时区后产生时间混乱。
    """
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def open_database(
    db_path: str | Path,
) -> Iterator[sqlite3.Connection]:
    """
    创建数据库连接，并确保使用结束后关闭连接。

    contextmanager 允许调用方使用：
        with open_database(...) as connection:
            ...

    无论代码正常结束还是抛出异常，finally 都会关闭连接。
    """
    try:
        connection = sqlite3.connect(
            str(db_path),
            timeout=5,
        )
    except sqlite3.Error as exc:
        logger.exception("无法连接数据库")
        raise DatabaseOperationError("无法连接数据库") from exc

    # 让查询结果能够使用 dict(row) 转换成字典。
    connection.row_factory = sqlite3.Row

    # SQLite默认可能不会强制检查外键，
    # 每次连接后都需要显式开启。
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        yield connection
    finally:
        connection.close()


def init_db(db_path: str | Path) -> None:
    """
    初始化业务数据库。

    【修改】
    昨天只创建 orders 表；
    今天增加 sessions、messages 和 tickets 三张表。
    """
    database_path = Path(db_path)

    try:
        database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open_database(database_path) as connection:
            # executescript 适合一次执行多条建表语句。
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE NOT NULL,
                    customer_id TEXT NOT NULL,
                    product TEXT NOT NULL,
                    amount REAL NOT NULL CHECK (amount >= 0),
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_name TEXT,
                    order_id TEXT,
                    problem_type TEXT,
                    description TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id)
                        REFERENCES sessions(session_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    order_id TEXT NOT NULL,
                    problem_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id)
                        REFERENCES sessions(session_id)
                        ON DELETE CASCADE
                );
                """
            )
            connection.commit()

    except (sqlite3.Error, OSError) as exc:
        logger.exception("初始化数据库失败")
        raise DatabaseOperationError("初始化数据库失败") from exc


def insert_order(
    order: dict[str, Any],
    db_path: str | Path,
) -> int:
    """插入订单，并返回数据库生成的主键。"""
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

    except sqlite3.Error as exc:
        logger.exception(
            "查询订单失败，order_id=%s",
            order_id,
        )
        raise DatabaseOperationError("查询订单失败") from exc

    return dict(row) if row is not None else None


# ==================== 以下为今天新增 ====================


def create_session(
    user_name: str | None,
    db_path: str | Path,
) -> dict[str, Any]:
    """
    创建一条客服会话。

    UUID比自增数字更适合作为公开接口中的会话标识：
    1. 不容易被顺序猜测；
    2. 多个服务节点也能独立生成；
    3. 不依赖数据库先插入再得到 ID。
    """
    session_id = str(uuid4())
    now = utc_now()

    session = {
        "session_id": session_id,
        "user_name": user_name,
        "order_id": None,
        "problem_type": None,
        "description": None,
        "status": "collecting_information",
        "created_at": now,
        "updated_at": now,
    }

    try:
        with open_database(db_path) as connection:
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id,
                    user_name,
                    order_id,
                    problem_type,
                    description,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    session["user_name"],
                    session["order_id"],
                    session["problem_type"],
                    session["description"],
                    session["status"],
                    session["created_at"],
                    session["updated_at"],
                ),
            )
            connection.commit()

    except sqlite3.Error as exc:
        logger.exception("创建客服会话失败")
        raise DatabaseOperationError("创建客服会话失败") from exc

    return session


def get_session_by_id(
    session_id: str,
    db_path: str | Path,
) -> dict[str, Any] | None:
    """按照 session_id 查询一条客服会话。"""
    try:
        with open_database(db_path) as connection:
            row = connection.execute(
                """
                SELECT
                    session_id,
                    user_name,
                    order_id,
                    problem_type,
                    description,
                    status,
                    created_at,
                    updated_at
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

    except sqlite3.Error as exc:
        logger.exception(
            "查询客服会话失败，session_id=%s",
            session_id,
        )
        raise DatabaseOperationError("查询客服会话失败") from exc

    return dict(row) if row is not None else None


def update_session(
    session_id: str,
    updates: dict[str, Any],
    db_path: str | Path,
) -> dict[str, Any] | None:
    """
    更新一条会话，并返回更新后的完整数据。

    SQL中的值继续使用 ? 参数化处理。

    列名不能使用 ? 占位，因此只允许白名单中的列进入 SQL，
    防止调用者构造任意列名。
    """
    allowed_columns = {
        "user_name",
        "order_id",
        "problem_type",
        "description",
        "status",
    }

    safe_updates = {
        key: value
        for key, value in updates.items()
        if key in allowed_columns
    }

    if not safe_updates:
        return get_session_by_id(session_id, db_path)

    safe_updates["updated_at"] = utc_now()

    # 这里只拼接经过白名单校验的列名。
    assignments = ", ".join(
        f"{column} = ?"
        for column in safe_updates
    )

    # 字段值依然全部通过参数化 SQL传入。
    parameters = [
        *safe_updates.values(),
        session_id,
    ]

    try:
        with open_database(db_path) as connection:
            cursor = connection.execute(
                f"""
                UPDATE sessions
                SET {assignments}
                WHERE session_id = ?
                """,
                parameters,
            )

            if cursor.rowcount == 0:
                return None

            row = connection.execute(
                """
                SELECT
                    session_id,
                    user_name,
                    order_id,
                    problem_type,
                    description,
                    status,
                    created_at,
                    updated_at
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

            connection.commit()

    except sqlite3.Error as exc:
        logger.exception(
            "更新客服会话失败，session_id=%s",
            session_id,
        )
        raise DatabaseOperationError("更新客服会话失败") from exc

    return dict(row) if row is not None else None


def insert_message(
    session_id: str,
    role: str,
    content: str,
    db_path: str | Path,
) -> dict[str, Any]:
    """保存一条会话消息并返回消息记录。"""
    created_at = utc_now()

    try:
        with open_database(db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO messages (
                    session_id,
                    role,
                    content,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content,
                    created_at,
                ),
            )
            connection.commit()

            message_id = int(cursor.lastrowid)

    except sqlite3.Error as exc:
        logger.exception(
            "保存会话消息失败，session_id=%s",
            session_id,
        )
        raise DatabaseOperationError("保存会话消息失败") from exc

    return {
        "message_id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": created_at,
    }


def list_messages_by_session(
    session_id: str,
    db_path: str | Path,
) -> list[dict[str, Any]]:
    """按照创建顺序查询某个会话的全部消息。"""
    try:
        with open_database(db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    message_id,
                    session_id,
                    role,
                    content,
                    created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY message_id
                """,
                (session_id,),
            ).fetchall()

    except sqlite3.Error as exc:
        logger.exception(
            "查询会话消息失败，session_id=%s",
            session_id,
        )
        raise DatabaseOperationError("查询会话消息失败") from exc

    return [dict(row) for row in rows]