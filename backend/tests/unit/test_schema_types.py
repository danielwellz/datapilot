from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.schemas.types import Money


class Priced(BaseModel):
    amount: Money


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("1234.5"), "1234.50"),
        (Decimal("0"), "0.00"),
        (Decimal("19.90"), "19.90"),
        (Decimal("99999999.99"), "99999999.99"),
    ],
)
def test_money_serializes_as_a_string_with_two_decimal_places(
    amount: Decimal, expected: str
) -> None:
    assert Priced(amount=amount).model_dump(mode="json") == {"amount": expected}


def test_money_stays_a_decimal_in_python_mode() -> None:
    assert Priced(amount=Decimal("5.10")).model_dump() == {"amount": Decimal("5.10")}


def test_money_is_documented_as_a_decimal_string() -> None:
    schema = Priced.model_json_schema()["properties"]["amount"]

    assert schema["type"] == "string"
    assert schema["examples"] == ["1234.50"]
