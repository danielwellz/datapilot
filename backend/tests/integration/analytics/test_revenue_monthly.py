from datetime import datetime, timedelta, timezone

import pytest
from flask.testing import FlaskClient

from app.models import OrderStatus
from tests.factories import create_customer
from tests.integration.analytics.conftest import at, sale
from tests.integration.conftest import QueryCounter

URL = "/api/analytics/revenue-monthly"


@pytest.fixture
def monthly_sales() -> None:
    """Today is 2026-03-15; months=3 returns December 2025 to February 2026.

    Paid revenue by month: 2024-12: 80, 2025-01: 100, 2025-02: 0,
    2025-10: 30, 2025-11: 60, 2025-12: 90, 2026-01: 0, 2026-02: 150.
    """
    ana = create_customer()
    # History before the returned months: year-ago and moving-average inputs.
    sale(ana, "80.00", at("2024-12-10"))
    sale(ana, "100.00", at("2025-01-20"))
    sale(ana, "30.00", at("2025-10-05"))
    sale(ana, "60.00", at("2025-11-05"))

    sale(ana, "50.00", at("2025-12-01", "00:00:00"))
    sale(ana, "40.00", at("2025-12-31", "23:59:59"))

    # January has orders, but none of them paid.
    sale(ana, "40.00", at("2026-01-10"), status=OrderStatus.REFUNDED)
    sale(ana, "70.00", at("2026-01-11"), status=OrderStatus.CANCELLED)

    sale(ana, "100.00", at("2026-02-01", "00:00:00"))
    sale(ana, "20.00", at("2026-02-14"))
    # 00:30 on March 1st at UTC+2 is still February 28th in UTC.
    sale(ana, "30.00", datetime(2026, 3, 1, 0, 30, tzinfo=timezone(timedelta(hours=2))))

    # The current month is incomplete and never returned.
    sale(ana, "500.00", at("2026-03-01", "00:00:00"))


@pytest.mark.usefixtures("monthly_sales")
def test_monthly_revenue_compares_each_month_with_the_month_and_year_before(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    response = client.get(URL, query_string={"months": 3}, headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "items": [
            {
                "month": "2025-12-01",
                "revenue": "90.00",
                "orders": 2,
                # Up 30 on 60 a month before, and 10 on 80 a year before.
                "revenue_change_mom": 0.5,
                "revenue_change_yoy": 0.125,
                # Average of 30, 60 and 90.
                "revenue_moving_average_3m": "60.00",
            },
            {
                # A month without paid orders is present, with zero revenue.
                "month": "2026-01-01",
                "revenue": "0.00",
                "orders": 0,
                "revenue_change_mom": -1.0,
                "revenue_change_yoy": -1.0,
                # Average of 60, 90 and 0.
                "revenue_moving_average_3m": "50.00",
            },
            {
                "month": "2026-02-01",
                "revenue": "150.00",
                "orders": 3,
                # Both months it compares with had no revenue.
                "revenue_change_mom": None,
                "revenue_change_yoy": None,
                # Average of 90, 0 and 150.
                "revenue_moving_average_3m": "80.00",
            },
        ]
    }


def test_monthly_revenue_covers_24_months_by_default_even_without_sales(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    items = client.get(URL, headers=auth_headers).get_json()["items"]

    assert len(items) == 24
    assert (items[0]["month"], items[-1]["month"]) == ("2024-03-01", "2026-02-01")
    assert {item["revenue"] for item in items} == {"0.00"}
    assert {item["revenue_change_mom"] for item in items} == {None}
    assert {item["revenue_moving_average_3m"] for item in items} == {"0.00"}


def test_moving_average_is_rounded_to_cents(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    ana = create_customer()
    sale(ana, "10.00", at("2025-12-15"))
    sale(ana, "10.00", at("2026-01-15"))
    sale(ana, "11.00", at("2026-02-15"))

    items = client.get(URL, query_string={"months": 1}, headers=auth_headers).get_json()["items"]

    # 31 / 3 = 10.333...; 11 / 10 is a 10% rise.
    assert items == [
        {
            "month": "2026-02-01",
            "revenue": "11.00",
            "orders": 1,
            "revenue_change_mom": 0.1,
            "revenue_change_yoy": None,
            "revenue_moving_average_3m": "10.33",
        }
    ]


@pytest.mark.parametrize("query", [{"months": 0}, {"months": 37}, {"days": 30}])
def test_monthly_revenue_rejects_invalid_query_parameters(
    client: FlaskClient, auth_headers: dict[str, str], query: dict[str, object]
) -> None:
    assert client.get(URL, query_string=query, headers=auth_headers).status_code == 422


def test_monthly_revenue_requires_an_access_token(client: FlaskClient) -> None:
    assert client.get(URL).status_code == 401


@pytest.mark.usefixtures("monthly_sales")
def test_monthly_revenue_runs_one_query(
    client: FlaskClient, auth_headers: dict[str, str], count_queries: QueryCounter
) -> None:
    with count_queries() as statements:
        client.get(URL, query_string={"months": 36}, headers=auth_headers)

    assert len([s for s in statements if "FROM orders" in s]) == 1


def test_monthly_revenue_is_documented(client: FlaskClient) -> None:
    operation = client.get("/api/openapi.json").get_json()["paths"][URL]["get"]

    assert operation["tags"] == ["analytics"]
    assert [parameter["name"] for parameter in operation["parameters"]] == ["months"]
    assert set(operation["responses"]) == {"200", "401", "422"}
