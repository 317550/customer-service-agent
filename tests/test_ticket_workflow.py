"""人工工单闭环的端到端测试。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.database import insert_order
from app.extraction import RuleBasedInformationExtractor
from app.main import create_app


ADMIN_HEADERS = {"X-Admin-Token": "test-admin-secret"}


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    database_path = tmp_path / "test_tickets.db"
    application = create_app(
        database_path=database_path,
        information_extractor=RuleBasedInformationExtractor(),
        admin_api_key="test-admin-secret",
    )
    with TestClient(application) as test_client:
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


def create_session(client: TestClient) -> str:
    response = client.post("/sessions", json={"user_name": "王五"})
    assert response.status_code == 201
    return response.json()["session_id"]


def create_refund_ticket(client: TestClient, session_id: str) -> dict:
    response = client.post(
        f"/sessions/{session_id}/runs",
        json={"message": "订单ORD001已经损坏，我需要退款"},
    )
    assert response.status_code == 200
    return response.json()


def test_valid_refund_creates_pending_ticket(client: TestClient) -> None:
    session_id = create_session(client)
    result = create_refund_ticket(client, session_id)

    assert result["action"] == "handoff_to_human"
    assert result["session_status"] == "waiting_for_human"
    assert result["ticket"]["status"] == "pending_review"
    assert result["ticket"]["order_id"] == "ORD001"
    assert f"#{result['ticket']['ticket_id']}" in result["reply"]


def test_unknown_order_does_not_create_ticket(client: TestClient) -> None:
    session_id = create_session(client)
    response = client.post(
        f"/sessions/{session_id}/runs",
        json={"message": "订单ORD999已经损坏，我需要退款"},
    )

    assert response.status_code == 200
    assert response.json()["action"] == "ask_user"
    ticket_response = client.get(f"/sessions/{session_id}/ticket")
    assert ticket_response.status_code == 404


def test_repeated_run_is_idempotent(client: TestClient) -> None:
    session_id = create_session(client)
    first = create_refund_ticket(client, session_id)
    second = create_refund_ticket(client, session_id)

    assert first["ticket"]["ticket_id"] == second["ticket"]["ticket_id"]


def test_user_can_query_ticket_by_session(client: TestClient) -> None:
    session_id = create_session(client)
    created = create_refund_ticket(client, session_id)["ticket"]

    response = client.get(f"/sessions/{session_id}/ticket")
    assert response.status_code == 200
    assert response.json()["ticket_id"] == created["ticket_id"]


def test_admin_can_query_ticket_by_id(client: TestClient) -> None:
    session_id = create_session(client)
    ticket = create_refund_ticket(client, session_id)["ticket"]

    response = client.get(
        f"/tickets/{ticket['ticket_id']}",
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == session_id


def test_ticket_admin_endpoint_requires_token(client: TestClient) -> None:
    session_id = create_session(client)
    ticket = create_refund_ticket(client, session_id)["ticket"]

    response = client.patch(
        f"/tickets/{ticket['ticket_id']}/status",
        json={"status": "approved"},
    )
    assert response.status_code == 401


def test_valid_ticket_state_transitions(client: TestClient) -> None:
    session_id = create_session(client)
    ticket = create_refund_ticket(client, session_id)["ticket"]
    ticket_id = ticket["ticket_id"]

    approved = client.patch(
        f"/tickets/{ticket_id}/status",
        json={"status": "approved"},
        headers=ADMIN_HEADERS,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    resolved = client.patch(
        f"/tickets/{ticket_id}/status",
        json={"status": "resolved"},
        headers=ADMIN_HEADERS,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    session = client.get(f"/sessions/{session_id}")
    assert session.status_code == 200
    assert session.json()["status"] == "completed"


def test_invalid_ticket_state_transition_returns_409(
    client: TestClient,
) -> None:
    session_id = create_session(client)
    ticket = create_refund_ticket(client, session_id)["ticket"]

    response = client.patch(
        f"/tickets/{ticket['ticket_id']}/status",
        json={"status": "resolved"},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 409
    assert "pending_review" in response.json()["detail"]


def test_normal_logistics_query_does_not_create_ticket(
    client: TestClient,
) -> None:
    session_id = create_session(client)
    response = client.post(
        f"/sessions/{session_id}/runs",
        json={"message": "查询订单ORD001的物流，为什么还没收到"},
    )

    assert response.status_code == 200
    assert response.json()["action"] == "query_order"
    assert response.json()["ticket"] is None
    assert client.get(f"/sessions/{session_id}/ticket").status_code == 404
