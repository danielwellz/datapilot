from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from flask_jwt_extended import decode_token
from redis import Redis

from app.models import User
from tests.cookies import CSRF_COOKIE, REFRESH_COOKIE, set_cookie
from tests.factories import DEFAULT_PASSWORD, create_user
from tests.tokens import bearer

URL = "/api/auth/logout"


@pytest.fixture
def user() -> User:
    return create_user(email="ana@datapilot.dev")


def log_in(client: FlaskClient) -> Any:
    response = client.post(
        "/api/auth/login", json={"email": "ana@datapilot.dev", "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200
    return response


def send_with(client: FlaskClient, app: Flask, url: str, token: str, *, csrf: bool = True) -> Any:
    """POST to ``url`` with exactly this refresh token, and its CSRF header unless told not to."""
    client.set_cookie(REFRESH_COOKIE, token, path="/api/auth")
    with app.app_context():
        headers = {"X-CSRF-TOKEN": decode_token(token)["csrf"]} if csrf else {}
    return client.post(url, headers=headers)


@pytest.mark.usefixtures("user")
def test_logout_returns_204_and_clears_both_cookies(app: Flask, client: FlaskClient) -> None:
    token = set_cookie(log_in(client), REFRESH_COOKIE).value

    response = send_with(client, app, URL, token)

    assert response.status_code == 204
    assert response.get_data() == b""
    # Cleared by overwriting each cookie, on its own path, with an expiry in 1970.
    for name, path in ((REFRESH_COOKIE, "/api/auth"), (CSRF_COOKIE, "/")):
        cookie = set_cookie(response, name)
        assert cookie.value == ""
        assert cookie["path"] == path
        assert "1970" in cookie["expires"]


@pytest.mark.usefixtures("user")
def test_logged_out_refresh_token_is_rejected(app: Flask, client: FlaskClient) -> None:
    token = set_cookie(log_in(client), REFRESH_COOKIE).value
    send_with(client, app, URL, token)

    for url in ("/api/auth/refresh", URL):
        response = send_with(client, app, url, token)
        assert response.status_code == 401
        assert response.get_json()["error"]["message"] == "The token has been revoked."


@pytest.mark.usefixtures("user")
def test_revocation_lasts_as_long_as_the_token_would_have(
    app: Flask, client: FlaskClient, redis_client: Redis
) -> None:
    token = set_cookie(log_in(client), REFRESH_COOKIE).value

    send_with(client, app, URL, token)

    with app.app_context():
        jti = decode_token(token)["jti"]
    ttl = redis_client.ttl(f"auth:refresh:revoked:{jti}")
    assert 7 * 24 * 3600 - 60 < ttl <= 7 * 24 * 3600


@pytest.mark.usefixtures("user")
def test_logout_without_the_csrf_header_is_forbidden_and_revokes_nothing(
    app: Flask, client: FlaskClient
) -> None:
    token = set_cookie(log_in(client), REFRESH_COOKIE).value

    response = send_with(client, app, URL, token, csrf=False)

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"
    assert send_with(client, app, "/api/auth/refresh", token).status_code == 200


def test_logout_without_a_cookie_returns_401(client: FlaskClient) -> None:
    response = client.post(URL)

    assert response.status_code == 401
    assert response.get_json()["error"]["message"] == "Authentication is required."


@pytest.mark.usefixtures("user")
def test_logout_ends_only_its_own_session(app: Flask, client: FlaskClient) -> None:
    other_device = set_cookie(log_in(app.test_client()), REFRESH_COOKIE).value
    token = set_cookie(log_in(client), REFRESH_COOKIE).value

    send_with(client, app, URL, token)

    assert send_with(client, app, "/api/auth/refresh", other_device).status_code == 200


@pytest.mark.usefixtures("user")
def test_access_token_stays_valid_until_it_expires_after_logout(
    app: Flask, client: FlaskClient
) -> None:
    # Documents the stateless trade-off (ADR 0003): the client drops the
    # access token on logout, and the server does not track it.
    login = log_in(client)
    send_with(client, app, URL, set_cookie(login, REFRESH_COOKIE).value)

    response = client.get("/api/auth/me", headers=bearer(login.get_json()["access_token"]))

    assert response.status_code == 200


def test_logout_is_documented_with_cookie_and_csrf_security(client: FlaskClient) -> None:
    operation = client.get("/api/openapi.json").get_json()["paths"][URL]["post"]

    assert operation["security"] == [{"refreshCookie": [], "csrfHeader": []}]
    assert {"204", "401", "403"} <= set(operation["responses"])
