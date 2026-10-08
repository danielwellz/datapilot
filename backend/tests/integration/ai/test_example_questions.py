"""Every example question's SQL returns the right answer.

The demo model answers the example questions with fixed SQL, so that SQL
must be right. Each test builds a small dataset around the database's own
clock, runs the example's SQL exactly as Ask your data would (guarded, as
the read-only role), and compares it with the same result computed in
Python from the rows the test created.
"""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, scoped_session

from app.ai.examples import EXAMPLE_QUESTIONS
from app.ai.sql_guard import guard_sql
from app.models import OrderChannel, OrderStatus
from tests.factories import create_customer, create_order, create_product
from tests.integration.ai.conftest import RunAsReadonly

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Line:
    name: str
    category: str
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True)
class Sale:
    country: str
    status: OrderStatus
    channel: OrderChannel
    created_at: datetime
    lines: tuple[Line, ...]

    @property
    def total(self) -> Decimal:
        return sum((line.quantity * line.unit_price for line in self.lines), Decimal(0))


@dataclass(frozen=True)
class Dataset:
    now: datetime
    sales: list[Sale]
    signups: list[datetime]

    def paid(self) -> list[Sale]:
        return [sale for sale in self.sales if sale.status is OrderStatus.PAID]


def _month_start(moment: datetime, months_back: int = 0) -> datetime:
    index = moment.year * 12 + moment.month - 1 - months_back
    return datetime(index // 12, index % 12 + 1, 1, tzinfo=UTC)


def _round(value: Decimal) -> Decimal:
    # PostgreSQL's round() on numeric rounds halves away from zero.
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@pytest.fixture
def dataset(db_session: scoped_session[Session]) -> Dataset:
    """Sales spread over two years before the database's now(), in every status."""
    now: datetime = db_session.execute(text("SELECT now()")).scalar_one().astimezone(UTC)
    products = [
        create_product(name="Desk Lamp", category="Home & Kitchen", price="35.00"),
        create_product(name="Paperback Novel", category="Books", price="12.50"),
        create_product(name="Trail Shoes", category="Sports & Outdoors", price="89.99"),
        create_product(name="Seed Kit", category="Garden", price="7.25"),
    ]
    countries = ["US", "DE", "FR", "GB", "US", "DE", "IT"]
    signups = [_month_start(now, months) + timedelta(days=3) for months in (0, 1, 1, 4, 11, 12, 20)]
    customers = [
        create_customer(country=country, signed_up_at=signed_up_at)
        for country, signed_up_at in zip(countries, signups, strict=True)
    ]

    moments = [
        # Paid orders just inside and just outside the 90-day window.
        now - timedelta(days=89),
        now - timedelta(days=91),
        now - timedelta(days=2),
        now - timedelta(days=40),
        *(_month_start(now, months) + timedelta(days=10, hours=5) for months in range(1, 26, 2)),
        datetime(now.year - 1, 7, 1, 12, tzinfo=UTC),
        datetime(now.year - 1, 12, 31, 23, 59, tzinfo=UTC),
        datetime(now.year, 1, 1, 0, 0, tzinfo=UTC),
    ]
    statuses = [OrderStatus.PAID, OrderStatus.PAID, OrderStatus.REFUNDED, OrderStatus.CANCELLED]
    channels = list(OrderChannel)
    sales: list[Sale] = []
    for index, created_at in enumerate(moments):
        customer = customers[index % len(customers)]
        chosen = [(products[index % 4], 1 + index % 3), (products[(index + 1) % 4], 1)]
        status = statuses[index % len(statuses)]
        channel = channels[index % len(channels)]
        create_order(customer, chosen, status=status, channel=channel, created_at=created_at)
        sales.append(
            Sale(
                country=customer.country,
                status=status,
                channel=channel,
                created_at=created_at,
                lines=tuple(
                    Line(product.name, product.category, quantity, product.price)
                    for product, quantity in chosen
                ),
            )
        )
    return Dataset(now=now, sales=sales, signups=signups)


def _monthly_revenue(data: Dataset) -> list[tuple[Any, ...]]:
    start, end = _month_start(data.now, 12), _month_start(data.now)
    revenue: defaultdict[date, Decimal] = defaultdict(Decimal)
    for sale in data.paid():
        if start <= sale.created_at < end:
            revenue[_month_start(sale.created_at).date()] += sale.total
    return [(month, _round(value)) for month, value in sorted(revenue.items())]


def _top_countries_last_year(data: Dataset) -> list[tuple[Any, ...]]:
    revenue: defaultdict[str, Decimal] = defaultdict(Decimal)
    for sale in data.paid():
        if sale.created_at.year == data.now.year - 1:
            revenue[sale.country] += sale.total
    ranked = sorted(revenue.items(), key=lambda item: (-item[1], item[0]))[:10]
    return [(country, _round(value)) for country, value in ranked]


def _top_products_90_days(data: Dataset) -> list[tuple[Any, ...]]:
    revenue: defaultdict[str, Decimal] = defaultdict(Decimal)
    for sale in data.paid():
        if sale.created_at >= data.now - timedelta(days=90):
            for line in sale.lines:
                revenue[line.name] += line.quantity * line.unit_price
    ranked = sorted(revenue.items(), key=lambda item: (-item[1], item[0]))[:10]
    return [(name, _round(value)) for name, value in ranked]


def _orders_by_channel_this_year(data: Dataset) -> list[tuple[Any, ...]]:
    counts = Counter(
        sale.channel.value for sale in data.sales if sale.created_at.year == data.now.year
    )
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _average_order_value_by_country(data: Dataset) -> list[tuple[Any, ...]]:
    totals: defaultdict[str, list[Decimal]] = defaultdict(list)
    for sale in data.paid():
        totals[sale.country].append(sale.total)
    averages = {
        country: _round(sum(values, Decimal(0)) / len(values)) for country, values in totals.items()
    }
    return sorted(averages.items(), key=lambda item: (-item[1], item[0]))


def _refund_share_by_month(data: Dataset) -> list[tuple[Any, ...]]:
    start, end = _month_start(data.now, 12), _month_start(data.now)
    placed: Counter[date] = Counter()
    refunded: Counter[date] = Counter()
    for sale in data.sales:
        if start <= sale.created_at < end:
            month = _month_start(sale.created_at).date()
            placed[month] += 1
            refunded[month] += sale.status is OrderStatus.REFUNDED
    return [
        (month, _round(Decimal(100) * refunded[month] / placed[month])) for month in sorted(placed)
    ]


def _units_by_category_last_quarter(data: Dataset) -> list[tuple[Any, ...]]:
    quarter_start = _month_start(data.now, (data.now.month - 1) % 3)
    start = _month_start(quarter_start, 3)
    units: Counter[str] = Counter()
    for sale in data.paid():
        if start <= sale.created_at < quarter_start:
            for line in sale.lines:
                units[line.category] += line.quantity
    return sorted(units.items(), key=lambda item: (-item[1], item[0]))


def _signups_by_month(data: Dataset) -> list[tuple[Any, ...]]:
    start, end = _month_start(data.now, 12), _month_start(data.now)
    counts = Counter(
        _month_start(signed_up_at).date()
        for signed_up_at in data.signups
        if start <= signed_up_at < end
    )
    return sorted(counts.items())


EXPECTED: dict[str, Callable[[Dataset], list[tuple[Any, ...]]]] = {
    "What was the monthly revenue over the last 12 months?": _monthly_revenue,
    "Which 10 countries brought in the most revenue last year?": _top_countries_last_year,
    "What are the top 10 products by revenue in the last 90 days?": _top_products_90_days,
    "How many orders came from each channel this year?": _orders_by_channel_this_year,
    "What is the average order value by country?": _average_order_value_by_country,
    "What share of orders were refunded each month over the last year?": _refund_share_by_month,
    "Which product categories sold the most units last quarter?": _units_by_category_last_quarter,
    "How many new customers signed up each month over the last year?": _signups_by_month,
}


def test_every_example_question_has_an_independent_expectation() -> None:
    assert set(EXPECTED) == {example.question for example in EXAMPLE_QUESTIONS}


@pytest.mark.parametrize("example", EXAMPLE_QUESTIONS, ids=lambda example: example.question)
def test_example_sql_returns_the_independently_computed_answer(
    example: Any, dataset: Dataset, run_as_readonly: RunAsReadonly
) -> None:
    assert example.answer.sql is not None
    expected = EXPECTED[example.question](dataset)

    rows = run_as_readonly(guard_sql(example.answer.sql, max_rows=1000).sql)

    assert expected, "the dataset must give every example a non-empty answer"
    assert rows == expected
