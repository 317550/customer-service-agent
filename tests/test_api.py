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
    每次测试使用独立的临时数据库，
    不读取或修改开发环境的 orders.db。
    """
    database_path = tmp_path / "test_orders.db"
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