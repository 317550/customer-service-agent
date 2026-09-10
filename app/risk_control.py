"""高风险操作判断。

风险控制使用确定性代码，而不是交给大模型自由决定。
这样规则可审计、可测试，也便于未来接入企业审批流程。
"""

from app.schemas import ProblemType


HIGH_RISK_KEYWORDS = (
    # 即使模型把“商品损坏并要求退款”分类成 quality，
    # 只要原始问题描述中包含退款意图，仍然必须转人工。
    "退款",
    "退货",
    "退钱",

    # 投诉、赔偿和敏感信息同样属于高风险场景。
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
    """
    使用“结构化分类 + 原始问题关键词”双重判断。

    不能只相信大模型的 problem_type，因为模型可能将
    “商品损坏，我要求退款”分类成 quality。
    """
    if problem_type == ProblemType.REFUND.value:
        return True

    normalized_description = (description or "").strip()

    return any(
        keyword in normalized_description
        for keyword in HIGH_RISK_KEYWORDS
    )
