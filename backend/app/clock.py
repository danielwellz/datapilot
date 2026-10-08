"""The current date, behind one function so tests can pin it."""

from datetime import UTC, date, datetime


def utc_today() -> date:
    """Today's calendar date in UTC, the time zone every date in the API uses."""
    return datetime.now(UTC).date()
