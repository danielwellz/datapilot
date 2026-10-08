from datetime import UTC, datetime

import pytest
from flask.testing import FlaskClient

from app.models import OrderChannel, OrderStatus
from tests.factories import create_customer, create_order, create_product
from tests.integration.conftest import QueryCounter


def url(order_id: int | str) -> str:
    return f"/api/orders/{order_id}"


def test_get_order_returns_the_order_with_its_customer_and_items(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    ana = create_customer(
        name="Ana Lima",
        email="ana@example.com",
        country="PT",
        signed_up_at=datetime(2024, 5, 2, 8, 15, tzinfo=UTC),
    )
    lamp = create_product(name="Desk Lamp", category="Home", price="45.05")
    bottle = create_product(name="Trail Water Bottle", category="Sports", price="19.90")
    order = create_order(
        ana,
        [(bottle, 3), (lamp, 1)],
        status=OrderStatus.CANCELLED,
        channel=OrderChannel.MARKETPLACE,
        created_at=datetime(2025, 6, 1, 18, 0, 5, tzinfo=UTC),
    )

    response = client.get(url(order.id), headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "id": order.id,
        "status": "cancelled",
        "channel": "marketplace",
        "total": "104.75",
        "created_at": "2025-06-01T18:00:05Z",
        "customer": {
            "id": ana.id,
            "name": "Ana Lima",
            "email": "ana@example.com",
            "country": "PT",
            "signed_up_at": "2024-05-02T08:15:00Z",
        },
        # Ordered by product id: the lamp was created first.
        "items": [
            {
                "product": {"id": lamp.id, "name": "Desk Lamp", "category": "Home"},
                "quantity": 1,
                "unit_price": "45.05",
                "line_total": "45.05",
            },
            {
                "product": {"id": bottle.id, "name": "Trail Water Bottle", "category": "Sports"},
                "quantity": 3,
                "unit_price": "19.90",
                "line_total": "59.70",
            },
        ],
    }


def test_get_order_for_a_missing_id_returns_404(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    response = client.get(url(987_654_321), headers=auth_headers)

    assert response.status_code == 404
    error = response.get_json()["error"]
    assert error["code"] == "not_found"
    assert error["message"] == "The order does not exist."
    assert error["details"] == [{"order_id": 987_654_321}]


@pytest.mark.parametrize("order_id", ["0", "-1", "abc", "1.5", str(2**63)])
def test_get_order_for_an_id_that_cannot_exist_returns_404(
    client: FlaskClient, auth_headers: dict[str, str], order_id: str
) -> None:
    response = client.get(url(order_id), headers=auth_headers)

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_get_order_requires_an_access_token(client: FlaskClient) -> None:
    order = create_order(create_customer(), [(create_product(), 1)])

    response = client.get(url(order.id))

    assert response.status_code == 401


@pytest.mark.parametrize("item_count", [1, 10])
def test_get_order_runs_three_queries_whatever_the_number_of_items(
    client: FlaskClient,
    auth_headers: dict[str, str],
    count_queries: QueryCounter,
    item_count: int,
) -> None:
    products = [create_product(name=f"Product {index}") for index in range(item_count)]
    # Read before counting: the committed instance would reload itself on access.
    order_id = create_order(create_customer(), [(product, 1) for product in products]).id

    with count_queries() as statements:
        response = client.get(url(order_id), headers=auth_headers)

    assert len(response.get_json()["items"]) == item_count
    # The token's user, the order with its customer, its items with their products.
    assert len(statements) == 3
    assert "FROM users" in statements[0]
    assert "JOIN customers" in statements[1]
    assert "FROM order_items JOIN products" in statements[2]
