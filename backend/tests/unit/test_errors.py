from typing import Any

import pytest
from flask import Flask, abort
from flask.testing import FlaskClient
from pydantic import BaseModel, SecretStr, ValidationError
from werkzeug.exceptions import RequestEntityTooLarge

from app import create_app
from app.config import Settings
from app.errors import (
    AppError,
    BadRequest,
    Conflict,
    Forbidden,
    NotFound,
    RateLimited,
    ServiceUnavailable,
    Unauthorized,
    UnsupportedMediaType,
    ValidationFailed,
)
from app.logging import REQUEST_ID_HEADER
from tests.logs import LogCapture


class Credentials(BaseModel):
    email: str
    password: SecretStr
    age: int


INVALID_CREDENTIALS = {"email": "a@b.dev", "password": "hunter2", "age": "old"}

RAISERS: dict[str, AppError] = {
    "bad-request": BadRequest(),
    "unauthorized": Unauthorized(),
    "forbidden": Forbidden(),
    "not-found": NotFound("Order 42 does not exist."),
    "conflict": Conflict(details=[{"field": "email", "reason": "taken"}]),
    "unsupported-media-type": UnsupportedMediaType(),
    "validation-failed": ValidationFailed(),
    "rate-limited": RateLimited(retry_after_seconds=30),
    "service-unavailable": ServiceUnavailable(),
}


@pytest.fixture
def error_app(settings: Settings) -> Flask:
    app = create_app(settings)

    @app.get("/raise/<name>")
    def raise_app_error(name: str) -> str:
        raise RAISERS[name]

    @app.post("/pydantic")
    def raise_pydantic_error() -> str:
        Credentials.model_validate(INVALID_CREDENTIALS)
        return "unreachable"

    @app.post("/client-input")
    def raise_converted_pydantic_error() -> str:
        try:
            Credentials.model_validate(INVALID_CREDENTIALS)
        except ValidationError as error:
            raise ValidationFailed.from_pydantic(error) from error
        return "unreachable"

    @app.get("/crash")
    def crash() -> str:
        raise RuntimeError("database password is hunter2")

    @app.get("/teapot")
    def teapot() -> str:
        abort(418)

    @app.get("/too-large")
    def too_large() -> str:
        raise RequestEntityTooLarge

    return app


@pytest.fixture
def error_client(error_app: Flask) -> FlaskClient:
    return error_app.test_client()


def error_of(response: Any) -> dict[str, Any]:
    """Assert the standard envelope and return its inner error object."""
    assert response.mimetype == "application/json"
    body = response.get_json()
    assert list(body) == ["error"]
    error: dict[str, Any] = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]
    return error


@pytest.mark.parametrize(
    ("name", "status", "code"),
    [
        ("bad-request", 400, "bad_request"),
        ("unauthorized", 401, "unauthorized"),
        ("forbidden", 403, "forbidden"),
        ("not-found", 404, "not_found"),
        ("conflict", 409, "conflict"),
        ("unsupported-media-type", 415, "unsupported_media_type"),
        ("validation-failed", 422, "validation_failed"),
        ("rate-limited", 429, "rate_limited"),
        ("service-unavailable", 503, "service_unavailable"),
    ],
)
def test_app_errors_render_their_status_and_code(
    error_client: FlaskClient, name: str, status: int, code: str
) -> None:
    response = error_client.get(f"/raise/{name}")

    assert response.status_code == status
    error = error_of(response)
    assert error["code"] == code
    assert error["message"]


def test_app_error_uses_a_custom_message_when_given(error_client: FlaskClient) -> None:
    error = error_of(error_client.get("/raise/not-found"))

    assert error["message"] == "Order 42 does not exist."


def test_app_error_includes_its_details(error_client: FlaskClient) -> None:
    error = error_of(error_client.get("/raise/conflict"))

    assert error["details"] == [{"field": "email", "reason": "taken"}]


def test_rate_limited_error_sets_retry_after_header(error_client: FlaskClient) -> None:
    response = error_client.get("/raise/rate-limited")

    assert response.headers["Retry-After"] == "30"


def test_request_id_in_error_body_echoes_the_incoming_header(error_client: FlaskClient) -> None:
    response = error_client.get("/raise/forbidden", headers={REQUEST_ID_HEADER: "trace-123"})

    assert error_of(response)["request_id"] == "trace-123"


def test_converted_pydantic_error_renders_422_without_echoing_input(
    error_client: FlaskClient,
) -> None:
    response = error_client.post("/client-input")

    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "validation_failed"
    assert error["details"] == [
        {
            "loc": ["age"],
            "message": "Input should be a valid integer, unable to parse string as an integer",
            "type": "int_parsing",
        }
    ]
    assert "old" not in response.get_data(as_text=True)


def test_raw_pydantic_error_from_server_code_renders_generic_500(
    error_client: FlaskClient,
) -> None:
    response = error_client.post("/pydantic")

    assert response.status_code == 500
    error = error_of(response)
    assert error["code"] == "internal_error"
    assert error["details"] == []
    body = response.get_data(as_text=True)
    assert "hunter2" not in body
    assert "int_parsing" not in body


def test_raw_pydantic_error_from_server_code_is_logged_as_a_server_error(
    error_client: FlaskClient, captured_logs: LogCapture
) -> None:
    error_client.post("/pydantic", headers={REQUEST_ID_HEADER: "bug-1"})

    (line,) = captured_logs.records("app.errors")
    assert line["level"] == "ERROR"
    assert line["request_id"] == "bug-1"
    assert "ValidationError" in line["exc_info"]


def test_unknown_route_renders_json_404(client: FlaskClient) -> None:
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


def test_wrong_method_renders_json_405_and_keeps_allow_header(error_client: FlaskClient) -> None:
    response = error_client.delete("/crash")

    assert response.status_code == 405
    assert error_of(response)["code"] == "method_not_allowed"
    assert set(response.headers["Allow"].split(", ")) == {"GET", "HEAD", "OPTIONS"}


def test_other_http_exceptions_render_json_with_their_code(error_client: FlaskClient) -> None:
    response = error_client.get("/too-large")

    assert response.status_code == 413
    assert error_of(response)["code"] == "payload_too_large"


def test_http_exceptions_without_a_known_code_fall_back_to_generic_code(
    error_client: FlaskClient,
) -> None:
    response = error_client.get("/teapot")

    assert response.status_code == 418
    assert error_of(response)["code"] == "http_error"


def test_unexpected_exception_renders_generic_500_without_internals(
    error_client: FlaskClient,
) -> None:
    response = error_client.get("/crash")

    assert response.status_code == 500
    error = error_of(response)
    assert error["code"] == "internal_error"
    assert error["details"] == []
    body = response.get_data(as_text=True)
    assert "hunter2" not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body


def test_unexpected_exception_is_logged_with_traceback_and_request_id(
    error_client: FlaskClient, captured_logs: LogCapture
) -> None:
    error_client.get("/crash", headers={REQUEST_ID_HEADER: "crash-1"})

    (line,) = captured_logs.records("app.errors")
    assert line["level"] == "ERROR"
    assert line["request_id"] == "crash-1"
    assert "RuntimeError: database password is hunter2" in line["exc_info"]
