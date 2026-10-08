from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.models import OrderSort, OrderStatus
from app.schemas.orders import OrderListQuery
from app.schemas.types import MAX_DATABASE_ID
from app.services.orders import filters_from_query


def test_defaults_are_newest_first_25_per_page_without_filters() -> None:
    query = OrderListQuery()

    assert query.sort is OrderSort.CREATED_AT
    assert query.limit == 25
    assert query.status == []
    assert query.cursor is None


def test_country_is_trimmed_and_uppercased() -> None:
    assert OrderListQuery(country=" de ").country == "DE"


@pytest.mark.parametrize(
    "values",
    [
        {"limit": 0},
        {"limit": 101},
        {"country": "USA"},
        {"country": "1A"},
        {"customer_id": 0},
        {"customer_id": MAX_DATABASE_ID + 1},
        {"min_total": "-0.01"},
        {"max_total": "1.005"},
        {"min_total": "10000000000.00"},
        {"min_total": "NaN"},
        {"date_from": "2025-03-02", "date_to": "2025-03-01"},
        {"min_total": "20", "max_total": "19.99"},
        {"unknown": "x"},
    ],
)
def test_invalid_query_is_rejected(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        OrderListQuery.model_validate(values)


def test_equal_range_bounds_are_accepted() -> None:
    query = OrderListQuery(
        date_from=date(2025, 3, 1),
        date_to=date(2025, 3, 1),
        min_total=Decimal("5"),
        max_total=Decimal("5"),
    )

    assert query.date_from == query.date_to


def test_date_filters_become_half_open_utc_instants() -> None:
    filters = filters_from_query(
        OrderListQuery(date_from=date(2025, 3, 1), date_to=date(2025, 3, 31))
    )

    assert filters.created_from == datetime(2025, 3, 1, tzinfo=UTC)
    assert filters.created_before == datetime(2025, 4, 1, tzinfo=UTC)


def test_the_last_representable_day_sets_no_upper_bound() -> None:
    assert filters_from_query(OrderListQuery(date_to=date.max)).created_before is None


def test_statuses_are_deduplicated_and_sorted() -> None:
    query = OrderListQuery(
        status=[OrderStatus.REFUNDED, OrderStatus.CANCELLED, OrderStatus.REFUNDED]
    )

    assert filters_from_query(query).statuses == (OrderStatus.CANCELLED, OrderStatus.REFUNDED)
