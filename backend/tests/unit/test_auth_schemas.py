from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.auth import UserCreate, UserOut

VALID: dict[str, Any] = {
    "email": "ana@datapilot.dev",
    "full_name": "Ana Lima",
    "password": "long enough password",
}


def errors_of(payload: dict[str, Any]) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        UserCreate.model_validate(payload)
    return [(error["loc"], error["type"]) for error in caught.value.errors()]


def test_email_is_trimmed_and_lowercased() -> None:
    user = UserCreate.model_validate(VALID | {"email": "  Ana@DataPilot.DEV "})

    assert user.email == "ana@datapilot.dev"


def test_full_name_is_trimmed() -> None:
    assert UserCreate.model_validate(VALID | {"full_name": "  Ana Lima "}).full_name == "Ana Lima"


@pytest.mark.parametrize("full_name", ["", "   ", "x" * 101])
def test_full_name_must_be_between_1_and_100_characters(full_name: str) -> None:
    assert errors_of(VALID | {"full_name": full_name})[0][0] == ("full_name",)


def test_invalid_email_is_rejected() -> None:
    assert errors_of(VALID | {"email": "not-an-email"}) == [(("email",), "value_error")]


def test_password_shorter_than_10_characters_is_rejected() -> None:
    assert errors_of(VALID | {"password": "123456789"}) == [(("password",), "password_too_short")]


def test_password_of_exactly_10_characters_is_accepted() -> None:
    assert UserCreate.model_validate(VALID | {"password": "1234567890"})


def test_password_longer_than_128_characters_is_rejected() -> None:
    assert errors_of(VALID | {"password": "x" * 129}) == [(("password",), "password_too_long")]


def test_password_equal_to_the_email_is_rejected_ignoring_case() -> None:
    payload = VALID | {"email": "analyst@datapilot.dev", "password": "Analyst@DataPilot.dev"}

    assert errors_of(payload) == [(("password",), "password_equals_email")]


def test_password_is_hidden_in_the_repr() -> None:
    assert VALID["password"] not in repr(UserCreate.model_validate(VALID))


def test_unknown_fields_are_rejected() -> None:
    assert errors_of(VALID | {"is_admin": True}) == [(("is_admin",), "extra_forbidden")]


def test_user_out_serializes_timestamps_as_utc_with_z_suffix() -> None:
    created = datetime(2026, 9, 30, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    user = UserOut(id=1, email="ana@datapilot.dev", full_name="Ana", created_at=created)

    assert user.model_dump(mode="json")["created_at"] == "2026-09-30T12:00:00Z"


def test_user_out_refuses_to_serialize_a_naive_timestamp() -> None:
    user = UserOut(id=1, email="a@datapilot.dev", full_name="A", created_at=datetime(2026, 9, 30))

    with pytest.raises(ValueError, match="naive datetime"):
        user.model_dump(mode="json")


def test_user_out_keeps_a_utc_timestamp_unchanged() -> None:
    created = datetime(2026, 9, 30, 12, 0, 0, 250_000, tzinfo=UTC)
    user = UserOut(id=1, email="a@datapilot.dev", full_name="A", created_at=created)

    assert user.model_dump(mode="json")["created_at"] == "2026-09-30T12:00:00.250000Z"
