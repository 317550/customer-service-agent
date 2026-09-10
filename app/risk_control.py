"""高风险操作判断。

风险控制使用确定性代码，而不是交给大模型自由决定。
这样规则可审计、可测试，也便于未来接入企业审批流程。
"""

from app.schemas import ProblemType


HIGH_RISK_KEYWORDS = (
    "投诉",
    "赔偿",
    "银行卡",
    "密码",
    "账户安全",
    "身份证",
)


def requires_human_review(
    problem_type: str | None,
    description: str | None,
) -> bool:
    """退款以及包含敏感关键词的问题必须交给人工确认。"""
    if problem_type == ProblemType.REFUND.value:
        return True

    normalized_description = (description or "").strip()
    return any(
        keyword in normalized_description
        for keyword in HIGH_RISK_KEYWORDS
    )
