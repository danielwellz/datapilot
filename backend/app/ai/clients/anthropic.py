"""The native client for Anthropic's Messages API, through the official SDK.

The answer is still requested as JSON in the reply, as for every provider;
JSON-schema output (``output_config.format``) constrains it when the registry
says the model supports that. A refusal (``stop_reason == "refusal"``) is
reported as invalid output: the request is not re-sent elsewhere, because the
same question would usually meet the same decision (ADR 0007).
"""

import time
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2

from app.ai.answer import ANSWER_JSON_SCHEMA
from app.ai.clients.base import ProviderError, ProviderFailure, Reply, TextReplyClient, TokenUsage
from app.ai.clients.openai_compatible import retry_after_seconds
from app.ai.prompt import Prompt
from app.ai.registry import RegisteredModel


class AnthropicClient(TextReplyClient):
    def __init__(
        self,
        model: RegisteredModel,
        *,
        timeout_seconds: float,
        max_output_tokens: int,
        http_client: httpx2.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(sleep=sleep)
        if model.api_key is None:
            raise ValueError(f"model {model.id!r} needs an API key")
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._client = anthropic.Anthropic(
            api_key=model.api_key.get_secret_value(),
            timeout=timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )

    def send(self, prompt: Prompt) -> Reply:
        options: dict[str, Any] = {}
        if self._model.json_schema:
            options["output_config"] = {
                "format": {"type": "json_schema", "schema": ANSWER_JSON_SCHEMA}
            }
        try:
            message = self._client.messages.create(
                model=self._model.provider_model,
                max_tokens=self._max_output_tokens,
                system=prompt.system,
                messages=[
                    {"role": message.role, "content": message.content}
                    for message in prompt.messages
                ],
                **options,
            )
        except anthropic.APIError as error:
            raise _provider_error(error) from error

        text = "".join(block.text for block in message.content if block.type == "text")
        usage = TokenUsage(message.usage.input_tokens, message.usage.output_tokens)
        return Reply(text, usage, refused=message.stop_reason == "refusal")


def _provider_error(error: anthropic.APIError) -> ProviderError:
    # Most specific first: APITimeoutError is an APIConnectionError, and every
    # status error below is an APIStatusError (OverloadedError is a 529).
    if isinstance(error, anthropic.APITimeoutError):
        return ProviderError(ProviderFailure.TIMEOUT)
    if isinstance(error, anthropic.APIConnectionError):
        return ProviderError(ProviderFailure.CONNECTION)
    if isinstance(error, anthropic.RateLimitError):
        return ProviderError(
            ProviderFailure.RATE_LIMITED, retry_after=retry_after_seconds(error.response)
        )
    if isinstance(error, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return ProviderError(ProviderFailure.AUTHENTICATION)
    if isinstance(error, anthropic.NotFoundError):
        return ProviderError(ProviderFailure.MODEL_UNAVAILABLE)
    if isinstance(error, anthropic.APIStatusError) and error.status_code >= 500:
        return ProviderError(ProviderFailure.SERVER_ERROR)
    return ProviderError(ProviderFailure.REQUEST_REJECTED)
