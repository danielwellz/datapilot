from datetime import UTC, date, datetime

import pytest

from app.services.periods import (
    DayRange,
    MonthRange,
    add_months,
    preceding_days,
    trailing_days,
    trailing_months,
)


def test_trailing_days_end_yesterday_and_include_both_ends() -> None:
    assert trailing_days(date(2026, 3, 15), 7) == DayRange(date(2026, 3, 8), date(2026, 3, 14))


def test_a_one_day_period_is_yesterday() -> None:
    assert trailing_days(date(2026, 3, 1), 1) == DayRange(date(2026, 2, 28), date(2026, 2, 28))


def test_preceding_days_have_the_same_length_and_end_the_day_before() -> None:
    period = DayRange(date(2026, 3, 8), date(2026, 3, 14))

    assert preceding_days(period) == DayRange(date(2026, 3, 1), date(2026, 3, 7))


def test_day_range_bounds_are_half_open_utc_instants() -> None:
    period = DayRange(date(2026, 3, 8), date(2026, 3, 14))

    assert period.start_at == datetime(2026, 3, 8, tzinfo=UTC)
    assert period.end_at == datetime(2026, 3, 15, tzinfo=UTC)


def test_trailing_months_exclude_the_current_month() -> None:
    assert trailing_months(date(2026, 3, 15), 3) == MonthRange(
        first_month=date(2025, 12, 1), last_month=date(2026, 2, 1)
    )


def test_trailing_months_on_the_first_of_january_end_in_december() -> None:
    assert trailing_months(date(2026, 1, 1), 1) == MonthRange(date(2025, 12, 1), date(2025, 12, 1))


@pytest.mark.parametrize(
    ("month", "count", "expected"),
    [
        (date(2026, 3, 1), 0, date(2026, 3, 1)),
        (date(2026, 3, 1), -3, date(2025, 12, 1)),
        (date(2025, 11, 1), 2, date(2026, 1, 1)),
        (date(2026, 1, 1), -24, date(2024, 1, 1)),
    ],
)
def test_add_months_moves_across_year_boundaries(month: date, count: int, expected: date) -> None:
    assert add_months(month, count) == expected
