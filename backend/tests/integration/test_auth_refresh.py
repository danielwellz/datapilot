from datetime import timedelta
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from flask_jwt_extended import decode_token
from sqlalchemy.orm import Session, scoped_session

from app.api import security
from app.models import User
from tests.cookies import CSRF_COOKIE, REFRESH_COOKIE, set_cookie
from tests.factories import DEFAULT_PASSWORD, create_user
from tests.logs import LogCapture
from tests.tokens import access_token_for, bearer, refresh_token_for

URL = "/api/auth/refresh"


@pytest.fixture
def user() -> User:
    return create_user(email="ana@datapilot.dev")


def log_in(client: FlaskClient) -> str:
    """Log in and return the refresh token the response set."""
    response = client.post(
        "/api/auth/login", json={"email": "ana@datapilot.dev", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200
    return set_cookie(response, REFRESH_COOKIE).value


def refresh_with(client: FlaskClient, app: Flask, token: str, csrf: str | None = None) -> Any:
    """Refresh with exactly this token and its matching CSRF value, unless one is given."""
    client.set_cookie(REFRESH_COOKIE, token, path="/api/auth")
    header = csrf if csrf is not None else claims_of(app, token)["csrf"]
    return client.post(URL, headers={"X-CSRF-TOKEN": header})


def claims_of(app: Flask, token: str) -> dict[str, Any]:
    with app.app_context():
        return decode_token(token, allow_expired=True)


def assert_rejected(response: Any, message: str) -> None:
    assert response.status_code == 401
    error = response.get_json()["error"]
    assert error["code"] == "unauthorized"
    assert error["message"] == message


@pytest.mark.usefixtures("user")
def test_refresh_returns_a_new_access_token_and_rotates_the_cookie(
    app: Flask, client: FlaskClient
) -> None:
    old = log_in(client)

    response = refresh_with(client, app, old)

    assert response.status_code == 200
    body = response.get_json()
    assert body["token_type"] == "Bearer"
    assert body["user"]["email"] == "ana@datapilot.dev"
    assert response.headers["Cache-Control"] == "no-store"
    new = set_cookie(response, REFRESH_COOKIE)
    assert new["httponly"] is True
    assert new["path"] == "/api/auth"
    assert new.value != old
    old_claims, new_claims = claims_of(app, old), claims_of(app, new.value)
    assert new_claims["jti"] != old_claims["jti"]
    assert new_claims["fam"] == old_claims["fam"]
    assert set_cookie(response, CSRF_COOKIE).value == new_claims["csrf"]


@pytest.mark.usefixtures("user")
def test_new_access_token_authenticates_requests(app: Flask, client: FlaskClient) -> None:
    access = refresh_with(client, app, log_in(client)).get_json()["access_token"]

    assert client.get("/api/auth/me", headers=bearer(access)).status_code == 200


@pytest.mark.usefixtures("user")
def test_rotated_token_can_refresh_again(app: Flask, client: FlaskClient) -> None:
    second = set_cookie(refresh_with(client, app, log_in(client)), REFRESH_COOKIE).value

    assert refresh_with(client, app, second).status_code == 200


@pytest.mark.usefixtures("user")
def test_replaying_a_rotated_token_revokes_the_whole_family(
    app: Flask, client: FlaskClient, monkeypatch: pytest.MonkeyPatch, captured_logs: LogCapture
) -> None:
    monkeypatch.setattr(security, "REFRESH_REUSE_GRACE_SECONDS", 0)
    stolen = log_in(client)
    latest = set_cookie(refresh_with(client, app, stolen), REFRESH_COOKIE).value

    replay = refresh_with(client, app, stolen)
    legitimate = refresh_with(client, app, latest)

    assert_rejected(replay, "The token has been revoked.")
    assert_rejected(legitimate, "The token has been revoked.")
    (warning,) = captured_logs.records("app.services.refresh_tokens")
    assert warning["token_family"] == claims_of(app, stolen)["fam"]


@pytest.mark.usefixtures("user")
def test_family_revocation_leaves_other_logins_alone(
    app: Flask, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(security, "REFRESH_REUSE_GRACE_SECONDS", 0)
    other_device = log_in(app.test_client())
    stolen = log_in(client)
    refresh_with(client, app, stolen)
    refresh_with(client, app, stolen)

    assert refresh_with(client, app, other_device).status_code == 200


@pytest.mark.usefixtures("user")
def test_concurrent_refreshes_within_the_grace_window_both_succeed(
    app: Flask, client: FlaskClient
) -> None:
    shared = log_in(client)

    first_tab = refresh_with(client, app, shared)
    second_tab = refresh_with(client, app, shared)

    assert first_tab.status_code == 200
    assert second_tab.status_code == 200
    for response in (first_tab, second_tab):
        token = set_cookie(response, REFRESH_COOKIE).value
        assert refresh_with(client, app, token).status_code == 200


@pytest.mark.usefixtures("user")
def test_refresh_without_the_csrf_header_is_forbidden(app: Flask, client: FlaskClient) -> None:
    client.set_cookie(REFRESH_COOKIE, log_in(client), path="/api/auth")

    response = client.post(URL)

    assert response.status_code == 403
    error = response.get_json()["error"]
    assert error["code"] == "forbidden"
    assert "X-CSRF-TOKEN" in error["message"]


@pytest.mark.usefixtures("user")
def test_refresh_with_a_mismatched_csrf_header_is_forbidden(
    app: Flask, client: FlaskClient
) -> None:
    response = refresh_with(client, app, log_in(client), csrf="forged-value")

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"


def test_refresh_without_a_cookie_returns_401(client: FlaskClient) -> None:
    assert_rejected(client.post(URL), "Authentication is required.")


def test_refresh_ignores_a_refresh_token_in_the_authorization_header(
    app: Flask, client: FlaskClient, user: User
) -> None:
    response = client.post(URL, headers=bearer(refresh_token_for(app, user)))

    assert_rejected(response, "Authentication is required.")


def test_refresh_rejects_an_access_token_in_the_refresh_cookie(
    app: Flask, client: FlaskClient, user: User
) -> None:
    # With a matching CSRF header, so the token type is what gets checked.
    response = refresh_with(client, app, access_token_for(app, user))

    assert_rejected(response, "The token is invalid.")


def test_refresh_rejects_a_refresh_token_without_a_family(
    app: Flask, client: FlaskClient, user: User
) -> None:
    token = refresh_token_for(app, user, family=None)

    assert_rejected(refresh_with(client, app, token), "The token has been revoked.")


def test_refresh_rejects_an_expired_refresh_token(
    app: Flask, client: FlaskClient, user: User
) -> None:
    token = refresh_token_for(app, user, expires_delta=timedelta(seconds=-1))

    assert_rejected(refresh_with(client, app, token), "The token has expired.")


def test_refresh_rejects_the_token_of_a_deleted_user(
    app: Flask, client: FlaskClient, user: User, db_session: scoped_session[Session]
) -> None:
    token = refresh_token_for(app, user)
    db_session.delete(user)
    db_session.commit()

    assert_rejected(
        refresh_with(client, app, token), "The account for this token no longer exists."
    )


def test_refresh_is_documented_with_cookie_and_csrf_security(client: FlaskClient) -> None:
    doc = client.get("/api/openapi.json").get_json()

    operation = doc["paths"][URL]["post"]
    assert operation["security"] == [{"refreshCookie": [], "csrfHeader": []}]
    assert {"200", "401", "403"} <= set(operation["responses"])
    schemes = doc["components"]["securitySchemes"]
    assert schemes["refreshCookie"]["in"] == "cookie"
    assert schemes["refreshCookie"]["name"] == "refresh_token_cookie"
    assert schemes["csrfHeader"] == {
        "type": "apiKey",
        "name": "X-CSRF-TOKEN",
        "in": "header",
        "description": "The value of the csrf_refresh_token cookie (double-submit).",
    }
