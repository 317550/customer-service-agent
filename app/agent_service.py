"""带状态客服 Agent 的单轮编排服务。"""

from pathlib import Path
from typing import Any

from app.database import (
    get_or_create_ticket,
    get_session_by_id,
    insert_message,
    update_session,
)
from app.extraction import (
    InformationExtractor,
    default_information_extractor,
)
from app.risk_control import requires_human_review
from app.schemas import (
    AgentAction,
    AgentRunResponse,
    OrderResponse,
    SessionStatus,
    TicketResponse,
)
from app.services import (
    get_missing_fields,
    normalize_session_updates,
)
from app.tools import query_order_tool


class AgentSessionNotFoundError(LookupError):
    """执行 Agent 时找不到目标会话。"""


FIELD_LABELS = {
    "user_name": "姓名",
    "order_id": "订单号",
    "problem_type": "问题类型",
    "description": "问题描述",
}


def _build_missing_fields_reply(missing_fields: list[str]) -> str:
    labels = [FIELD_LABELS[field] for field in missing_fields]
    return f"为了继续处理，请补充：{'、'.join(labels)}。"


def _persist_agent_result(
    session_id: str,
    updates: dict[str, Any],
    reply: str,
    db_path: str | Path,
) -> dict[str, Any]:
    """统一保存会话新状态和 Agent 回复，避免各分支重复代码。"""
    updated_session = update_session(
        session_id=session_id,
        updates=updates,
        db_path=db_path,
    )

    # 前面查询成功后，记录仍可能被其他请求删除，因此不能假定一定存在。
    if updated_session is None:
        raise AgentSessionNotFoundError(session_id)

    insert_message(
        session_id=session_id,
        role="assistant",
        content=reply,
        db_path=db_path,
    )
    return updated_session


def run_agent(
    session_id: str,
    message: str,
    db_path: str | Path,
    extractor: InformationExtractor = default_information_extractor,
) -> AgentRunResponse:
    """
    执行一轮客服 Agent。

    编排原则：
    1. 提取器只负责把自然语言变成结构化字段；
    2. Python 代码负责缺失字段、风险和工具路由；
    3. 所有用户消息、Agent 回复和会话状态都落入 SQLite。
    """
    session = get_session_by_id(session_id, db_path)
    if session is None:
        raise AgentSessionNotFoundError(session_id)

    normalized_message = message.strip()
    insert_message(
        session_id=session_id,
        role="user",
        content=normalized_message,
        db_path=db_path,
    )

    extracted = extractor.extract(normalized_message)
    extracted_updates = extracted.model_dump(
        mode="json",
        exclude_none=True,
    )
    extracted_updates = normalize_session_updates(extracted_updates)

    candidate_session = {
        **session,
        **extracted_updates,
    }
    missing_fields = get_missing_fields(candidate_session)

    # 分支一：必要字段尚未收集完整，Agent 继续追问。
    if missing_fields:
        reply = _build_missing_fields_reply(missing_fields)
        updated_session = _persist_agent_result(
            session_id,
            {
                **extracted_updates,
                "status": SessionStatus.COLLECTING_INFORMATION.value,
            },
            reply,
            db_path,
        )
        return AgentRunResponse(
            session_id=session_id,
            reply=reply,
            action=AgentAction.ASK_USER,
            session_status=updated_session["status"],
            missing_fields=get_missing_fields(updated_session),
            requires_human=False,
        )

    # 信息完整后先验证订单。高风险请求同样不能绕过订单校验，
    # 否则伪造或输错的订单号也会制造无效人工工单。
    order = query_order_tool(
        candidate_session["order_id"],
        db_path,
    )

    if order is None:
        # 无效订单号不能继续留作“已验证状态”，清空后请用户重新提供。
        reply = "没有查询到该订单，请核对并重新提供订单号。"
        updated_session = _persist_agent_result(
            session_id,
            {
                **extracted_updates,
                "order_id": None,
                "status": SessionStatus.COLLECTING_INFORMATION.value,
            },
            reply,
            db_path,
        )
        return AgentRunResponse(
            session_id=session_id,
            reply=reply,
            action=AgentAction.ASK_USER,
            session_status=updated_session["status"],
            missing_fields=get_missing_fields(updated_session),
            requires_human=False,
        )

    # 分支二：有效订单的退款、投诉或敏感操作创建人工工单。
    if requires_human_review(
        candidate_session.get("problem_type"),
        candidate_session.get("description"),
    ):
        ticket = get_or_create_ticket(
            session_id=session_id,
            order_id=candidate_session["order_id"],
            problem_type=candidate_session["problem_type"],
            description=candidate_session["description"],
            db_path=db_path,
        )
        reply = (
            "该请求需要人工客服确认，已创建工单 "
            f"#{ticket['ticket_id']}，您可以随时查询处理进度。"
        )
        updated_session = _persist_agent_result(
            session_id,
            {
                **extracted_updates,
                "status": SessionStatus.WAITING_FOR_HUMAN.value,
            },
            reply,
            db_path,
        )
        return AgentRunResponse(
            session_id=session_id,
            reply=reply,
            action=AgentAction.HANDOFF_TO_HUMAN,
            session_status=updated_session["status"],
            missing_fields=[],
            requires_human=True,
            ticket=TicketResponse.model_validate(ticket),
        )

    # 分支三：普通问题返回前面已验证过的订单结果。
    reply = (
        f"已查询到订单 {order['order_id']}："
        f"商品为{order['product']}，当前状态为 {order['status']}。"
    )
    updated_session = _persist_agent_result(
        session_id,
        {
            **extracted_updates,
            "status": SessionStatus.COMPLETED.value,
        },
        reply,
        db_path,
    )
    return AgentRunResponse(
        session_id=session_id,
        reply=reply,
        action=AgentAction.QUERY_ORDER,
        session_status=updated_session["status"],
        missing_fields=[],
        requires_human=False,
        order=OrderResponse.model_validate(order),
    )
