from collections import defaultdict
from datetime import date, timedelta

import pytest

from app.seed.calendar import (
    HOUR_WEIGHTS,
    daily_order_counts,
    expected_volume,
    history_start,
)

END_DATE = date(2026, 10, 1)


@pytest.fixture(scope="module")
def days() -> dict[date, int]:
    return {entry.day: entry.orders for entry in daily_order_counts(END_DATE, 2_000_000)}


def test_history_covers_three_years_and_excludes_the_end_date(days: dict[date, int]) -> None:
    assert min(days) == date(2023, 10, 1)
    assert max(days) == END_DATE - timedelta(days=1)
    assert len(days) == (END_DATE - date(2023, 10, 1)).days


def test_history_start_maps_a_leap_day_to_the_last_day_of_february() -> None:
    assert history_start(date(2028, 2, 29)) == date(2025, 2, 28)


def test_daily_counts_add_up_to_exactly_the_requested_total(days: dict[date, int]) -> None:
    assert sum(days.values()) == 2_000_000


@pytest.mark.parametrize("total", [0, 1, 999, 12_345])
def test_daily_counts_add_up_for_small_totals(total: int) -> None:
    assert sum(entry.orders for entry in daily_order_counts(END_DATE, total)) == total


def test_volume_grows_by_about_a_quarter_year_over_year(days: dict[date, int]) -> None:
    last_year = sum(n for day, n in days.items() if day >= date(2025, 10, 1))
    year_before = sum(n for day, n in days.items() if date(2024, 10, 1) <= day < date(2025, 10, 1))

    assert 1.23 < last_year / year_before < 1.27


def test_november_and_december_are_the_busiest_months(days: dict[date, int]) -> None:
    # One full calendar year, so growth within the year is the only skew.
    per_month: dict[int, int] = defaultdict(int)
    for day, orders in days.items():
        if day.year == 2025:
            per_month[day.month] += orders
    daily_average = {month: total / _days_in(2025, month) for month, total in per_month.items()}

    busiest = sorted(daily_average, key=daily_average.__getitem__, reverse=True)
    assert busiest[:2] == [12, 11]
    assert daily_average[12] > 1.4 * daily_average[2]


def test_sunday_outsells_saturday_in_the_same_week() -> None:
    start = date(2025, 3, 2)  # a Sunday
    saturday = start + timedelta(days=6)

    assert expected_volume(start, start) > 1.2 * expected_volume(saturday, start)


def test_hour_weights_cover_the_day_with_an_evening_peak() -> None:
    assert len(HOUR_WEIGHTS) == 24
    assert max(range(24), key=HOUR_WEIGHTS.__getitem__) in range(18, 22)


def _days_in(year: int, month: int) -> int:
    first = date(year, month, 1)
    following = date(year + month // 12, month % 12 + 1, 1)
    return (following - first).days
