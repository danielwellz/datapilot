"""Passwords must never reach the logs or come back in a response."""

from typing import Any

import pytest
from flask.testing import FlaskClient

from tests.factories import DEFAULT_PASSWORD, create_user
from tests.logs import LogCapture

SECRET = "never-log-this-password-9f3a"


def register(email: str, full_name: str = "Ana Lima") -> dict[str, str]:
    return {"email": email, "full_name": full_name, "password": SECRET}


@pytest.mark.parametrize(
    ("url", "payload"),
    [
        ("/api/auth/login", {"email": "ana@datapilot.dev", "password": SECRET}),
        ("/api/auth/login", {"email": "nobody@datapilot.dev", "password": SECRET}),
        ("/api/auth/login", {"email": "not-an-email", "password": SECRET}),
        ("/api/auth/register", register("new@datapilot.dev")),
        ("/api/auth/register", register("ana@datapilot.dev")),
        ("/api/auth/register", register("new@datapilot.dev", full_name="")),
    ],
    ids=[
        "login-wrong-password",
        "login-unknown-email",
        "login-invalid",
        "register",
        "register-duplicate",
        "register-invalid",
    ],
)
def test_password_never_appears_in_logs_or_responses(
    client: FlaskClient, captured_logs: LogCapture, url: str, payload: dict[str, Any]
) -> None:
    create_user(email="ana@datapilot.dev")

    response = client.post(url, json=payload)

    assert captured_logs.records("app.access"), "the request must have been logged"
    assert SECRET not in captured_logs.text
    assert SECRET not in response.get_data(as_text=True)


def test_successful_login_logs_neither_the_password_nor_the_tokens(
    client: FlaskClient, captured_logs: LogCapture
) -> None:
    create_user(email="ana@datapilot.dev")

    response = client.post(
        "/api/auth/login", json={"email": "ana@datapilot.dev", "password": DEFAULT_PASSWORD}
    )

    assert response.status_code == 200
    assert DEFAULT_PASSWORD not in captured_logs.text
    assert response.get_json()["access_token"] not in captured_logs.text
