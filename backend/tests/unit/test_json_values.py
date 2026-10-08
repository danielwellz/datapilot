from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from ipaddress import ip_address
from uuid import UUID

import pytest

from app.ai.executor import to_json_value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (42, 42),
        ("text", "text"),
        (1.25, 1.25),
        (float("inf"), "inf"),
        (float("nan"), "nan"),
        (Decimal("1234.50"), "1234.50"),
        (datetime(2026, 10, 1, 12, tzinfo=timezone(timedelta(hours=2))), "2026-10-01T10:00:00Z"),
        (datetime(2026, 10, 1, 12, tzinfo=UTC), "2026-10-01T12:00:00Z"),
        (datetime(2026, 10, 1, 12), "2026-10-01T12:00:00"),
        (date(2026, 10, 1), "2026-10-01"),
        (time(9, 30), "09:30:00"),
        (timedelta(days=3, hours=4), "P3DT14400S"),
        (timedelta(seconds=1.5), "P0DT1.5S"),
        (-timedelta(days=1), "-P1DT0S"),
        (UUID("12345678-1234-5678-1234-567812345678"), "12345678-1234-5678-1234-567812345678"),
        (b"\x00\xff", "AP8="),
        (memoryview(b"ab"), "YWI="),
        ({"total": Decimal("1.10"), 2: [date(2026, 1, 1)]}, {"total": "1.10", "2": ["2026-01-01"]}),
        ((1, Decimal("2.5")), [1, "2.5"]),
        (ip_address("10.0.0.1"), "10.0.0.1"),
    ],
)
def test_database_values_follow_the_api_json_conventions(value: object, expected: object) -> None:
    assert to_json_value(value) == expected
