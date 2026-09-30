from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session, scoped_session

from app.api.security import current_user
from tests.factories import create_user
from tests.tokens import access_token_for, bearer, refresh_token_for

URL = "/api/auth/me"


def assert_rejected(response: Any, message: str) -> None:
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    error = response.get_json()["error"]
    assert error["code"] == "unauthorized"
    assert error["message"] == message


def test_me_returns_the_user_of_the_access_token(app: Flask, client: FlaskClient) -> None:
    user = create_user(email="ana@datapilot.dev", full_name="Ana Lima")

    response = client.get(URL, headers=bearer(access_token_for(app, user)))

    assert response.status_code == 200
    body = response.get_json()
    assert body == {
        "id": user.id,
        "email": "ana@datapilot.dev",
        "full_name": "Ana Lima",
        "created_at": body["created_at"],
    }
    assert body["created_at"].endswith("Z")


def test_me_without_a_token_returns_401(client: FlaskClient) -> None:
    assert_rejected(client.get(URL), "Authentication is required.")


@pytest.mark.parametrize(
    "authorization",
    ["Bearer not-a-jwt", "Bearer", "Basic YW5hOnNlY3JldA==", "Bearer a.b.c"],
)
def test_me_with_a_malformed_authorization_header_returns_401(
    client: FlaskClient, authorization: str
) -> None:
    response = client.get(URL, headers={"Authorization": authorization})

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_me_with_an_expired_access_token_returns_401(app: Flask, client: FlaskClient) -> None:
    token = access_token_for(app, create_user(), expires_delta=timedelta(seconds=-1))

    assert_rejected(client.get(URL, headers=bearer(token)), "The token has expired.")


def test_me_rejects_a_token_signed_with_another_key(client: FlaskClient) -> None:
    user = create_user()
    now = datetime.now(UTC)
    claims = {
        "sub": str(user.id),
        "type": "access",
        "jti": "forged",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
        "fresh": False,
    }
    forged = pyjwt.encode(claims, "an-attacker-key-of-sufficient-length!", algorithm="HS256")

    assert_rejected(client.get(URL, headers=bearer(forged)), "The token is invalid.")


def test_me_rejects_an_unsigned_token(client: FlaskClient) -> None:
    user = create_user()
    exp = datetime.now(UTC) + timedelta(minutes=5)
    unsigned = pyjwt.encode({"sub": str(user.id), "type": "access", "exp": exp}, None, "none")

    assert_rejected(client.get(URL, headers=bearer(unsigned)), "The token is invalid.")


def test_me_rejects_a_refresh_token_used_as_an_access_token(
    app: Flask, client: FlaskClient
) -> None:
    token = refresh_token_for(app, create_user())

    assert_rejected(client.get(URL, headers=bearer(token)), "The token is invalid.")


def test_me_ignores_an_access_token_sent_as_a_cookie(app: Flask, client: FlaskClient) -> None:
    client.set_cookie("access_token_cookie", access_token_for(app, create_user()))

    assert_rejected(client.get(URL), "Authentication is required.")


def test_me_rejects_the_token_of_a_deleted_user(
    app: Flask, client: FlaskClient, db_session: scoped_session[Session]
) -> None:
    user = create_user()
    token = access_token_for(app, user)
    db_session.delete(user)
    db_session.commit()

    assert_rejected(
        client.get(URL, headers=bearer(token)), "The account for this token no longer exists."
    )


def test_current_user_outside_a_protected_endpoint_is_a_programming_error(app: Flask) -> None:
    with app.test_request_context(), pytest.raises(RuntimeError, match="jwt_required"):
        current_user()


def test_me_is_documented_with_bearer_security(client: FlaskClient) -> None:
    doc = client.get("/api/openapi.json").get_json()

    operation = doc["paths"][URL]["get"]
    assert operation["security"] == [{"bearerAuth": []}]
    assert set(operation["responses"]) >= {"200", "401"}
    assert doc["components"]["securitySchemes"]["bearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Access token from login or refresh, valid for 15 minutes.",
    }
