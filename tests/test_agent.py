"""带状态客服 Agent 的端到端 API 测试。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.database import (
    DatabaseOperationError,
    insert_order,
)
from app.extraction import RuleBasedInformationExtractor
from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    database_path = tmp_path / "test_agent.db"
    # 明确注入规则提取器，保证测试不会读取本地 .env，
    # 也不会调用真实 DeepSeek API 或产生费用。
    test_app = create_app(
        database_path,
        information_extractor=RuleBasedInformationExtractor(),
    )

    with TestClient(test_app) as test_client:
        insert_order(
            {
                "order_id": "ORD001",
                "customer_id": "C001",
                "product": "机械键盘",
                "amount": 299.0,
                "status": "shipped",
            },
            database_path,
        )
        yield test_client


def create_session(
    client: TestClient,
    user_name: str | None = "张三",
) -> str:
    response = client.post(
        "/sessions",
        json={"user_name": user_name},
    )
    assert response.status_code == 201
    return response.json()["session_id"]


def test_missing_session_returns_404(client: TestClient) -> None:
    response = client.post(
        "/sessions/not-existing/runs",
        json={"message": "查询订单ORD001的物流"},
    )
    assert response.status_code == 404


def test_blank_message_returns_422(client: TestClient) -> None:
    session_id = create_session(client)
    response = client.post(
        f"/sessions/{session_id}/runs",
        json={"message": "   "},
    )
    assert response.status_code == 422


def test_missing_information_asks_user(client: TestClient) -> None:
    session_id = create_session(client, user_name=None)
    response = client.post(
        f"/sessions/{session_id}/runs",
        json={"message": "我的订单有问题"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "ask_user"
    assert body["session_status"] == "collecting_information"
    assert body["missing_fields"] == ["user_name", "order_id"]


def test_complete_information_queries_order(client: TestClient) -> None:
    session_id = create_session(client)
    response = client.post(
        f"/sessions/{session_id}/runs",
        json={
            "message": "订单号ORD001，我想查询物流，为什么还没收到"
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "query_order"
    assert body["session_status"] == "completed"
    assert body["requires_human"] is False
    assert body["order"]["order_id"] == "ORD001"


def test_refund_request_is_handed_to_human(client: TestClient) -> None:
    session_id = create_session(client)
    response = client.post(
        f"/sessions/{session_id}/runs",
        json={"message": "订单ORD001已经损坏，我需要退款"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "handoff_to_human"
    assert body["session_status"] == "waiting_for_human"
    assert body["requires_human"] is True


def test_unknown_order_asks_for_new_order_id(client: TestClient) -> None:
    session_id = create_session(client)
    response = client.post(
        f"/sessions/{session_id}/runs",
        json={"message": "查询订单ORD999的物流，为什么没有收到"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "ask_user"
    assert body["missing_fields"] == ["order_id"]
    assert body["order"] is None
    assert body["reply"] == "没有查询到该订单，请核对并重新提供订单号。"


def test_user_and_assistant_messages_are_persisted(
    client: TestClient,
) -> None:
    session_id = create_session(client)
    run_response = client.post(
        f"/sessions/{session_id}/runs",
        json={
            "message": "订单ORD001的物流怎么样，我还没有收到"
        },
    )
    assert run_response.status_code == 200

    messages_response = client.get(
        f"/sessions/{session_id}/messages"
    )
    assert messages_response.status_code == 200

    messages = messages_response.json()
    assert [message["role"] for message in messages] == [
        "user",
        "assistant",
    ]


def test_multi_turn_session_recovers_previous_state(
    client: TestClient,
) -> None:
    """
    第一轮只描述问题，第二轮补充姓名和订单号。

    该测试证明 Agent 不要求用户一次性提供全部信息，
    而是能够从 SQLite 恢复前一轮已经收集的状态。
    """
    session_id = create_session(
        client,
        user_name=None,
    )

    first_response = client.post(
        f"/sessions/{session_id}/runs",
        json={
            "message": "我的订单有物流问题，一直没有收到"
        },
    )

    assert first_response.status_code == 200

    first_body = first_response.json()

    assert first_body["action"] == "ask_user"
    assert first_body["session_status"] == "collecting_information"
    assert first_body["missing_fields"] == [
        "user_name",
        "order_id",
    ]

    second_response = client.post(
        f"/sessions/{session_id}/runs",
        json={
            "message": "我叫李四，订单号是ORD001"
        },
    )

    assert second_response.status_code == 200

    second_body = second_response.json()

    assert second_body["action"] == "query_order"
    assert second_body["session_status"] == "completed"
    assert second_body["missing_fields"] == []
    assert second_body["order"]["order_id"] == "ORD001"

    # 再通过查询接口验证最终状态确实已经落入数据库，
    # 而不只是存在于 run_agent() 的局部变量中。
    session_response = client.get(
        f"/sessions/{session_id}"
    )

    assert session_response.status_code == 200

    session = session_response.json()

    assert session["user_name"] == "李四"
    assert session["order_id"] == "ORD001"
    assert session["problem_type"] == "logistics"
    assert session["status"] == "completed"


def test_agent_database_failure_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Agent内部发生数据库故障时，不向客户端泄露SQL或堆栈，
    而是返回稳定的503响应。
    """

    def raise_database_error(*args, **kwargs):
        raise DatabaseOperationError("模拟数据库故障")

    monkeypatch.setattr(
        "app.routes.run_agent",
        raise_database_error,
    )

    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/runs",
        json={
            "message": "查询订单ORD001的物流"
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "服务暂时不可用"
    }

