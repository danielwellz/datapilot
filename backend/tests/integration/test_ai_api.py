"""The Ask your data endpoints over HTTP.

The read-only role logs in for real here, so it cannot see the rows a test
inserts (they are never committed): answers are checked for their shape, and
the service tests check the numbers.
"""

import importlib
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from pydantic import SecretStr

from app.ai.clients.base import ProviderError, ProviderFailure
from app.ai.examples import EXAMPLE_QUESTIONS
from app.api.spec import spec
from app.models import User
from app.services.ask_history import CURSOR_PURPOSE
from app.services.cursors import CursorSigner
from tests.conftest import AppFactory
from tests.factories import create_ai_query, create_user
from tests.integration.ai.conftest import ScriptedLLMClient, answer
from tests.tokens import access_token_for, bearer

ASK = "/api/ai/ask"
QUESTION = EXAMPLE_QUESTIONS[3].question


@pytest.fixture
def user() -> User:
    return create_user()


@pytest.fixture
def headers(app: Flask, user: User) -> dict[str, str]:
    return bearer(access_token_for(app, user))


@pytest.fixture
def scripted(app: Flask, monkeypatch: pytest.MonkeyPatch) -> list[ScriptedLLMClient]:
    """Replaces every model's client with the scripted clients appended to the list."""
    clients: list[ScriptedLLMClient] = []
    # By module object: the name app.api.ai is the blueprint that package exports.
    module = importlib.import_module("app.api.ai")
    monkeypatch.setattr(module, "create_llm_client", lambda *_args, **_kwargs: clients.pop(0))
    # The app caches one client per model; start this test with none cached.
    monkeypatch.setitem(app.extensions, module._CLIENTS_EXTENSION_KEY, {})
    return clients


def _error(response: Any) -> dict[str, Any]:
    body: dict[str, Any] = response.get_json()["error"]
    return body


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/ai/models"),
        ("GET", "/api/ai/examples"),
        ("POST", ASK),
        ("GET", "/api/ai/history"),
    ],
)
def test_every_ai_endpoint_requires_an_access_token(
    client: FlaskClient, method: str, path: str
) -> None:
    response = client.open(
        path, method=method, json={"question": QUESTION} if method == "POST" else None
    )

    assert response.status_code == 401


def test_models_lists_only_enabled_models_and_the_default(
    client: FlaskClient, headers: dict[str, str]
) -> None:
    response = client.get("/api/ai/models", headers=headers)

    assert response.status_code == 200
    assert response.get_json() == {
        "items": [
            {
                "id": "fake",
                "label": "Demo model (example questions only)",
                "provider": "fake",
                "provider_label": "Demo",
                "default": True,
            }
        ],
        "default_model": "fake",
    }


def test_models_include_a_provider_once_its_key_is_set(make_app: AppFactory, user: User) -> None:
    app = make_app(llm_api_keys={"GROQ_API_KEY": SecretStr("key")})

    body = (
        app.test_client()
        .get("/api/ai/models", headers=bearer(access_token_for(app, user)))
        .get_json()
    )

    assert [item["id"] for item in body["items"]] == [
        "groq-gpt-oss-120b",
        "groq-qwen3.8-27b",
        "fake",
    ]
    assert body["default_model"] == "groq-gpt-oss-120b"
    assert "key" not in str(body)


def test_examples_lists_the_questions_the_demo_model_answers(
    client: FlaskClient, headers: dict[str, str]
) -> None:
    body = client.get("/api/ai/examples", headers=headers).get_json()

    assert body == {"items": [{"question": example.question} for example in EXAMPLE_QUESTIONS]}


def test_ask_answers_an_example_question_with_the_demo_model(
    client: FlaskClient, headers: dict[str, str]
) -> None:
    response = client.post(ASK, headers=headers, json={"question": f"  {QUESTION}  "})

    assert response.status_code == 200
    body = response.get_json()
    assert body["question"] == QUESTION
    assert body["model"] == {
        "id": "fake",
        "label": "Demo model (example questions only)",
        "provider": "fake",
        "provider_label": "Demo",
    }
    assert (body["requested_model"], body["fell_back"], body["repaired"]) == ("fake", False, False)
    assert body["columns"] == [
        {"name": "channel", "type": "string"},
        {"name": "orders", "type": "number"},
    ]
    assert (body["rows"], body["row_count"], body["truncated"]) == ([], 0, False)
    assert body["sql"].startswith("SELECT\n")
    assert body["sql"].endswith("LIMIT 1001")
    assert body["chart"] == "bar"
    assert body["explanation"] == EXAMPLE_QUESTIONS[3].answer.explanation
    assert body["created_at"].endswith("Z")
    assert isinstance(body["id"], int)
    assert isinstance(body["latency_ms"], int)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": "hi"},
        {"question": "   hi   "},
        {"question": "x" * 501},
        {"question": QUESTION, "model": "Groq/GPT"},
        {"question": QUESTION, "temperature": 0},
    ],
)
def test_ask_validates_the_request(
    client: FlaskClient, headers: dict[str, str], payload: dict[str, Any]
) -> None:
    response = client.post(ASK, headers=headers, json=payload)

    assert response.status_code == 422
    assert _error(response)["code"] == "validation_failed"


def test_ask_refuses_a_model_that_is_not_enabled(
    client: FlaskClient, headers: dict[str, str]
) -> None:
    response = client.post(
        ASK, headers=headers, json={"question": QUESTION, "model": "groq-gpt-oss-120b"}
    )

    assert response.status_code == 422
    assert _error(response)["code"] == "model_not_available"


def test_ask_rejection_carries_a_receipt_of_what_happened(
    client: FlaskClient, headers: dict[str, str], scripted: list[ScriptedLLMClient]
) -> None:
    scripted.append(ScriptedLLMClient(answer("SELECT email FROM users")))

    response = client.post(ASK, headers=headers, json={"question": "All the emails please"})

    assert response.status_code == 422
    error = _error(response)
    assert error["code"] == "sql_rejected"
    (detail,) = error["details"]
    assert detail["sql"] == "SELECT email FROM users"
    assert (detail["model"], detail["provider"], detail["reason"]) == (
        "fake",
        "fake",
        "forbidden_table",
    )
    assert isinstance(detail["audit_id"], int)


def test_ask_reports_provider_rate_limits_with_retry_after(
    client: FlaskClient, headers: dict[str, str], scripted: list[ScriptedLLMClient]
) -> None:
    scripted.append(ScriptedLLMClient(ProviderError(ProviderFailure.RATE_LIMITED, retry_after=90)))

    response = client.post(ASK, headers=headers, json={"question": QUESTION})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "90"
    assert _error(response)["code"] == "llm_rate_limited"


@pytest.mark.usefixtures("pinned_rate_limit_clock")
def test_ask_enforces_the_per_user_rate_limit(make_app: AppFactory, user: User) -> None:
    app = make_app(ai_rate_limit_per_minute=1)
    client = app.test_client()
    headers = bearer(access_token_for(app, user))
    assert client.post(ASK, headers=headers, json={"question": QUESTION}).status_code == 200

    response = client.post(ASK, headers=headers, json={"question": QUESTION})

    assert response.status_code == 429
    assert _error(response)["code"] == "rate_limited"
    assert response.headers["Retry-After"] == "60"


def test_history_pages_through_the_users_questions_newest_first(
    client: FlaskClient, headers: dict[str, str], user: User
) -> None:
    first = create_ai_query(user, question="First?")
    rejected = create_ai_query(
        user,
        question="Second?",
        status="rejected",
        error_code="sql_rejected",
        generated_sql="DELETE FROM v_orders",
        executed_sql=None,
        row_count=None,
    )
    third = create_ai_query(user, question="Third?")
    create_ai_query(create_user(), question="Someone else's")

    page = client.get("/api/ai/history?limit=2", headers=headers).get_json()
    rest = client.get(
        f"/api/ai/history?limit=2&cursor={page['next_cursor']}", headers=headers
    ).get_json()

    assert [item["id"] for item in page["items"]] == [third.id, rejected.id]
    assert [item["id"] for item in rest["items"]] == [first.id]
    assert rest["next_cursor"] is None
    item = page["items"][1]
    assert (item["status"], item["error_code"], item["sql"]) == (
        "rejected",
        "sql_rejected",
        "DELETE FROM v_orders",
    )
    assert page["items"][0]["sql"] == third.executed_sql
    assert page["items"][0]["created_at"].endswith("Z")


def test_history_includes_questions_asked_through_the_api(
    client: FlaskClient, headers: dict[str, str]
) -> None:
    client.post(ASK, headers=headers, json={"question": QUESTION})

    (item,) = client.get("/api/ai/history", headers=headers).get_json()["items"]

    assert (item["question"], item["status"], item["model"]) == (QUESTION, "ok", "fake")


@pytest.mark.parametrize("cursor", ["garbage", "eyJ2IjoxfQ.AAAA"])
def test_history_refuses_a_cursor_it_did_not_issue(
    client: FlaskClient, headers: dict[str, str], cursor: str
) -> None:
    response = client.get(f"/api/ai/history?cursor={cursor}", headers=headers)

    assert response.status_code == 400
    assert _error(response)["code"] == "invalid_cursor"


def test_history_refuses_a_signed_cursor_with_the_wrong_shape(
    client: FlaskClient, headers: dict[str, str], app: Flask
) -> None:
    signer = CursorSigner(app.config["SECRET_KEY"].encode(), CURSOR_PURPOSE)
    naive = signer.sign(b'{"v": 1, "created_at": "2026-10-01T12:00:00", "id": 1}')
    future = signer.sign(b'{"v": 2, "created_at": "2026-10-01T12:00:00Z", "id": 1}')

    for cursor in (naive, future):
        response = client.get(f"/api/ai/history?cursor={cursor}", headers=headers)
        assert response.status_code == 400


@pytest.mark.parametrize("limit", ["0", "51", "x"])
def test_history_bounds_the_page_size(
    client: FlaskClient, headers: dict[str, str], limit: str
) -> None:
    assert client.get(f"/api/ai/history?limit={limit}", headers=headers).status_code == 422


def test_ai_endpoints_are_in_the_openapi_document(client: FlaskClient) -> None:
    vars(spec).pop("_spec", None)
    try:
        paths = client.get("/api/openapi.json").get_json()["paths"]
    finally:
        vars(spec).pop("_spec", None)

    assert {"/api/ai/models", "/api/ai/examples", "/api/ai/ask", "/api/ai/history"} <= set(paths)
    responses = paths["/api/ai/ask"]["post"]["responses"]
    assert {"200", "422", "429", "502", "503"} <= set(responses)
