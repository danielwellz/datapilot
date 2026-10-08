from datetime import datetime, timedelta, timezone

import pytest
from flask.testing import FlaskClient

from app.models import OrderStatus
from tests.factories import create_customer, create_order, create_product
from tests.integration.analytics.conftest import at
from tests.integration.conftest import QueryCounter

URL = "/api/analytics/summary"


@pytest.fixture
def week_of_orders() -> None:
    """Today is 2026-03-15; days=7 compares 03-08..03-14 with 03-01..03-07.

    Current period:   paid 100 (Ana) + 50 + 20 (Ben) = 170.00 in 3 orders,
                      plus one refunded and one cancelled order (Cleo):
                      5 placed, 2 active customers, refund rate 1/5.
    Previous period:  paid 100 (Ana) + 25 (Cleo) + 20 (Ben) = 145.00 in
                      3 orders, 3 active customers, nothing refunded.
    """
    ana, ben, cleo = create_customer(), create_customer(), create_customer()
    lamp = create_product(price="100.00")
    atlas = create_product(price="50.00")
    mug = create_product(price="25.00")
    novel = create_product(price="20.00")

    # Current period, including its first and last instants.
    create_order(ana, [(lamp, 1)], created_at=at("2026-03-14", "23:59:59"))
    create_order(ben, [(atlas, 1)], created_at=at("2026-03-08", "00:00:00"))
    create_order(ben, [(novel, 1)], created_at=at("2026-03-10"))
    create_order(cleo, [(mug, 1)], status=OrderStatus.REFUNDED, created_at=at("2026-03-11"))
    create_order(cleo, [(novel, 1)], status=OrderStatus.CANCELLED, created_at=at("2026-03-12"))

    # Previous period. 00:30 at UTC+2 on 03-08 is still 03-07 in UTC.
    create_order(ana, [(lamp, 1)], created_at=at("2026-03-07", "23:59:59"))
    create_order(cleo, [(mug, 1)], created_at=at("2026-03-02"))
    create_order(
        ben,
        [(novel, 1)],
        created_at=datetime(2026, 3, 8, 0, 30, tzinfo=timezone(timedelta(hours=2))),
    )

    # Outside both periods: before the previous one, and today (incomplete).
    create_order(ana, [(lamp, 1)], created_at=at("2026-02-28", "23:59:59"))
    create_order(ana, [(mug, 1)], created_at=at("2026-03-15", "00:00:00"))


@pytest.mark.usefixtures("week_of_orders")
def test_summary_compares_the_last_complete_days_with_the_days_before(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    response = client.get(URL, query_string={"days": 7}, headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "period": {"start_date": "2026-03-08", "end_date": "2026-03-14"},
        "previous_period": {"start_date": "2026-03-01", "end_date": "2026-03-07"},
        # (170 - 145) / 145 = 0.17241...
        "revenue": {"current": "170.00", "previous": "145.00", "change": 0.1724},
        "orders": {"current": 3, "previous": 3, "change": 0.0},
        # 170 / 3 = 56.666..., 145 / 3 = 48.333...; the change uses the
        # unrounded averages: (170/3 - 145/3) / (145/3) = 25 / 145.
        "average_order_value": {"current": "56.67", "previous": "48.33", "change": 0.1724},
        # Two active customers against three: a third fewer.
        "active_customers": {"current": 2, "previous": 3, "change": -0.3333},
        # 1 refunded of 5 placed; no change from a rate of zero.
        "refund_rate": {"current": 0.2, "previous": 0.0, "change": None},
    }


def test_summary_of_periods_without_orders_has_zero_totals_and_no_averages(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    body = client.get(URL, query_string={"days": 1}, headers=auth_headers).get_json()

    assert body == {
        "period": {"start_date": "2026-03-14", "end_date": "2026-03-14"},
        "previous_period": {"start_date": "2026-03-13", "end_date": "2026-03-13"},
        "revenue": {"current": "0.00", "previous": "0.00", "change": None},
        "orders": {"current": 0, "previous": 0, "change": None},
        "average_order_value": {"current": None, "previous": None, "change": None},
        "active_customers": {"current": 0, "previous": 0, "change": None},
        "refund_rate": {"current": None, "previous": None, "change": None},
    }


def test_summary_covers_thirty_days_by_default(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    body = client.get(URL, headers=auth_headers).get_json()

    assert body["period"] == {"start_date": "2026-02-13", "end_date": "2026-03-14"}
    assert body["previous_period"] == {"start_date": "2026-01-14", "end_date": "2026-02-12"}


@pytest.mark.parametrize(
    "query", [{"days": 0}, {"days": 366}, {"days": "week"}, {"days": 7, "country": "US"}]
)
def test_summary_rejects_invalid_query_parameters(
    client: FlaskClient, auth_headers: dict[str, str], query: dict[str, object]
) -> None:
    response = client.get(URL, query_string=query, headers=auth_headers)

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_failed"


def test_summary_requires_an_access_token(client: FlaskClient) -> None:
    assert client.get(URL).status_code == 401


@pytest.mark.usefixtures("week_of_orders")
def test_summary_runs_one_query(
    client: FlaskClient, auth_headers: dict[str, str], count_queries: QueryCounter
) -> None:
    with count_queries() as statements:
        client.get(URL, query_string={"days": 7}, headers=auth_headers)

    # The access token check loads the user; the summary itself is one query.
    assert len([s for s in statements if "FROM orders" in s]) == 1


def test_summary_is_documented_with_its_query_and_responses(client: FlaskClient) -> None:
    operation = client.get("/api/openapi.json").get_json()["paths"][URL]["get"]

    assert operation["tags"] == ["analytics"]
    assert operation["security"] == [{"bearerAuth": []}]
    assert [parameter["name"] for parameter in operation["parameters"]] == ["days"]
    assert set(operation["responses"]) == {"200", "401", "422"}
