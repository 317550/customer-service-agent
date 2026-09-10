"""工单领域规则：把状态转换约束集中在一个位置。"""

from pathlib import Path
from typing import Any

from app.database import get_ticket_by_id, set_ticket_status
from app.schemas import TicketStatus


class TicketNotFoundError(LookupError):
    """工单不存在。"""


class InvalidTicketTransitionError(ValueError):
    """请求的工单状态转换不符合业务流程。"""


ALLOWED_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.PENDING_REVIEW: {
        TicketStatus.APPROVED,
        TicketStatus.REJECTED,
    },
    TicketStatus.APPROVED: {TicketStatus.RESOLVED},
    TicketStatus.REJECTED: set(),
    TicketStatus.RESOLVED: set(),
}


def transition_ticket(
    ticket_id: int,
    target_status: TicketStatus,
    db_path: str | Path,
) -> dict[str, Any]:
    """校验状态机并持久化新的工单状态。"""
    ticket = get_ticket_by_id(ticket_id, db_path)
    if ticket is None:
        raise TicketNotFoundError(ticket_id)

    current_status = TicketStatus(ticket["status"])
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise InvalidTicketTransitionError(
            f"不允许从 {current_status.value} 转换为 {target_status.value}"
        )

    updated_ticket = set_ticket_status(
        ticket_id,
        target_status.value,
        db_path,
        # 工单拒绝或完成后，本次客服会话不再等待人工处理。
        session_status=(
            "completed"
            if target_status in {
                TicketStatus.REJECTED,
                TicketStatus.RESOLVED,
            }
            else None
        ),
    )
    if updated_ticket is None:
        raise TicketNotFoundError(ticket_id)
    return updated_ticket
