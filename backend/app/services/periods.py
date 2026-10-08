"""Reporting periods: whole UTC days and calendar months that end before today.

Only complete periods are reported. Today is still in progress, so a period
that included it would look like a drop against any complete period it is
compared with.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta


@dataclass(frozen=True, slots=True)
class DayRange:
    """Whole UTC days from ``first_day`` to ``last_day``, both included."""

    first_day: date
    last_day: date

    @property
    def start_at(self) -> datetime:
        """The first instant of the range, for half-open SQL bounds."""
        return _utc_midnight(self.first_day)

    @property
    def end_at(self) -> datetime:
        """The first instant after the range."""
        return _utc_midnight(self.last_day + timedelta(days=1))


@dataclass(frozen=True, slots=True)
class MonthRange:
    """Calendar months from ``first_month`` to ``last_month``, both included.

    Each month is represented by its first day.
    """

    first_month: date
    last_month: date


def trailing_days(today: date, days: int) -> DayRange:
    """The ``days`` complete days before ``today``."""
    last_day = today - timedelta(days=1)
    return DayRange(first_day=last_day - timedelta(days=days - 1), last_day=last_day)


def preceding_days(period: DayRange) -> DayRange:
    """The range of equal length that ends the day before ``period`` starts."""
    return trailing_days(period.first_day, (period.last_day - period.first_day).days + 1)


def trailing_months(today: date, months: int) -> MonthRange:
    """The ``months`` complete calendar months before the month of ``today``."""
    last_month = add_months(today.replace(day=1), -1)
    return MonthRange(first_month=add_months(last_month, -(months - 1)), last_month=last_month)


def add_months(month: date, count: int) -> date:
    """The first day of the month ``count`` months after ``month`` (negative goes back)."""
    index = month.year * 12 + month.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def _utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)
