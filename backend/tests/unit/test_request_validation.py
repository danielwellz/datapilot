"""Request validation through spectree, rendered in the standard error envelope.

The endpoints below exist only in these tests, on a dedicated blueprint.
"""

from typing import Any

import pytest
from flask import Blueprint, Flask
from flask.testing import FlaskClient
from pydantic import BaseModel, ConfigDict, Field
from spectree import Response

from app import create_app
from app.api.spec import _raise_request_validation_error, spec
from app.config import Settings
from tests.logs import LogCapture


class ItemQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=100)


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    password: str


class ItemOut(BaseModel):
    name: str
    limit: int


validation_probe = Blueprint("validation_probe", __name__, url_prefix="/api/probe")


@validation_probe.post("/items")
@spec.validate(resp=Response(HTTP_200=ItemOut))
def create_item(query: ItemQuery, json: ItemCreate) -> ItemOut:
    return ItemOut(name=json.name, limit=query.limit)


@validation_probe.get("/broken")
@spec.validate(resp=Response(HTTP_200=ItemOut))
def broken_response() -> Any:
    return {"name": "missing the limit field"}


@pytest.fixture(scope="module")
def probe_client(settings: Settings) -> FlaskClient:
    app: Flask = create_app(settings)
    app.register_blueprint(validation_probe)
    return app.test_client()


def error_of(response: Any) -> dict[str, Any]:
    error: dict[str, Any] = response.get_json()["error"]
    return error


def test_valid_request_reaches_the_endpoint_with_parsed_models(probe_client: FlaskClient) -> None:
    response = probe_client.post("/api/probe/items?limit=5", json={"name": "a", "password": "p"})

    assert response.status_code == 200
    assert response.get_json() == {"name": "a", "limit": 5}


def test_invalid_query_parameter_returns_422_with_field_location(
    probe_client: FlaskClient,
) -> None:
    response = probe_client.post("/api/probe/items?limit=500", json={"name": "a", "password": "p"})

    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "validation_failed"
    assert [(d["loc"], d["type"]) for d in error["details"]] == [(["limit"], "less_than_equal")]


def test_invalid_body_returns_422_without_echoing_submitted_values(
    probe_client: FlaskClient,
) -> None:
    response = probe_client.post("/api/probe/items", json={"name": "", "password": "s3cret-pw"})

    assert response.status_code == 422
    details = error_of(response)["details"]
    assert [(d["loc"], d["type"]) for d in details] == [(["name"], "string_too_short")]
    assert "s3cret-pw" not in response.get_data(as_text=True)


def test_unknown_body_field_is_rejected(probe_client: FlaskClient) -> None:
    response = probe_client.post(
        "/api/probe/items", json={"name": "a", "password": "p", "is_admin": True}
    )

    assert response.status_code == 422
    assert [(d["loc"], d["type"]) for d in error_of(response)["details"]] == [
        (["is_admin"], "extra_forbidden")
    ]


def test_missing_body_returns_422_for_each_required_field(probe_client: FlaskClient) -> None:
    response = probe_client.post("/api/probe/items")

    assert response.status_code == 422
    assert sorted(d["loc"][0] for d in error_of(response)["details"]) == ["name", "password"]


def test_malformed_json_body_returns_400(probe_client: FlaskClient) -> None:
    response = probe_client.post(
        "/api/probe/items", data='{"name": ', content_type="application/json"
    )

    assert response.status_code == 400
    assert error_of(response)["code"] == "bad_request"
    assert error_of(response)["message"] == "The request body is not valid JSON."


def test_non_json_body_returns_415(probe_client: FlaskClient) -> None:
    response = probe_client.post("/api/probe/items", data={"name": "a", "password": "p"})

    assert response.status_code == 415
    assert error_of(response)["code"] == "unsupported_media_type"


def test_body_over_the_size_limit_returns_413(probe_client: FlaskClient) -> None:
    oversized = '{"name": "' + "a" * (1024 * 1024) + '"}'

    response = probe_client.post(
        "/api/probe/items", data=oversized, content_type="application/json"
    )

    assert response.status_code == 413
    assert error_of(response)["code"] == "payload_too_large"


def test_response_that_breaks_its_schema_returns_generic_500_and_is_logged(
    probe_client: FlaskClient, captured_logs: LogCapture
) -> None:
    response = probe_client.get("/api/probe/broken")

    assert response.status_code == 500
    assert error_of(response)["code"] == "internal_error"
    assert "missing the limit field" not in response.get_data(as_text=True)
    (line,) = captured_logs.records("app.errors")
    assert "Response does not match its declared schema" in line["exc_info"]


def test_request_hook_reraises_errors_that_are_not_validation_errors() -> None:
    error = RuntimeError("unexpected failure inside spectree")

    with pytest.raises(RuntimeError, match="unexpected failure"):
        _raise_request_validation_error(None, None, error, None, None)
