import hashlib
from collections import Counter
from datetime import UTC, date, datetime

import pytest

from app.models import OrderChannel, OrderStatus
from app.seed import generator
from app.seed.generator import (
    SCALES,
    GeneratedOrder,
    SalesData,
    SeedScale,
    generate_sales_data,
)
from app.seed.reference import CATEGORIES, COUNTRY_WEIGHTS

END_DATE = date(2026, 10, 1)
TINY = SeedScale("tiny", customers=200, products=30, orders=2_000)


def digest(data: SalesData) -> str:
    """A fingerprint of every generated row, in generation order."""
    sha = hashlib.sha256()
    for row in (*data.customers, *data.products, *data.orders):
        sha.update(repr(row).encode())
    return sha.hexdigest()


@pytest.fixture(scope="module")
def small() -> tuple[SalesData, list[GeneratedOrder]]:
    data = generate_sales_data(SCALES["small"], seed=42, end_date=END_DATE)
    return data, list(data.orders)


# --- Determinism ---


def test_the_same_seed_and_end_date_give_identical_rows() -> None:
    first = generate_sales_data(TINY, seed=7, end_date=END_DATE)
    second = generate_sales_data(TINY, seed=7, end_date=END_DATE)

    assert digest(first) == digest(second)


def test_a_different_seed_gives_different_rows() -> None:
    assert digest(generate_sales_data(TINY, seed=7, end_date=END_DATE)) != digest(
        generate_sales_data(TINY, seed=8, end_date=END_DATE)
    )


def test_generated_rows_match_the_recorded_checksum() -> None:
    # Pins the exact output. It changes when a distribution is tuned on
    # purpose (update the value then) and must never change by accident,
    # for example through a dependency or interpreter upgrade.
    data = generate_sales_data(TINY, seed=42, end_date=END_DATE)

    assert digest(data) == "4b094c320c0f9c87390db9d45f7be2ba96a23164dcaa8ae597c7a6fec7513cf9"


# --- Shape and integrity ---


def test_scales_have_the_documented_sizes() -> None:
    assert SCALES["small"] == SeedScale("small", customers=2_000, products=100, orders=50_000)
    assert SCALES["full"] == SeedScale("full", customers=50_000, products=1_000, orders=2_000_000)


@pytest.mark.parametrize(
    ("customers", "products", "orders"), [(0, 30, 10), (10, 4, 10), (10, 30, -1)]
)
def test_scales_too_small_for_valid_orders_are_rejected(
    customers: int, products: int, orders: int
) -> None:
    with pytest.raises(ValueError, match="at least 1 customer, 5 products"):
        SeedScale("broken", customers=customers, products=products, orders=orders)


def test_a_catalog_of_five_products_still_fills_the_largest_orders() -> None:
    data = generate_sales_data(SeedScale("five", 50, 5, 500), seed=5, end_date=END_DATE)

    assert max(len(order.items) for order in data.orders) == 5


def test_row_counts_match_the_scale(small: tuple[SalesData, list[GeneratedOrder]]) -> None:
    data, orders = small
    item_count = sum(len(order.items) for order in orders)

    assert (len(data.customers), len(data.products), len(orders)) == (2_000, 100, 50_000)
    assert 2.1 < item_count / len(orders) < 2.4


def test_ids_are_sequential_and_order_ids_follow_creation_time(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    data, orders = small

    assert [c.id for c in data.customers] == list(range(1, 2_001))
    assert [p.id for p in data.products] == list(range(1, 101))
    assert [o.order.id for o in orders] == list(range(1, 50_001))
    created = [o.order.created_at for o in orders]
    assert created == sorted(created)


def test_orders_fall_within_the_three_years_before_the_end_date(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    _, orders = small

    assert orders[0].order.created_at >= datetime(2023, 10, 1, tzinfo=UTC)
    assert orders[-1].order.created_at < datetime(2026, 10, 1, tzinfo=UTC)


def test_every_order_is_placed_after_its_customer_signed_up(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    data, orders = small
    signed_up = {customer.id: customer.signed_up_at for customer in data.customers}

    assert all(o.order.created_at > signed_up[o.order.customer_id] for o in orders)


def test_order_totals_equal_the_sum_of_their_items(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    _, orders = small

    for order, items in orders:
        assert order.total_cents == sum(i.quantity * i.unit_price_cents for i in items)


def test_items_list_distinct_products_at_catalog_price(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    data, orders = small
    prices = {product.id: product.price_cents for product in data.products}

    for order, items in orders:
        assert 1 <= len(items) <= 5
        assert len({item.product_id for item in items}) == len(items)
        assert all(item.order_id == order.id and item.quantity > 0 for item in items)
        assert all(item.unit_price_cents == prices[item.product_id] for item in items)


def test_customers_have_unique_lowercase_emails_and_known_countries(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    data, _ = small
    emails = [customer.email for customer in data.customers]

    assert len(set(emails)) == len(emails)
    assert all(email == email.lower() and email.endswith("@example.com") for email in emails)
    assert {customer.country for customer in data.customers} <= set(COUNTRY_WEIGHTS)


def test_full_catalog_has_unique_names_and_shelf_prices() -> None:
    products = generate_sales_data(SCALES["full"], seed=42, end_date=END_DATE).products

    assert len({product.name for product in products}) == 1_000
    assert {product.category for product in products} == {c.name for c in CATEGORIES}
    assert all(p.price_cents >= 99 and p.price_cents % 100 == 99 for p in products)


def test_generation_fails_clearly_when_nobody_can_place_the_first_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generator, "EARLY_CUSTOMER_SHARE", 0.0)
    data = generate_sales_data(TINY, seed=1, end_date=END_DATE)

    with pytest.raises(ValueError, match="no customer had signed up by 2023-10-01"):
        next(data.orders)


# --- Realism ---


def test_status_mix_is_mostly_paid_with_some_refunds_and_cancellations(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    _, orders = small
    share = _shares(Counter(o.order.status for o in orders))

    assert set(share) == set(OrderStatus)
    assert 0.025 < share[OrderStatus.REFUNDED] < 0.035
    assert 0.015 < share[OrderStatus.CANCELLED] < 0.025


def test_mobile_share_grows_over_the_years(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    _, orders = small
    first_year = [o.order.channel for o in orders if o.order.created_at.date() < date(2024, 10, 1)]
    last_year = [o.order.channel for o in orders if o.order.created_at.date() >= date(2025, 10, 1)]

    assert set(Counter(last_year)) == set(OrderChannel)
    assert _shares(Counter(last_year))["mobile"] > _shares(Counter(first_year))["mobile"] + 0.1


def test_a_minority_of_customers_places_most_orders(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    data, orders = small
    per_customer = sorted(Counter(o.order.customer_id for o in orders).values(), reverse=True)
    top_fifth = per_customer[: len(data.customers) // 5]

    assert sum(top_fifth) / len(orders) > 0.6
    # Repeat customers are the norm, not one-off buyers.
    assert sum(1 for count in per_customer if count > 1) / len(per_customer) > 0.8


def test_a_few_countries_dominate_the_customer_base(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    data, _ = small
    counts = Counter(customer.country for customer in data.customers).most_common()

    assert counts[0][0] == "US"
    assert 0.4 < sum(count for _, count in counts[:3]) / len(data.customers) < 0.55


def test_orders_grow_year_over_year_and_peak_in_december(
    small: tuple[SalesData, list[GeneratedOrder]],
) -> None:
    _, orders = small
    days = [o.order.created_at.date() for o in orders]
    last_year = sum(1 for day in days if day >= date(2025, 10, 1))
    year_before = sum(1 for day in days if date(2024, 10, 1) <= day < date(2025, 10, 1))
    by_month = Counter(day.month for day in days if day.year == 2025)

    assert 1.2 < last_year / year_before < 1.3
    assert by_month.most_common(1)[0][0] == 12


def _shares(counts: Counter[str]) -> dict[str, float]:
    total = sum(counts.values())
    return {key: count / total for key, count in counts.items()}
