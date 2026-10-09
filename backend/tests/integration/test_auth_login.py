from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from argon2 import PasswordHasher as Argon2Hasher
from flask.testing import FlaskClient
from sqlalchemy.orm import Session, scoped_session

from app.api.security import start_session
from app.models import User
from app.services.passwords import PasswordHasher
from tests.conftest import AppFactory
from tests.cookies import CSRF_COOKIE, REFRESH_COOKIE, set_cookie
from tests.factories import DEFAULT_PASSWORD, create_user
from tests.settings import PRODUCTION_SECRETS
from tests.tokens import bearer

URL = "/api/auth/login"
EMAIL = "ana@datapilot.dev"
GENERIC_FAILURE = "Email or password is incorrect."
CLIENT_IP = "198.51.100.1"


def login(
    client: FlaskClient, email: str = EMAIL, password: str = DEFAULT_PASSWORD, ip: str = CLIENT_IP
) -> Any:
    return client.post(
        URL, json={"email": email, "password": password}, environ_base={"REMOTE_ADDR": ip}
    )


def reload(db_session: scoped_session[Session], user: User) -> User:
    """Read the user back as stored; the request's session cleanup detached ``user``."""
    stored = db_session.get(User, user.id)
    assert stored is not None
    return stored


@pytest.fixture
def user() -> User:
    return create_user(email=EMAIL, full_name="Ana Lima")


def test_login_returns_an_access_token_and_the_user(user: User, client: FlaskClient) -> None:
    response = login(client)

    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 15 * 60
    assert body["user"]["id"] == user.id
    assert response.headers["Cache-Control"] == "no-store"


def test_login_access_token_authenticates_requests(user: User, client: FlaskClient) -> None:
    token = login(client).get_json()["access_token"]

    assert client.get("/api/auth/me", headers=bearer(token)).get_json()["id"] == user.id


@pytest.mark.usefixtures("user")
def test_login_sets_an_httponly_strict_refresh_cookie_scoped_to_auth(client: FlaskClient) -> None:
    cookie = set_cookie(login(client), REFRESH_COOKIE)

    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Strict"
    assert cookie["path"] == "/api/auth"
    assert cookie["max-age"] == str(7 * 24 * 3600)
    assert not cookie["secure"]


@pytest.mark.usefixtures("user")
def test_login_sets_a_script_readable_csrf_cookie_for_the_whole_site(client: FlaskClient) -> None:
    response = login(client)
    csrf = set_cookie(response, CSRF_COOKIE)

    assert not csrf["httponly"]
    assert csrf["samesite"] == "Strict"
    assert csrf["path"] == "/"
    assert csrf.value
    assert csrf.value not in response.get_data(as_text=True)


def test_login_cookies_are_secure_in_production(make_app: AppFactory) -> None:
    client = make_app(app_env="production", **PRODUCTION_SECRETS).test_client()
    create_user(email=EMAIL)

    response = login(client)

    assert set_cookie(response, REFRESH_COOKIE)["secure"] is True
    assert set_cookie(response, CSRF_COOKIE)["secure"] is True


def test_login_records_the_login_time(
    user: User, client: FlaskClient, db_session: scoped_session[Session]
) -> None:
    login(client)

    stored = reload(db_session, user)
    assert stored.last_login_at is not None
    assert abs(datetime.now(UTC) - stored.last_login_at) < timedelta(minutes=1)


@pytest.mark.usefixtures("user")
def test_login_ignores_the_case_of_the_email(client: FlaskClient) -> None:
    assert login(client, email="ANA@DataPilot.dev").status_code == 200


@pytest.mark.usefixtures("user")
def test_wrong_password_and_unknown_email_get_identical_answers(client: FlaskClient) -> None:
    wrong_password = login(client, password="not the password")
    unknown_email = login(client, email="nobody@datapilot.dev")

    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert "Set-Cookie" not in response.headers
    wrong_error = wrong_password.get_json()["error"]
    unknown_error = unknown_email.get_json()["error"]
    assert wrong_error["message"] == GENERIC_FAILURE
    assert {**wrong_error, "request_id": None} == {**unknown_error, "request_id": None}


def test_login_with_an_unknown_email_still_spends_a_password_verification(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        PasswordHasher, "verify_against_dummy", lambda _self, password: calls.append(password)
    )

    login(client, email="nobody@datapilot.dev", password="guess-1234")

    assert calls == ["guess-1234"]


def test_login_upgrades_a_hash_made_with_outdated_parameters(
    client: FlaskClient, db_session: scoped_session[Session]
) -> None:
    outdated = PasswordHasher(Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1))
    user = create_user(email=EMAIL, password_hash=outdated.hash(DEFAULT_PASSWORD))
    old_hash = user.password_hash

    assert login(client).status_code == 200

    new_hash = reload(db_session, user).password_hash
    current = PasswordHasher()
    assert new_hash != old_hash
    assert current.needs_rehash(new_hash) is False
    assert current.verify(new_hash, DEFAULT_PASSWORD)


def test_login_keeps_a_current_hash(
    user: User, client: FlaskClient, db_session: scoped_session[Session]
) -> None:
    old_hash = user.password_hash

    login(client)

    assert reload(db_session, user).password_hash == old_hash


@pytest.mark.parametrize(
    "payload",
    [
        {"email": EMAIL},
        {"email": "not-an-email", "password": "x"},
        {"email": EMAIL, "password": "x" * 129},
        {"email": EMAIL, "password": "x", "remember": True},
    ],
)
def test_login_rejects_malformed_input_with_422(client: FlaskClient, payload: Any) -> None:
    response = client.post(URL, json=payload)

    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_failed"


@pytest.mark.usefixtures("user", "pinned_rate_limit_clock")
def test_sixth_attempt_for_one_account_from_one_address_gets_429(client: FlaskClient) -> None:
    for _ in range(5):
        assert login(client, password="wrong password").status_code == 401

    blocked = login(client)  # even the right password is refused now

    assert blocked.status_code == 429
    error = blocked.get_json()["error"]
    assert error["code"] == "rate_limited"
    assert error["message"] == "Too many login attempts for this account. Try again later."
    assert blocked.headers["Retry-After"] == "60"
    assert "Set-Cookie" not in blocked.headers


@pytest.mark.usefixtures("user", "pinned_rate_limit_clock")
def test_account_limit_does_not_block_other_accounts_or_addresses(client: FlaskClient) -> None:
    create_user(email="bruno@datapilot.dev")
    for _ in range(5):
        login(client, password="wrong password")

    assert login(client).status_code == 429
    assert login(client, email="bruno@datapilot.dev").status_code == 200
    assert login(client, ip="198.51.100.2").status_code == 200


@pytest.mark.usefixtures("user", "pinned_rate_limit_clock")
def test_address_limit_stops_spraying_one_password_over_many_emails(client: FlaskClient) -> None:
    for n in range(30):
        assert login(client, email=f"user{n}@datapilot.dev").status_code == 401

    blocked = login(client)
    other_address = login(client, ip="198.51.100.2")

    assert blocked.status_code == 429
    assert blocked.get_json()["error"]["message"] == (
        "Too many login attempts from this address. Try again later."
    )
    assert other_address.status_code == 200


@pytest.mark.usefixtures("user", "pinned_rate_limit_clock")
def test_refused_attempts_spend_no_hashing_time(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for _ in range(5):
        login(client, password="wrong password")
    verified: list[str] = []
    monkeypatch.setattr(
        PasswordHasher, "verify", lambda _self, _hash, password: verified.append(password)
    )

    assert login(client).status_code == 429
    assert verified == []


def test_login_is_documented_with_its_failure_responses(client: FlaskClient) -> None:
    operation = client.get("/api/openapi.json").get_json()["paths"][URL]["post"]

    assert set(operation["responses"]) == {"200", "401", "422", "429"}
    assert "security" not in operation


def test_a_request_that_fails_after_starting_a_session_sets_no_cookie(
    make_app: AppFactory,
) -> None:
    app = make_app()
    user = create_user(email=EMAIL)

    @app.post("/probe/session-then-fail")
    def session_then_fail() -> str:
        start_session(user)
        raise RuntimeError("fails after the tokens were issued")

    response = app.test_client().post("/probe/session-then-fail")

    assert response.status_code == 500
    assert "Set-Cookie" not in response.headers


PROXY_IP = "10.0.0.2"


def _login_via_proxy(client: FlaskClient, forwarded_for: str, email: str = EMAIL) -> Any:
    return client.post(
        URL,
        json={"email": email, "password": DEFAULT_PASSWORD},
        environ_base={"REMOTE_ADDR": PROXY_IP},
        headers={"X-Forwarded-For": forwarded_for},
    )


@pytest.mark.usefixtures("user", "pinned_rate_limit_clock")
def test_behind_a_trusted_proxy_each_client_address_has_its_own_limit(
    make_app: AppFactory,
) -> None:
    client = make_app(trusted_proxy_hops=1).test_client()
    for n in range(30):
        # A client may prepend addresses of its own; only the proxy's hop counts.
        response = _login_via_proxy(client, f"192.0.2.9, {CLIENT_IP}", f"user{n}@datapilot.dev")
        assert response.status_code == 401

    assert _login_via_proxy(client, CLIENT_IP).status_code == 429
    assert _login_via_proxy(client, "198.51.100.2").status_code == 200


@pytest.mark.usefixtures("user", "pinned_rate_limit_clock")
def test_without_trusted_proxies_a_forged_forwarded_address_is_ignored(
    client: FlaskClient,
) -> None:
    for n in range(30):
        response = _login_via_proxy(client, f"198.51.100.{n}", f"user{n}@datapilot.dev")
        assert response.status_code == 401

    assert _login_via_proxy(client, "198.51.100.200").status_code == 429
