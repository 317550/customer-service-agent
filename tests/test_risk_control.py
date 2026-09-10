"""风险控制规则测试。"""

from app.risk_control import requires_human_review


def test_refund_keyword_requires_human_when_model_misclassifies() -> None:
    """
    即使模型把问题误分类为 quality，
    原始描述包含退款意图时仍必须转人工。
    """
    result = requires_human_review(
        problem_type="quality",
        description="收到的商品已经损坏，我要求退款",
    )

    assert result is True


def test_normal_logistics_query_does_not_require_human() -> None:
    """普通物流查询应当继续由 Agent 自动处理。"""
    result = requires_human_review(
        problem_type="logistics",
        description="查询订单什么时候送到",
    )

    assert result is False