"""A pinned "today" and helpers for the hand-built analytics datasets.

Every analytics test builds a dataset small enough to compute the expected
numbers by hand, and writes that arithmetic next to its assertions.
"""

from datetime import UTC, date, datetime

import pytest

from app import clock

TODAY = date(2026, 3, 15)


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch: pytest.MonkeyPatch) -> date:
    monkeypatch.setattr(clock, "utc_today", lambda: TODAY)
    return TODAY


def at(day: str, clock: str = "12:00:00") -> datetime:
    """A UTC instant from ISO text: ``at("2026-03-14", "23:59:59")``."""
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=UTC)
