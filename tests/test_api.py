from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.database import (
    DatabaseOperationError,
    insert_order,
)
from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    """
    每个测试使用独立的临时数据库。

    TestClient进入上下文时会执行 FastAPI lifespan，
    从而自动调用 init_db() 创建所有数据表。
    """
    database_path = tmp_path / "test_database.db"
    test_app = create_app(database_path)

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


def create_test_session(
    client: TestClient,
    user_name: str = "张三",
) -> dict:
    """
    测试辅助函数。

    多个测试都需要先创建会话，所以统一封装，
    避免重复发送相同请求。
    """
    response = client.post(
        "/sessions",
        json={"user_name": user_name},
    )

    assert response.status_code == 201
    return response.json()


# ==================== 昨天的4个测试 ====================


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_existing_order(client: TestClient) -> None:
    response = client.get("/orders/ORD001")

    assert response.status_code == 200
    assert response.json()["order_id"] == "ORD001"
    assert response.json()["amount"] == 299.0


def test_get_missing_order(client: TestClient) -> None:
    response = client.get("/orders/NOT-EXIST")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "订单不存在：NOT-EXIST"
    }


def test_database_failure_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_database_error(*args, **kwargs):
        raise DatabaseOperationError("模拟数据库故障")

    monkeypatch.setattr(
        "app.routes.get_order_by_id",
        raise_database_error,
    )

    response = client.get("/orders/ORD001")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "订单服务暂时不可用"
    }


# ==================== 今天新增的6个测试 ====================


def test_create_session(client: TestClient) -> None:
    response = client.post(
        "/sessions",
        json={"user_name": " 张三 "},
    )

    assert response.status_code == 201

    body = response.json()

    # Service层应该删除姓名两端的空格。
    assert body["user_name"] == "张三"
    assert body["status"] == "collecting_information"
    assert body["missing_fields"] == [
        "order_id",
        "problem_type",
        "description",
    ]
    assert body["session_id"]


def test_get_existing_session(
    client: TestClient,
) -> None:
    session = create_test_session(client)

    response = client.get(
        f"/sessions/{session['session_id']}"
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == session["session_id"]
    assert response.json()["user_name"] == "张三"


def test_get_missing_session_returns_404(
    client: TestClient,
) -> None:
    response = client.get(
        "/sessions/not-existing-session"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "会话不存在：not-existing-session"
    }


def test_partial_information_keeps_collecting_status(
    client: TestClient,
) -> None:
    session = create_test_session(client)

    response = client.patch(
        f"/sessions/{session['session_id']}",
        json={
            "order_id": "ORD001",
            "problem_type": "refund",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "collecting_information"
    assert body["missing_fields"] == ["description"]


def test_complete_information_becomes_ready(
    client: TestClient,
) -> None:
    session = create_test_session(client)

    first_response = client.patch(
        f"/sessions/{session['session_id']}",
        json={
            "order_id": "ORD001",
            "problem_type": "refund",
        },
    )

    assert first_response.status_code == 200
    assert (
        first_response.json()["status"]
        == "collecting_information"
    )

    second_response = client.patch(
        f"/sessions/{session['session_id']}",
        json={
            "description": " 商品损坏，希望申请退款 ",
        },
    )

    assert second_response.status_code == 200

    body = second_response.json()

    assert body["description"] == "商品损坏，希望申请退款"
    assert body["status"] == "ready_for_processing"
    assert body["missing_fields"] == []


def test_create_and_list_messages(
    client: TestClient,
) -> None:
    session = create_test_session(client)
    session_id = session["session_id"]

    create_response = client.post(
        f"/sessions/{session_id}/messages",
        json={
            "content": " 我的商品损坏了 ",
        },
    )

    assert create_response.status_code == 201
    assert create_response.json()["role"] == "user"
    assert (
        create_response.json()["content"]
        == "我的商品损坏了"
    )

    list_response = client.get(
        f"/sessions/{session_id}/messages"
    )

    assert list_response.status_code == 200

    messages = list_response.json()

    assert len(messages) == 1
    assert messages[0]["session_id"] == session_id
    assert messages[0]["content"] == "我的商品损坏了"