"""How many orders the store receives on each day of its history.

The expected volume of a day is the product of three effects:

    growth (about 25% a year) x month of year x day of week

Each day then gets its share of the requested total, rounded to whole
orders so that the days add up to exactly that total.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

from app.seed.sampling import apportion

HISTORY_YEARS = 3
YEARLY_GROWTH = 1.25
DAYS_PER_YEAR = 365.25

# Holiday shopping peaks in November (Black Friday, Cyber Monday) and
# December, followed by the usual January and February dip.
MONTH_FACTORS = {
    1: 0.80,
    2: 0.82,
    3: 0.92,
    4: 0.94,
    5: 0.97,
    6: 0.93,
    7: 0.90,
    8: 0.94,
    9: 0.98,
    10: 1.04,
    11: 1.40,
    12: 1.55,
}

# Monday is 0, as in date.weekday(). Online stores sell most on Sunday
# evening and Monday, least on Friday and Saturday.
WEEKDAY_FACTORS = (1.08, 1.03, 1.00, 0.98, 0.92, 0.88, 1.11)

# Orders per hour of the day (UTC), with an evening peak.
HOUR_WEIGHTS = (
    # 00-05: night
    *(2, 1, 1, 1, 1, 2),
    # 06-11: morning
    *(3, 4, 5, 6, 6, 7),
    # 12-17: afternoon
    *(8, 7, 6, 6, 7, 8),
    # 18-23: evening peak
    *(10, 11, 11, 9, 6, 4),
)


@dataclass(frozen=True, slots=True)
class OrderDay:
    day: date
    orders: int


def history_start(end_date: date) -> date:
    """First day of the history: ``HISTORY_YEARS`` before ``end_date``.

    A 29 February end date maps to 28 February, the closest real date.
    """
    year = end_date.year - HISTORY_YEARS
    if end_date.month == 2 and end_date.day == 29:
        return date(year, 2, 28)
    return end_date.replace(year=year)


def expected_volume(day: date, start: date) -> float:
    """Relative order volume of ``day``; only ratios between days matter."""
    growth = math.pow(YEARLY_GROWTH, (day - start).days / DAYS_PER_YEAR)
    return growth * MONTH_FACTORS[day.month] * WEEKDAY_FACTORS[day.weekday()]


def daily_order_counts(end_date: date, total_orders: int) -> list[OrderDay]:
    """Spread ``total_orders`` over the days before ``end_date``, oldest first.

    ``end_date`` itself is excluded, so a history ending today never holds
    orders later than the current time.
    """
    start = history_start(end_date)
    days = [start + timedelta(days=offset) for offset in range((end_date - start).days)]
    counts = apportion([expected_volume(day, start) for day in days], total_orders)
    return [OrderDay(day, count) for day, count in zip(days, counts, strict=True)]
