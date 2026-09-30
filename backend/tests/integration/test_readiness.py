from typing import Any

import pytest
from flask.testing import FlaskClient

from app.logging import REQUEST_ID_HEADER
from tests.conftest import AppFactory
from tests.logs import LogCapture

# Nothing listens on port 1, so connections are refused at once.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://datapilot:datapilot@localhost:1/datapilot_test"
UNREACHABLE_REDIS_URL = "redis://localhost:1/15"


def readiness_error(response: Any) -> dict[str, Any]:
    assert response.status_code == 503
    error: dict[str, Any] = response.get_json()["error"]
    assert error["code"] == "service_unavailable"
    assert error["request_id"] == response.headers[REQUEST_ID_HEADER]
    return error


def test_ready_returns_200_when_database_and_redis_answer(client: FlaskClient) -> None:
    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


def test_ready_returns_503_naming_redis_when_redis_is_unreachable(
    make_app: AppFactory, captured_logs: LogCapture
) -> None:
    client = make_app(redis_url=UNREACHABLE_REDIS_URL).test_client()

    error = readiness_error(client.get("/api/ready"))

    assert error["details"] == [
        {"check": "database", "status": "ok"},
        {"check": "redis", "status": "error"},
    ]
    (warning,) = captured_logs.records("app.services.health")
    assert warning["check"] == "redis"
    assert "ConnectionError" in warning["exc_info"]


def test_ready_returns_503_naming_database_when_database_is_unreachable(
    make_app: AppFactory, captured_logs: LogCapture
) -> None:
    client = make_app(database_url=UNREACHABLE_DATABASE_URL).test_client()

    error = readiness_error(client.get("/api/ready"))

    assert error["details"] == [
        {"check": "database", "status": "error"},
        {"check": "redis", "status": "ok"},
    ]
    (warning,) = captured_logs.records("app.services.health")
    assert warning["check"] == "database"
    assert "OperationalError" in warning["exc_info"]


@pytest.mark.parametrize("path", ["/api/health", "/api/ready"])
def test_probes_are_documented_in_openapi(client: FlaskClient, path: str) -> None:
    operation = client.get("/api/openapi.json").get_json()["paths"][path]["get"]

    assert operation["tags"] == ["system"]
    assert "200" in operation["responses"]


def test_readiness_failure_response_is_documented(client: FlaskClient) -> None:
    doc = client.get("/api/openapi.json").get_json()

    failure = doc["paths"]["/api/ready"]["get"]["responses"]["503"]
    assert failure["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorOut")
