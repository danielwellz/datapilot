"""Turns a seed into customers, products, orders and order items.

Every random draw comes from one ``random.Random(seed)``, in a fixed order:
customers, then products, then orders day by day. The same seed and end date
therefore always produce exactly the same rows.

How the data is shaped:

- Customers sign up at a growing rate; some signed up before the history
  starts. Each has an activity weight drawn from a Pareto distribution, so a
  minority of customers places most of the orders.
- Products belong to categories with their own log-normal price range, and
  their popularity follows Zipf's law (a few best sellers, a long tail).
- The calendar decides how many orders fall on each day (growth, seasonality,
  weekdays). Each order picks a customer who had signed up before that day,
  1 to 5 distinct products and a quantity for each.
- About 3% of orders are refunded and 2% cancelled. The mobile share of
  orders grows over the years.

Money is handled in integer cents, so an order's total is exactly the sum of
its items. Orders are produced lazily: only the current day is in memory.
"""

import math
from bisect import bisect
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from random import Random
from typing import NamedTuple

from app.models import OrderChannel, OrderStatus
from app.seed.calendar import (
    DAYS_PER_YEAR,
    HOUR_WEIGHTS,
    YEARLY_GROWTH,
    OrderDay,
    daily_order_counts,
)
from app.seed.reference import (
    CATEGORIES,
    COUNTRY_WEIGHTS,
    FIRST_NAMES,
    LAST_NAMES,
    PRODUCT_LINES,
)
from app.seed.sampling import WeightedPicker, apportion

# --- Customers ---
# Share of customers who signed up during the year before the history starts,
# so the first days of the history already have customers to order.
EARLY_CUSTOMER_SHARE = 0.15
# A Pareto shape of about 1.16 is the classic 80/20 rule. Weights are capped
# so that no single customer dominates a country's numbers.
ACTIVITY_PARETO_SHAPE = 1.16
MAX_ACTIVITY = 60.0

# --- Products ---
# Zipf exponent of product popularity: the best seller sells about twice as
# often as the second, three times as often as the third, and so on.
POPULARITY_EXPONENT = 1.0

# --- Orders ---
ITEM_COUNT_WEIGHTS = {1: 35, 2: 30, 3: 18, 4: 10, 5: 7}  # mean of about 2.2 products
QUANTITY_WEIGHTS = {1: 80, 2: 13, 3: 5, 4: 2}
REFUND_RATE = 0.03
CANCELLATION_RATE = 0.02
MOBILE_SHARE_AT_START = 0.25
MOBILE_SHARE_AT_END = 0.45
MARKETPLACE_SHARE = 0.15

SECONDS_PER_HOUR = 3_600


@dataclass(frozen=True, slots=True)
class SeedScale:
    name: str
    customers: int
    products: int
    orders: int

    def __post_init__(self) -> None:
        # Fewer products than the largest order could never fill that order
        # with distinct products, and the item loop would never finish.
        if self.customers < 1 or self.products < max(ITEM_COUNT_WEIGHTS) or self.orders < 0:
            raise ValueError(
                f"a scale needs at least 1 customer, {max(ITEM_COUNT_WEIGHTS)} products "
                "and a non-negative number of orders"
            )


SCALES = {
    scale.name: scale
    for scale in (
        SeedScale("small", customers=2_000, products=100, orders=50_000),
        SeedScale("full", customers=50_000, products=1_000, orders=2_000_000),
    )
}


class CustomerRow(NamedTuple):
    id: int
    name: str
    email: str
    country: str
    signed_up_at: datetime


class ProductRow(NamedTuple):
    id: int
    name: str
    category: str
    price_cents: int


class OrderRow(NamedTuple):
    id: int
    customer_id: int
    status: str
    channel: str
    total_cents: int
    created_at: datetime


class OrderItemRow(NamedTuple):
    order_id: int
    product_id: int
    quantity: int
    unit_price_cents: int


class GeneratedOrder(NamedTuple):
    order: OrderRow
    items: list[OrderItemRow]


@dataclass(frozen=True, slots=True)
class SalesData:
    """Generated rows. ``orders`` is lazy and can be consumed only once."""

    customers: list[CustomerRow]
    products: list[ProductRow]
    orders: Iterator[GeneratedOrder]


def generate_sales_data(scale: SeedScale, seed: int, end_date: date) -> SalesData:
    """Generate a scale's rows for a history of three years ending before ``end_date``."""
    rng = Random(seed)
    calendar = daily_order_counts(end_date, scale.orders)
    history_start = calendar[0].day
    customers, activity = _generate_customers(rng, scale.customers, history_start, end_date)
    products, popularity = _generate_products(rng, scale.products)
    orders = _generate_orders(
        rng,
        calendar=calendar,
        customers=customers,
        customer_picker=WeightedPicker(customers, activity),
        product_picker=WeightedPicker(products, popularity),
    )
    return SalesData(customers, products, orders)


def _generate_customers(
    rng: Random, count: int, history_start: date, end_date: date
) -> tuple[list[CustomerRow], list[float]]:
    """Customers in signup order (ids grow with signup time) and their activity weights."""
    start = _midnight(history_start)
    history_years = (end_date - history_start).days / DAYS_PER_YEAR
    signups = sorted(_signup_time(rng, start, history_years) for _ in range(count))
    country_picker = WeightedPicker(list(COUNTRY_WEIGHTS), list(COUNTRY_WEIGHTS.values()))

    customers: list[CustomerRow] = []
    activity: list[float] = []
    for customer_id, signed_up_at in enumerate(signups, start=1):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        customers.append(
            CustomerRow(
                id=customer_id,
                name=f"{first} {last}",
                # The id keeps emails unique; example.com is reserved for examples.
                email=f"{first}.{last}.{customer_id}@example.com".lower(),
                country=country_picker.pick(rng),
                signed_up_at=signed_up_at,
            )
        )
        activity.append(min(rng.paretovariate(ACTIVITY_PARETO_SHAPE), MAX_ACTIVITY))
    return customers, activity


def _signup_time(rng: Random, history_start: datetime, history_years: float) -> datetime:
    if rng.random() < EARLY_CUSTOMER_SHARE:
        years = -rng.random()
    else:
        # Signups grow at the same yearly rate as orders. Inverting the
        # cumulative distribution of an exponentially growing rate turns a
        # uniform draw into a point in time with that shape.
        total_growth = math.pow(YEARLY_GROWTH, history_years) - 1
        years = math.log1p(rng.random() * total_growth) / math.log(YEARLY_GROWTH)
    seconds = round(years * DAYS_PER_YEAR * 86_400)
    return history_start + timedelta(seconds=seconds)


def _generate_products(rng: Random, count: int) -> tuple[list[ProductRow], list[float]]:
    """Products grouped by category, and their popularity weights."""
    per_category = apportion([category.catalog_share for category in CATEGORIES], count)
    products: list[ProductRow] = []
    for category, category_count in zip(CATEGORIES, per_category, strict=True):
        names = [f"{line} {noun}" for line in PRODUCT_LINES for noun in category.nouns]
        for name in rng.sample(names, category_count):
            price = rng.lognormvariate(math.log(category.median_price), category.price_spread)
            products.append(
                ProductRow(
                    id=len(products) + 1,
                    name=name,
                    category=category.name,
                    # Shelf prices end in .99, and nothing is free.
                    price_cents=max(round(price) * 100 - 1, 99),
                )
            )

    # Popularity ranks are shuffled so best sellers are spread across categories.
    ranks = list(range(1, count + 1))
    rng.shuffle(ranks)
    return products, [1 / math.pow(rank, POPULARITY_EXPONENT) for rank in ranks]


def _generate_orders(
    rng: Random,
    *,
    calendar: list[OrderDay],
    customers: list[CustomerRow],
    customer_picker: WeightedPicker[CustomerRow],
    product_picker: WeightedPicker[ProductRow],
) -> Iterator[GeneratedOrder]:
    hour_picker = WeightedPicker(range(24), HOUR_WEIGHTS)
    item_count_picker = WeightedPicker(list(ITEM_COUNT_WEIGHTS), list(ITEM_COUNT_WEIGHTS.values()))
    quantity_picker = WeightedPicker(list(QUANTITY_WEIGHTS), list(QUANTITY_WEIGHTS.values()))
    signups = [customer.signed_up_at for customer in customers]
    order_id = 0

    for day_number, entry in enumerate(calendar):
        day_start = _midnight(entry.day)
        # Only customers who signed up before the day can order on it.
        signed_up = bisect(signups, day_start)
        if entry.orders and not signed_up:
            raise ValueError(f"no customer had signed up by {entry.day}")
        mobile_share = MOBILE_SHARE_AT_START + (MOBILE_SHARE_AT_END - MOBILE_SHARE_AT_START) * (
            day_number / len(calendar)
        )
        # Sorted times make order ids grow with created_at, as identity ids do.
        seconds = sorted(
            hour_picker.pick(rng) * SECONDS_PER_HOUR + int(rng.random() * SECONDS_PER_HOUR)
            for _ in range(entry.orders)
        )

        for second in seconds:
            order_id += 1
            customer = customer_picker.pick(rng, among_first=signed_up)
            items = _order_items(rng, order_id, item_count_picker, quantity_picker, product_picker)
            yield GeneratedOrder(
                OrderRow(
                    id=order_id,
                    customer_id=customer.id,
                    status=_status(rng),
                    channel=_channel(rng, mobile_share),
                    total_cents=sum(item.quantity * item.unit_price_cents for item in items),
                    created_at=day_start + timedelta(seconds=second),
                ),
                items,
            )


def _order_items(
    rng: Random,
    order_id: int,
    item_count_picker: WeightedPicker[int],
    quantity_picker: WeightedPicker[int],
    product_picker: WeightedPicker[ProductRow],
) -> list[OrderItemRow]:
    item_count = item_count_picker.pick(rng)
    # An order lists each product once (the primary key is order + product),
    # so draw until the products are distinct. With hundreds of products,
    # repeats are rare and the loop almost always runs item_count times.
    products: dict[int, ProductRow] = {}
    while len(products) < item_count:
        product = product_picker.pick(rng)
        products[product.id] = product
    return [
        OrderItemRow(order_id, product.id, quantity_picker.pick(rng), product.price_cents)
        for product in products.values()
    ]


def _status(rng: Random) -> str:
    draw = rng.random()
    if draw < REFUND_RATE:
        return OrderStatus.REFUNDED.value
    if draw < REFUND_RATE + CANCELLATION_RATE:
        return OrderStatus.CANCELLED.value
    return OrderStatus.PAID.value


def _channel(rng: Random, mobile_share: float) -> str:
    draw = rng.random()
    if draw < mobile_share:
        return OrderChannel.MOBILE.value
    if draw < mobile_share + MARKETPLACE_SHARE:
        return OrderChannel.MARKETPLACE.value
    return OrderChannel.WEB.value


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)
