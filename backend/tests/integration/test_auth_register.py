from typing import Any

import pytest
from flask.testing import FlaskClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, scoped_session

from app.models import User
from app.repositories.users import UserRepository
from app.schemas.auth import UserCreate
from app.services.auth import AuthService, EmailAlreadyRegistered
from app.services.passwords import PasswordHasher
from tests.factories import create_user

URL = "/api/auth/register"
PAYLOAD: dict[str, Any] = {
    "email": "Ana@DataPilot.dev",
    "full_name": "Ana Lima",
    "password": "correct horse battery",
}


def test_register_creates_the_user_and_returns_201(
    client: FlaskClient, db_session: scoped_session[Session]
) -> None:
    response = client.post(URL, json=PAYLOAD)

    assert response.status_code == 201
    body = response.get_json()
    assert set(body) == {"id", "email", "full_name", "created_at"}
    assert body["email"] == "ana@datapilot.dev"
    assert body["full_name"] == "Ana Lima"
    assert body["created_at"].endswith("Z")
    user = db_session.scalars(select(User).where(User.id == body["id"])).one()
    assert user.email == "ana@datapilot.dev"


def test_register_stores_an_argon2_hash_and_never_the_password(
    client: FlaskClient, db_session: scoped_session[Session]
) -> None:
    body = client.post(URL, json=PAYLOAD).get_data(as_text=True)

    user = db_session.scalars(select(User)).one()
    assert user.password_hash.startswith("$argon2id$")
    assert PasswordHasher().verify(user.password_hash, PAYLOAD["password"])
    assert PAYLOAD["password"] not in body
    assert "argon2" not in body


def test_register_returns_409_when_the_email_exists_in_any_case(client: FlaskClient) -> None:
    create_user(email="ana@datapilot.dev")

    response = client.post(URL, json=PAYLOAD | {"email": "ANA@datapilot.dev"})

    assert response.status_code == 409
    error = response.get_json()["error"]
    assert error["code"] == "conflict"
    assert error["message"] == "An account with this email address already exists."
    assert error["details"] == [{"field": "email"}]


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"email": "not-an-email"}, "email"),
        ({"password": "too-short"}, "password"),
        ({"password": "ana@datapilot.dev"}, "password"),
        ({"full_name": " "}, "full_name"),
        ({"role": "admin"}, "role"),
    ],
)
def test_register_rejects_invalid_input_with_422(
    client: FlaskClient, override: dict[str, str], field: str
) -> None:
    response = client.post(URL, json=PAYLOAD | override)

    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["code"] == "validation_failed"
    assert [detail["loc"] for detail in error["details"]] == [[field]]


def test_register_does_not_echo_a_rejected_password(client: FlaskClient) -> None:
    response = client.post(URL, json=PAYLOAD | {"password": "tiny-pw"})

    assert response.status_code == 422
    assert "tiny-pw" not in response.get_data(as_text=True)


def test_register_is_limited_to_10_per_hour_per_client_address(client: FlaskClient) -> None:
    for n in range(10):
        response = client.post(URL, json=PAYLOAD | {"email": f"user{n}@datapilot.dev"})
        assert response.status_code == 201

    blocked = client.post(URL, json=PAYLOAD | {"email": "user10@datapilot.dev"})
    other_address = client.post(
        URL,
        json=PAYLOAD | {"email": "user11@datapilot.dev"},
        environ_base={"REMOTE_ADDR": "203.0.113.7"},
    )

    assert blocked.status_code == 429
    assert blocked.get_json()["error"]["code"] == "rate_limited"
    assert 0 < int(blocked.headers["Retry-After"]) <= 3600
    assert other_address.status_code == 201


def test_register_reports_a_conflict_when_a_concurrent_insert_wins(
    db_session: scoped_session[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    create_user(email="ana@datapilot.dev")
    # Simulate the race: the lookup ran before the other registration committed.
    monkeypatch.setattr(UserRepository, "get_by_email", lambda _self, _email: None)
    service = AuthService(db_session(), PasswordHasher())

    with pytest.raises(EmailAlreadyRegistered):
        service.register(UserCreate.model_validate(PAYLOAD))


def test_register_reraises_integrity_errors_other_than_a_duplicate_email(
    db_session: scoped_session[Session],
) -> None:
    service = AuthService(db_session(), PasswordHasher())
    # Bypasses validation to break the lowercase check constraint instead.
    data = UserCreate.model_construct(
        email="Ana@DataPilot.dev", full_name="Ana Lima", password=SecretStr("correct horse battery")
    )

    with pytest.raises(IntegrityError, match="ck_users_email_lowercase"):
        service.register(data)
