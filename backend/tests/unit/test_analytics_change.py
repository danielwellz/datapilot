from decimal import Decimal

import pytest

from app.services.analytics import change


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        (Decimal("170.00"), Decimal("145.00"), Decimal("0.1724")),
        (2, 3, Decimal("-0.3333")),
        (0, 90, Decimal("-1.0000")),
        (3, 3, Decimal("0.0000")),
        # A change of exactly 0.00125 rounds half away from zero, as round() does in SQL.
        (Decimal("1.00125"), 1, Decimal("0.0013")),
        (Decimal("0.99875"), 1, Decimal("-0.0013")),
    ],
)
def test_change_is_relative_to_the_previous_value_rounded_to_four_places(
    current: Decimal | int, previous: Decimal | int, expected: Decimal
) -> None:
    assert change(current, previous) == expected


@pytest.mark.parametrize(
    ("current", "previous"), [(5, 0), (Decimal(5), Decimal(0)), (None, 3), (3, None)]
)
def test_change_is_unknown_without_a_non_zero_previous_value(
    current: int | Decimal | None, previous: int | Decimal | None
) -> None:
    assert change(current, previous) is None
