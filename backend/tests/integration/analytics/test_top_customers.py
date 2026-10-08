from dataclasses import dataclass

import pytest
from flask.testing import FlaskClient

from app.models import OrderStatus
from tests.factories import create_customer
from tests.integration.analytics.conftest import at, sale
from tests.integration.conftest import QueryCounter

URL = "/api/analytics/top-customers"


@dataclass(frozen=True)
class Ref:
    """What the assertions need, read before requests detach the model."""

    id: int
    name: str
    country: str


@pytest.fixture
def customers() -> dict[str, Ref]:
    """Today is 2026-03-15; the default 365 days are 2025-03-15 to 2026-03-14.

    Paid revenue in the period: US: Ana 300, Ben 300, Cleo 150, Dan 50;
    DE: Eva 80. Finn (DE) only has a refund; Gus (GB) only orders today.
    """
    people = {
        name: create_customer(name=name, country=country)
        for name, country in [
            ("Ana", "US"),
            ("Ben", "US"),
            ("Cleo", "US"),
            ("Dan", "US"),
            ("Eva", "DE"),
            ("Finn", "DE"),
            ("Gus", "GB"),
        ]
    }
    sale(people["Ana"], "200.00", at("2025-06-01"))
    sale(people["Ana"], "100.00", at("2026-03-14", "23:59:59"))
    sale(people["Ben"], "300.00", at("2025-09-01"))
    sale(people["Cleo"], "150.00", at("2025-03-15", "00:00:00"))
    sale(people["Dan"], "50.00", at("2025-12-24"))
    # The day before the period starts.
    sale(people["Dan"], "1000.00", at("2025-03-14", "23:59:59"))
    sale(people["Eva"], "80.00", at("2026-01-02"))
    sale(people["Finn"], "500.00", at("2026-01-03"), status=OrderStatus.REFUNDED)
    sale(people["Gus"], "999.00", at("2026-03-15", "00:00:00"))
    return {name: Ref(c.id, c.name, c.country) for name, c in people.items()}


def item(customer: Ref, rank: int, revenue: str, orders: int, last: str) -> dict[str, object]:
    return {
        "country": customer.country,
        "rank": rank,
        "customer_id": customer.id,
        "name": customer.name,
        "revenue": revenue,
        "orders": orders,
        "last_order_at": last,
    }


def test_top_customers_are_ranked_within_each_country_with_ties_sharing_a_rank(
    client: FlaskClient, auth_headers: dict[str, str], customers: dict[str, Ref]
) -> None:
    response = client.get(URL, headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json()["items"] == [
        item(customers["Eva"], 1, "80.00", 1, "2026-01-02T12:00:00Z"),
        # Ana and Ben tie on 300.00; dense ranking gives Cleo rank 2, not 3.
        item(customers["Ana"], 1, "300.00", 2, "2026-03-14T23:59:59Z"),
        item(customers["Ben"], 1, "300.00", 1, "2025-09-01T12:00:00Z"),
        item(customers["Cleo"], 2, "150.00", 1, "2025-03-15T00:00:00Z"),
        item(customers["Dan"], 3, "50.00", 1, "2025-12-24T12:00:00Z"),
    ]


def test_limit_is_the_worst_rank_so_ties_can_return_more_customers(
    client: FlaskClient, auth_headers: dict[str, str], customers: dict[str, Ref]
) -> None:
    body = client.get(URL, query_string={"limit": 2}, headers=auth_headers).get_json()

    assert [(row["name"], row["rank"]) for row in body["items"]] == [
        ("Eva", 1),
        ("Ana", 1),
        ("Ben", 1),
        ("Cleo", 2),
    ]


def test_country_filter_accepts_either_case(
    client: FlaskClient, auth_headers: dict[str, str], customers: dict[str, Ref]
) -> None:
    body = client.get(
        URL, query_string={"country": "us", "limit": 1}, headers=auth_headers
    ).get_json()

    assert [row["name"] for row in body["items"]] == ["Ana", "Ben"]


def test_a_shorter_period_ranks_only_its_own_orders(
    client: FlaskClient, auth_headers: dict[str, str], customers: dict[str, Ref]
) -> None:
    # 2026-03-14 alone: only Ana's last order.
    body = client.get(URL, query_string={"days": 1}, headers=auth_headers).get_json()

    assert body["items"] == [item(customers["Ana"], 1, "100.00", 1, "2026-03-14T23:59:59Z")]


def test_a_country_without_paid_orders_returns_no_customers(
    client: FlaskClient, auth_headers: dict[str, str], customers: dict[str, Ref]
) -> None:
    body = client.get(URL, query_string={"country": "GB"}, headers=auth_headers).get_json()

    assert body == {"items": []}


@pytest.mark.parametrize(
    "query",
    [{"limit": 0}, {"limit": 101}, {"days": 0}, {"days": 366}, {"country": "USA"}, {"x": 1}],
)
def test_top_customers_rejects_invalid_query_parameters(
    client: FlaskClient, auth_headers: dict[str, str], query: dict[str, object]
) -> None:
    assert client.get(URL, query_string=query, headers=auth_headers).status_code == 422


def test_top_customers_requires_an_access_token(client: FlaskClient) -> None:
    assert client.get(URL).status_code == 401


@pytest.mark.usefixtures("customers")
def test_top_customers_runs_one_query(
    client: FlaskClient, auth_headers: dict[str, str], count_queries: QueryCounter
) -> None:
    with count_queries() as statements:
        client.get(URL, headers=auth_headers)

    assert len([s for s in statements if "FROM orders" in s]) == 1


def test_top_customers_is_documented(client: FlaskClient) -> None:
    operation = client.get("/api/openapi.json").get_json()["paths"][URL]["get"]

    assert operation["tags"] == ["analytics"]
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "country",
        "limit",
        "days",
    }
    assert set(operation["responses"]) == {"200", "401", "422"}
