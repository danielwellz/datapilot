from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app.models import Customer, OrderChannel, OrderStatus, Product
from app.services.cursors import CursorSigner
from app.services.orders import CURSOR_PURPOSE
from tests.factories import create_customer, create_order, create_product
from tests.integration.conftest import QueryCounter

URL = "/api/orders"

QueryParams = Mapping[str, str | list[str]]


@dataclass(frozen=True)
class Row:
    """What a test needs to know about an order it created."""

    id: int
    created_at: datetime
    total: Decimal
    status: OrderStatus
    country: str


class Shop:
    """Creates orders whose total is a chosen amount, reusing one product per price."""

    def __init__(self) -> None:
        self._products: dict[str, Product] = {}

    def order(
        self,
        customer: Customer,
        total: str,
        created_at: datetime,
        status: OrderStatus = OrderStatus.PAID,
        channel: OrderChannel = OrderChannel.WEB,
    ) -> Row:
        product = self._products.get(total) or create_product(price=total)
        self._products[total] = product
        order = create_order(
            customer, [(product, 1)], status=status, channel=channel, created_at=created_at
        )
        return Row(order.id, order.created_at, order.total, status, customer.country)


def get_page(client: FlaskClient, headers: dict[str, str], params: QueryParams) -> dict[str, Any]:
    response = client.get(URL, headers=headers, query_string=dict(params))
    assert response.status_code == 200, response.get_json()
    body: dict[str, Any] = response.get_json()
    return body


def ids(body: dict[str, Any]) -> list[int]:
    return [item["id"] for item in body["items"]]


# --- Response shape -------------------------------------------------------


def test_list_orders_returns_orders_with_their_customer(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    ana = create_customer(name="Ana Lima", country="BR")
    order = Shop().order(
        ana,
        "1234.50",
        datetime(2025, 6, 1, 18, 0, tzinfo=UTC),
        status=OrderStatus.REFUNDED,
        channel=OrderChannel.MOBILE,
    )

    body = get_page(client, auth_headers, {})

    assert body == {
        "items": [
            {
                "id": order.id,
                "status": "refunded",
                "channel": "mobile",
                "total": "1234.50",
                "created_at": "2025-06-01T18:00:00Z",
                "customer": {"id": ana.id, "name": "Ana Lima", "country": "BR"},
            }
        ],
        "next_cursor": None,
    }


def test_list_orders_without_matches_returns_an_empty_last_page(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    assert get_page(client, auth_headers, {}) == {"items": [], "next_cursor": None}


def test_list_orders_returns_25_by_default_and_a_next_cursor_when_more_rows_exist(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    shop, customer = Shop(), create_customer()
    start = datetime(2025, 1, 1, tzinfo=UTC)
    for minute in range(26):
        shop.order(customer, "10.00", start + timedelta(minutes=minute))

    body = get_page(client, auth_headers, {})

    assert len(body["items"]) == 25
    assert body["next_cursor"] is not None


def test_list_orders_has_no_next_cursor_when_the_page_holds_the_last_row(
    client: FlaskClient, auth_headers: dict[str, str]
) -> None:
    shop, customer = Shop(), create_customer()
    for minute in range(3):
        shop.order(customer, "10.00", datetime(2025, 1, 1, 0, minute, tzinfo=UTC))

    body = get_page(client, auth_headers, {"limit": "3"})

    assert len(body["items"]) == 3
    assert body["next_cursor"] is None


@pytest.mark.parametrize("limit", ["1", "100"])
def test_list_orders_accepts_the_limit_bounds(
    client: FlaskClient, auth_headers: dict[str, str], limit: str
) -> None:
    Shop().order(create_customer(), "10.00", datetime(2025, 1, 1, tzinfo=UTC))

    assert len(get_page(client, auth_headers, {"limit": limit})["items"]) == 1


# --- Filters --------------------------------------------------------------


@pytest.fixture
def four_orders() -> dict[str, Row]:
    """Orders on both sides of every filter boundary the tests use."""
    shop = Shop()
    ana = create_customer(country="DE")
    ben = create_customer(country="US")
    cara = create_customer(country="GB")
    return {
        "a": shop.order(ana, "10.00", datetime(2025, 3, 1, 0, 0, 0, tzinfo=UTC)),
        "b": shop.order(
            ben,
            "25.50",
            datetime(2025, 3, 31, 23, 59, 59, tzinfo=UTC),
            status=OrderStatus.REFUNDED,
            channel=OrderChannel.MOBILE,
        ),
        "c": shop.order(
            ben,
            "99.99",
            datetime(2025, 4, 1, 0, 0, 0, tzinfo=UTC),
            status=OrderStatus.CANCELLED,
            channel=OrderChannel.MARKETPLACE,
        ),
        "d": shop.order(
            cara,
            "25.49",
            datetime(2025, 2, 28, 23, 59, 59, tzinfo=UTC),
            channel=OrderChannel.MOBILE,
        ),
    }


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, "cbad"),
        ({"status": "refunded"}, "b"),
        ({"status": ["paid", "cancelled"]}, "cad"),
        ({"country": "us"}, "cb"),
        ({"channel": "mobile"}, "bd"),
        ({"date_from": "2025-03-01", "date_to": "2025-03-31"}, "ba"),
        ({"date_from": "2025-04-01"}, "c"),
        ({"date_to": "2025-02-28"}, "d"),
        ({"date_to": "9999-12-31"}, "cbad"),
        ({"min_total": "25.50"}, "cb"),
        ({"max_total": "25.50"}, "bad"),
        ({"min_total": "25.49", "max_total": "25.50"}, "bd"),
        ({"country": "US", "status": "refunded"}, "b"),
        ({"sort": "total"}, "cbda"),
        ({"sort": "total", "channel": "mobile"}, "bd"),
    ],
)
def test_list_orders_applies_each_filter_and_sort(
    client: FlaskClient,
    auth_headers: dict[str, str],
    four_orders: dict[str, Row],
    params: QueryParams,
    expected: str,
) -> None:
    body = get_page(client, auth_headers, params)

    assert ids(body) == [four_orders[name].id for name in expected]


def test_list_orders_filters_by_customer(client: FlaskClient, auth_headers: dict[str, str]) -> None:
    shop = Shop()
    ana, ben = create_customer(), create_customer()
    when = datetime(2025, 5, 1, tzinfo=UTC)
    older = shop.order(ana, "10.00", when)
    shop.order(ben, "10.00", when + timedelta(hours=1))
    newer = shop.order(ana, "10.00", when + timedelta(hours=2))

    body = get_page(client, auth_headers, {"customer_id": str(ana.id)})

    assert ids(body) == [newer.id, older.id]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": "0"},
        {"limit": "101"},
        {"limit": "ten"},
        {"status": "shipped"},
        {"channel": "phone"},
        {"country": "USA"},
        {"customer_id": "0"},
        {"customer_id": str(2**63)},
        {"date_from": "2025-13-01"},
        {"date_from": "2025-03-02", "date_to": "2025-03-01"},
        {"min_total": "-1"},
        {"min_total": "1.005"},
        {"min_total": "20", "max_total": "10"},
        {"sort": "id"},
        {"page": "2"},
    ],
)
def test_list_orders_rejects_invalid_parameters_with_422(
    client: FlaskClient, auth_headers: dict[str, str], params: QueryParams
) -> None:
    response = client.get(URL, headers=auth_headers, query_string=dict(params))

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_failed"


# --- Keyset pagination ----------------------------------------------------


@pytest.fixture
def tied_orders() -> list[Row]:
    """36 orders sharing four timestamps and three totals, so most rows tie.

    Status, country and channel vary on cycles that do not line up with the
    sort values, so every filtered subset still contains ties.
    """
    shop = Shop()
    customers = [
        create_customer(country="US"),
        create_customer(country="DE"),
        create_customer(country="US"),
    ]
    start = datetime(2025, 11, 28, 12, 0, tzinfo=UTC)
    statuses = [
        OrderStatus.PAID,
        OrderStatus.PAID,
        OrderStatus.PAID,
        OrderStatus.REFUNDED,
        OrderStatus.CANCELLED,
    ]
    return [
        shop.order(
            customers[(index // 3) % 3],
            ["10.00", "25.50", "99.99"][index % 3],
            start + timedelta(seconds=index % 4),
            status=statuses[index % 5],
        )
        for index in range(36)
    ]


def walk(
    client: FlaskClient, headers: dict[str, str], params: QueryParams, limit: int
) -> list[list[int]]:
    """Follow next_cursor from the first page to the last; return each page's ids."""
    pages: list[list[int]] = []
    cursor: str | None = None
    while True:
        query = {**params, "limit": str(limit)} | ({"cursor": cursor} if cursor else {})
        body = get_page(client, headers, query)
        pages.append(ids(body))
        cursor = body["next_cursor"]
        if cursor is None:
            return pages
        assert len(pages) <= 100, "pagination did not reach the last page"


def expected_order(rows: list[Row], sort: str, keep: Any) -> list[int]:
    """The full result, computed independently of the API: filter, then sort with id as tiebreak."""

    def key(row: Row) -> tuple[Any, int]:
        return (row.created_at if sort == "created_at" else row.total, row.id)

    return [row.id for row in sorted(filter(keep, rows), key=key, reverse=True)]


FILTERS: list[tuple[QueryParams, Any]] = [
    ({}, lambda row: True),
    (
        {"status": ["refunded", "cancelled"]},
        lambda row: row.status in (OrderStatus.REFUNDED, OrderStatus.CANCELLED),
    ),
    (
        {"country": "US", "min_total": "20"},
        lambda row: row.country == "US" and row.total >= Decimal("20"),
    ),
]


@pytest.mark.parametrize("sort", ["created_at", "total"])
@pytest.mark.parametrize("limit", [1, 2, 7])
@pytest.mark.parametrize(("params", "keep"), FILTERS, ids=["all", "status", "country-total"])
def test_walking_every_page_returns_each_matching_order_exactly_once_in_order(
    client: FlaskClient,
    auth_headers: dict[str, str],
    tied_orders: list[Row],
    sort: str,
    limit: int,
    params: QueryParams,
    keep: Any,
) -> None:
    pages = walk(client, auth_headers, {**params, "sort": sort}, limit)

    walked = [order_id for page in pages for order_id in page]
    expected = expected_order(tied_orders, sort, keep)
    assert len(expected) > limit  # the walk crosses page boundaries inside ties
    # Same rows, same order: no duplicates, no gaps, no reordering at boundaries.
    assert walked == expected
    # Every page but the last is full, and the last is never empty.
    assert all(len(page) == limit for page in pages[:-1])
    assert 1 <= len(pages[-1]) <= limit


def test_a_cursor_works_with_a_different_page_size(
    client: FlaskClient, auth_headers: dict[str, str], tied_orders: list[Row]
) -> None:
    first = get_page(client, auth_headers, {"limit": "5"})

    second = get_page(client, auth_headers, {"limit": "10", "cursor": first["next_cursor"]})

    assert ids(second) == expected_order(tied_orders, "created_at", lambda row: True)[5:15]


def test_a_cursor_accepts_the_same_statuses_in_another_order(
    client: FlaskClient, auth_headers: dict[str, str], tied_orders: list[Row]
) -> None:
    first = get_page(client, auth_headers, {"status": ["paid", "refunded"], "limit": "2"})

    response = client.get(
        URL,
        headers=auth_headers,
        query_string={"status": ["refunded", "paid"], "limit": "2", "cursor": first["next_cursor"]},
    )

    assert response.status_code == 200


@pytest.mark.parametrize(("first", "then"), [("20", "20.00"), ("20.5", "20.50"), ("0", "0.00")])
def test_a_cursor_accepts_the_same_total_bound_written_differently(
    client: FlaskClient,
    auth_headers: dict[str, str],
    tied_orders: list[Row],
    first: str,
    then: str,
) -> None:
    page = get_page(client, auth_headers, {"min_total": first, "limit": "2"})

    response = client.get(
        URL,
        headers=auth_headers,
        query_string={"min_total": then, "limit": "2", "cursor": page["next_cursor"]},
    )

    assert response.status_code == 200


def assert_invalid_cursor(response: Any) -> None:
    assert response.status_code == 400
    error = response.get_json()["error"]
    assert error["code"] == "invalid_cursor"
    assert "first page" in error["message"]


@pytest.fixture
def next_cursor(client: FlaskClient, auth_headers: dict[str, str], tied_orders: list[Row]) -> str:
    cursor: str = get_page(client, auth_headers, {"limit": "2"})["next_cursor"]
    return cursor


def test_an_edited_cursor_is_rejected_with_400(
    client: FlaskClient, auth_headers: dict[str, str], next_cursor: str
) -> None:
    edited = ("A" if next_cursor[3] != "A" else "B").join([next_cursor[:3], next_cursor[4:]])

    assert_invalid_cursor(client.get(URL, headers=auth_headers, query_string={"cursor": edited}))


@pytest.mark.parametrize("cursor", ["not-a-cursor", "a.b", "", "x" * 600])
def test_a_malformed_cursor_is_rejected_with_400(
    client: FlaskClient, auth_headers: dict[str, str], cursor: str
) -> None:
    assert_invalid_cursor(client.get(URL, headers=auth_headers, query_string={"cursor": cursor}))


@pytest.mark.parametrize(
    "other_query",
    [{"sort": "total"}, {"status": "paid"}, {"country": "US"}, {"date_from": "2025-01-01"}],
)
def test_a_cursor_from_another_sort_or_filter_set_is_rejected_with_400(
    client: FlaskClient,
    auth_headers: dict[str, str],
    next_cursor: str,
    other_query: dict[str, str],
) -> None:
    response = client.get(
        URL, headers=auth_headers, query_string={**other_query, "cursor": next_cursor}
    )

    assert_invalid_cursor(response)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"v":2,"sort":"created_at","key":"2025-01-01T00:00:00Z","id":1,"filters":"x"}',
        b'{"v":1,"sort":"created_at","key":"2025-01-01T00:00:00","id":1,"filters":"x"}',
        b'{"v":1,"sort":"total","key":"many","id":1,"filters":"x"}',
        b'{"v":1,"sort":"id","key":1,"id":1,"filters":"x"}',
        b"[]",
        b"not json",
    ],
)
def test_a_correctly_signed_cursor_with_an_unknown_format_is_rejected_with_400(
    app: Flask, client: FlaskClient, auth_headers: dict[str, str], payload: bytes
) -> None:
    signer = CursorSigner(app.config["SECRET_KEY"].encode(), CURSOR_PURPOSE)

    response = client.get(URL, headers=auth_headers, query_string={"cursor": signer.sign(payload)})

    assert_invalid_cursor(response)


# --- Access and query count -----------------------------------------------


def test_list_orders_requires_an_access_token(client: FlaskClient) -> None:
    response = client.get(URL)

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("limit", ["1", "100"])
def test_list_orders_runs_two_queries_whatever_the_page_size(
    client: FlaskClient,
    auth_headers: dict[str, str],
    count_queries: QueryCounter,
    tied_orders: list[Row],
    limit: str,
) -> None:
    first = get_page(client, auth_headers, {"limit": "1"})

    with count_queries() as statements:
        body = get_page(client, auth_headers, {"limit": limit, "cursor": first["next_cursor"]})

    assert len(body["items"]) == min(int(limit), len(tied_orders) - 1)
    # The token's user, then the page of orders joined to their customers.
    assert len(statements) == 2
    assert "FROM users" in statements[0]
    assert "JOIN customers" in statements[1]
