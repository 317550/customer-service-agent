"""
为什么新增 Service层？

如果把所有逻辑都塞进路由：

@app.patch(...)
def update_session():
    # 查数据库
    # 清洗字符串
    # 判断字段
    # 修改状态
    # 处理响应

路由会越来越长，也难以单独测试业务规则。

现在职责分成：

routes.py    HTTP请求与状态码
services.py 业务状态判断
database.py 数据持久化
schemas.py  输入输出契约

这是实际项目常见的职责分离。
"""
from typing import Any

from app.schemas import SessionResponse, SessionStatus


# 一个会话进入自动处理前必须具备的字段。
REQUIRED_SESSION_FIELDS = (
    "user_name",
    "order_id",
    "problem_type",
    "description",
)


def normalize_optional_text(
    value: str | None,
) -> str | None:
    """
    标准化可选文本。

    None继续保持为 None；
    删除字符串两端空格；
    只有空格的字符串转换成 None。
    """
    if value is None:
        return None

    normalized = value.strip()
    return normalized if normalized else None


def normalize_session_updates(
    updates: dict[str, Any],
) -> dict[str, Any]:
    """
    标准化 PATCH请求中的文本字段。

    Pydantic负责校验数据类型；
    Service层负责业务数据清洗。
    """
    normalized: dict[str, Any] = {}

    for key, value in updates.items():
        if isinstance(value, str):
            normalized[key] = normalize_optional_text(value)
        else:
            normalized[key] = value

    return normalized


def get_missing_fields(
    session: dict[str, Any],
) -> list[str]:
    """
    计算当前会话缺失的必要字段。

    不把 missing_fields 保存到数据库，因为它可以由当前状态推导，
    避免数据库中的状态和缺失字段列表发生不一致。
    """
    missing_fields: list[str] = []

    for field_name in REQUIRED_SESSION_FIELDS:
        value = session.get(field_name)

        if value is None:
            missing_fields.append(field_name)
            continue

        if isinstance(value, str) and not value.strip():
            missing_fields.append(field_name)

    return missing_fields


def determine_session_status(
    session: dict[str, Any],
) -> str:
    """
    根据必要信息是否完整决定会话状态。

    今天先使用确定性规则；
    明天 LangGraph会根据这个结果进行条件路由。
    """
    if get_missing_fields(session):
        return SessionStatus.COLLECTING_INFORMATION.value

    return SessionStatus.READY_FOR_PROCESSING.value


def build_session_response(
    session: dict[str, Any],
) -> SessionResponse:
    """
    把数据库记录转换成 API响应模型，
    并动态补充 missing_fields。
    """
    return SessionResponse(
        **session,
        missing_fields=get_missing_fields(session),
    )