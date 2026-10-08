"""The real provider clients, run against a mock HTTP transport.

No test reaches a provider: each client gets an httpx2 client whose
transport is a function, so the tests see the exact requests the SDKs send
and choose every response, including the failures that drive fallback.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app.ai.clients.anthropic import AnthropicClient
from app.ai.clients.base import (
    InvalidModelOutputError,
    ProviderError,
    ProviderFailure,
    TextReplyClient,
    TokenUsage,
)
from app.ai.clients.factory import CLIENT_BUILDERS, create_llm_client
from app.ai.clients.fake import FakeLLMClient
from app.ai.clients.openai_compatible import OpenAICompatibleClient, retry_after_seconds
from app.ai.prompt import build_prompt
from app.ai.registry import ProviderConfig, ProviderType, RegisteredModel

API_KEY = "test-provider-key-do-not-leak"
ANSWER = {
    "sql": "SELECT count(*) AS orders FROM v_orders",
    "explanation": "All orders.",
    "chart": "none",
    "assumptions": [],
}
PROMPT = build_prompt("How many orders?", "v_orders: One row per order.")

Handler = Callable[[httpx2.Request], httpx2.Response]


class Transport:
    """Answers requests from a list of responses (or exceptions), recording each request."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self._responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(request.content) for request in self.requests]


def _model(
    provider_type: ProviderType, *, json_schema: bool = True, api_key: str | None = API_KEY
) -> RegisteredModel:
    config: dict[str, Any] = {"type": provider_type, "label": "Test"}
    if provider_type is ProviderType.OPENAI_COMPATIBLE:
        config["base_url"] = "https://llm.example/v1"
    if provider_type is not ProviderType.FAKE:
        config["api_key_env"] = "TEST_API_KEY"
    provider = ProviderConfig.model_validate(config)
    return RegisteredModel(
        id="test-model",
        label="Test model",
        provider_id="test",
        provider=provider,
        provider_model="vendor/model-1",
        json_schema=json_schema,
        api_key=SecretStr(api_key) if api_key else None,
    )


def _completion(content: str | None, *, finish_reason: str = "stop") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 1,
            "model": "vendor/model-1",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": content, "refusal": None},
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        },
    )


def _message(text: str, *, stop_reason: str = "end_turn") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "vendor/model-1",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": text},
            ],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 200, "output_tokens": 40},
        },
    )


def _error(status: int, *, headers: dict[str, str] | None = None) -> httpx2.Response:
    body = {"error": {"type": "error", "message": f"status {status}"}}
    return httpx2.Response(status, json=body, headers=headers)


def _openai_client(
    transport: Transport, *, sleeps: list[float] | None = None, **model: Any
) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        _model(ProviderType.OPENAI_COMPATIBLE, **model),
        timeout_seconds=5,
        max_output_tokens=4096,
        http_client=httpx2.Client(transport=httpx2.MockTransport(transport)),
        sleep=(sleeps if sleeps is not None else []).append,
    )


def _anthropic_client(
    transport: Transport, *, sleeps: list[float] | None = None, **model: Any
) -> AnthropicClient:
    return AnthropicClient(
        _model(ProviderType.ANTHROPIC, **model),
        timeout_seconds=5,
        max_output_tokens=4096,
        http_client=httpx2.Client(transport=httpx2.MockTransport(transport)),
        sleep=(sleeps if sleeps is not None else []).append,
    )


# --- OpenAI-compatible ---------------------------------------------------


def test_openai_compatible_request_uses_the_registry_model_and_asks_for_json() -> None:
    transport = Transport(_completion(json.dumps(ANSWER)))

    result = _openai_client(transport).answer(PROMPT)

    (request,) = transport.requests
    assert str(request.url) == "https://llm.example/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    body = transport.bodies()[0]
    assert body["model"] == "vendor/model-1"
    assert body["max_completion_tokens"] == 4096
    assert body["messages"][0] == {"role": "system", "content": PROMPT.system}
    assert body["messages"][-1]["content"] == "<question>\nHow many orders?\n</question>"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "tools" not in body
    assert result.answer.sql == ANSWER["sql"]
    assert result.usage == TokenUsage(120, 30)


def test_openai_compatible_omits_the_schema_for_models_without_schema_support() -> None:
    transport = Transport(_completion(json.dumps(ANSWER)))

    _openai_client(transport, json_schema=False).answer(PROMPT)

    assert "response_format" not in transport.bodies()[0]


def test_openai_compatible_sends_a_placeholder_key_to_keyless_servers() -> None:
    transport = Transport(_completion(json.dumps(ANSWER)))

    _openai_client(transport, api_key=None).answer(PROMPT)

    assert transport.requests[0].headers["authorization"] == "Bearer no-key-needed"


def test_openai_compatible_retries_an_unusable_reply_once_with_the_problem() -> None:
    transport = Transport(_completion("Here you go: SELECT 1"), _completion(json.dumps(ANSWER)))

    result = _openai_client(transport).answer(PROMPT)

    second = transport.bodies()[1]["messages"]
    assert second[-2] == {"role": "assistant", "content": "Here you go: SELECT 1"}
    assert "does not contain the JSON answer object" in second[-1]["content"]
    assert result.usage == TokenUsage(240, 60)


def test_openai_compatible_gives_up_after_a_second_unusable_reply() -> None:
    transport = Transport(_completion(None, finish_reason="length"), _completion("{}"))

    with pytest.raises(InvalidModelOutputError):
        _openai_client(transport).answer(PROMPT)

    assert len(transport.requests) == 2


def test_openai_compatible_reports_a_content_filter_as_a_refusal() -> None:
    transport = Transport(_completion("", finish_reason="content_filter"))

    with pytest.raises(InvalidModelOutputError, match="declined to answer"):
        _openai_client(transport).answer(PROMPT)


def test_openai_compatible_treats_a_reply_without_choices_as_a_server_error() -> None:
    empty = httpx2.Response(
        200,
        json={"id": "x", "object": "chat.completion", "created": 1, "model": "m", "choices": []},
    )
    transport = Transport(empty, empty)

    with pytest.raises(ProviderError) as caught:
        _openai_client(transport).answer(PROMPT)

    assert caught.value.failure is ProviderFailure.SERVER_ERROR


@pytest.mark.parametrize(
    ("response", "failure"),
    [
        (_error(401), ProviderFailure.AUTHENTICATION),
        (_error(403), ProviderFailure.AUTHENTICATION),
        (_error(404), ProviderFailure.MODEL_UNAVAILABLE),
        (_error(400), ProviderFailure.REQUEST_REJECTED),
        (_error(422), ProviderFailure.REQUEST_REJECTED),
    ],
)
def test_openai_compatible_maps_refusals_of_the_request_without_retrying(
    response: httpx2.Response, failure: ProviderFailure
) -> None:
    transport = Transport(response)

    with pytest.raises(ProviderError) as caught:
        _openai_client(transport).answer(PROMPT)

    assert caught.value.failure is failure
    assert len(transport.requests) == 1


def test_openai_compatible_does_not_retry_a_rate_limit_and_reports_retry_after() -> None:
    transport = Transport(_error(429, headers={"retry-after": "12"}))

    with pytest.raises(ProviderError) as caught:
        _openai_client(transport).answer(PROMPT)

    assert caught.value.failure is ProviderFailure.RATE_LIMITED
    assert caught.value.retry_after == 12.0
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("first", "failure"),
    [
        (_error(503), ProviderFailure.SERVER_ERROR),
        (httpx2.ReadTimeout("slow"), ProviderFailure.TIMEOUT),
        (httpx2.ConnectError("refused"), ProviderFailure.CONNECTION),
    ],
)
def test_openai_compatible_retries_a_transient_failure_once(
    first: httpx2.Response | Exception, failure: ProviderFailure
) -> None:
    sleeps: list[float] = []
    recovered = Transport(first, _completion(json.dumps(ANSWER)))

    assert _openai_client(recovered, sleeps=sleeps).answer(PROMPT).answer.sql == ANSWER["sql"]
    assert sleeps == [0.5]

    second = first if isinstance(first, Exception) else _error(first.status_code)
    failing = Transport(first, second)
    with pytest.raises(ProviderError) as caught:
        _openai_client(failing).answer(PROMPT)
    assert caught.value.failure is failure
    assert len(failing.requests) == 2


def test_provider_errors_never_carry_the_api_key() -> None:
    transport = Transport(_error(401))

    with pytest.raises(ProviderError) as caught:
        _openai_client(transport).answer(PROMPT)

    assert API_KEY not in str(caught.value)
    assert API_KEY not in repr(caught.value)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"retry-after": "7"}, 7.0),
        ({"retry-after": "0.5"}, 0.5),
        ({"retry-after": "-3"}, 0.0),
        ({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
        ({}, None),
    ],
)
def test_retry_after_is_read_in_seconds(headers: dict[str, str], expected: float | None) -> None:
    assert retry_after_seconds(httpx2.Response(429, headers=headers)) == expected


# --- Anthropic -------------------------------------------------------------


def test_anthropic_request_uses_the_messages_api_with_json_schema_output() -> None:
    transport = Transport(_message(json.dumps(ANSWER)))

    result = _anthropic_client(transport).answer(PROMPT)

    (request,) = transport.requests
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == API_KEY
    body = transport.bodies()[0]
    assert body["model"] == "vendor/model-1"
    assert body["max_tokens"] == 4096
    assert body["system"] == PROMPT.system
    assert [message["role"] for message in body["messages"]][-2:] == ["assistant", "user"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "tools" not in body
    assert result.answer.sql == ANSWER["sql"]
    assert result.usage == TokenUsage(200, 40)


def test_anthropic_omits_the_schema_for_models_without_schema_support() -> None:
    transport = Transport(_message(json.dumps(ANSWER)))

    _anthropic_client(transport, json_schema=False).answer(PROMPT)

    assert "output_config" not in transport.bodies()[0]


def test_anthropic_refusal_is_invalid_output_and_not_retried() -> None:
    transport = Transport(_message("", stop_reason="refusal"))

    with pytest.raises(InvalidModelOutputError, match="declined to answer"):
        _anthropic_client(transport).answer(PROMPT)

    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    ("response", "failure", "requests"),
    [
        (_error(429, headers={"retry-after": "30"}), ProviderFailure.RATE_LIMITED, 1),
        (_error(529), ProviderFailure.SERVER_ERROR, 2),
        (_error(500), ProviderFailure.SERVER_ERROR, 2),
        (_error(404), ProviderFailure.MODEL_UNAVAILABLE, 1),
        (_error(401), ProviderFailure.AUTHENTICATION, 1),
        (_error(400), ProviderFailure.REQUEST_REJECTED, 1),
        (httpx2.ReadTimeout("slow"), ProviderFailure.TIMEOUT, 2),
        (httpx2.ConnectError("refused"), ProviderFailure.CONNECTION, 2),
    ],
)
def test_anthropic_maps_provider_failures(
    response: httpx2.Response | Exception, failure: ProviderFailure, requests: int
) -> None:
    transport = Transport(response, response)

    with pytest.raises(ProviderError) as caught:
        _anthropic_client(transport).answer(PROMPT)

    assert caught.value.failure is failure
    assert len(transport.requests) == requests
    if failure is ProviderFailure.RATE_LIMITED:
        assert caught.value.retry_after == 30.0


def test_anthropic_client_needs_a_key() -> None:
    with pytest.raises(ValueError, match="needs an API key"):
        AnthropicClient(
            _model(ProviderType.ANTHROPIC, api_key=None), timeout_seconds=5, max_output_tokens=1
        )


# --- Factory ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider_type", "client_type"),
    [
        (ProviderType.FAKE, FakeLLMClient),
        (ProviderType.OPENAI_COMPATIBLE, OpenAICompatibleClient),
        (ProviderType.ANTHROPIC, AnthropicClient),
    ],
)
def test_factory_builds_the_client_for_the_provider_type(
    provider_type: ProviderType, client_type: type
) -> None:
    model = _model(provider_type, api_key=None if provider_type is ProviderType.FAKE else API_KEY)

    client = create_llm_client(model, timeout_seconds=5, max_output_tokens=10)

    assert isinstance(client, client_type)


def test_text_reply_clients_share_the_retry_logic() -> None:
    assert issubclass(OpenAICompatibleClient, TextReplyClient)
    assert issubclass(AnthropicClient, TextReplyClient)


def test_every_provider_type_has_a_client_builder() -> None:
    assert set(CLIENT_BUILDERS) == set(ProviderType)
