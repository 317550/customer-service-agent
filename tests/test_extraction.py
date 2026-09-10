"""DeepSeek 结构化提取和降级机制测试。"""

import httpx
import pytest

from app.extraction import (
    DeepSeekInformationExtractor,
    FallbackInformationExtractor,
    InformationExtractionError,
    RuleBasedInformationExtractor,
)


class FakeHTTPResponse:
    """只实现被提取器使用的响应方法。"""

    def __init__(self, body: dict) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.body


def build_deepseek_extractor() -> DeepSeekInformationExtractor:
    return DeepSeekInformationExtractor(
        api_key="test-key",
        base_url="https://example.com",
        model="test-model",
    )


def test_deepseek_extractor_parses_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*args, **kwargs) -> FakeHTTPResponse:
        return FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"user_name":"李四",'
                                '"order_id":"ORD001",'
                                '"problem_type":"logistics",'
                                '"description":"查询物流"}'
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.extraction.httpx.post", fake_post)

    result = build_deepseek_extractor().extract("查询订单物流")

    assert result.user_name == "李四"
    assert result.order_id == "ORD001"
    assert result.problem_type == "logistics"


def test_deepseek_invalid_json_raises_extraction_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(*args, **kwargs) -> FakeHTTPResponse:
        return FakeHTTPResponse(
            {
                "choices": [
                    {"message": {"content": "不是JSON"}}
                ]
            }
        )

    monkeypatch.setattr("app.extraction.httpx.post", fake_post)

    with pytest.raises(InformationExtractionError):
        build_deepseek_extractor().extract("测试消息")


def test_http_failure_falls_back_to_rule_extractor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_network_error(*args, **kwargs):
        raise httpx.ConnectError("模拟网络故障")

    monkeypatch.setattr(
        "app.extraction.httpx.post",
        raise_network_error,
    )

    extractor = FallbackInformationExtractor(
        primary=build_deepseek_extractor(),
        fallback=RuleBasedInformationExtractor(),
    )

    result = extractor.extract("我叫王五，订单号ORD001，需要退款")

    assert result.user_name == "王五"
    assert result.order_id == "ORD001"
    assert result.problem_type == "refund"
