"""One client for every provider with an OpenAI-compatible chat completions API.

Groq, Gemini (through its OpenAI-compatible endpoint), OpenRouter and local
servers such as Ollama all accept the same request; the registry supplies the
base URL, the key and the provider's model name. Only the official ``openai``
SDK's request and error types are used, so a provider differs by
configuration alone.
"""

import time
from collections.abc import Callable
from typing import Any

import httpx2
import openai

from app.ai.answer import ANSWER_JSON_SCHEMA
from app.ai.clients.base import ProviderError, ProviderFailure, Reply, TextReplyClient, TokenUsage
from app.ai.prompt import Prompt
from app.ai.registry import RegisteredModel

# The SDK refuses to start without a key; local servers ignore it.
_NO_KEY = "no-key-needed"


class OpenAICompatibleClient(TextReplyClient):
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
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._client = openai.OpenAI(
            api_key=model.api_key.get_secret_value() if model.api_key else _NO_KEY,
            base_url=str(model.provider.base_url),
            timeout=timeout_seconds,
            max_retries=0,
            http_client=http_client,
        )

    def send(self, prompt: Prompt) -> Reply:
        messages: list[Any] = [
            {"role": "system", "content": prompt.system},
            *({"role": message.role, "content": message.content} for message in prompt.messages),
        ]
        options: dict[str, Any] = {}
        if self._model.json_schema:
            options["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "strict": True, "schema": ANSWER_JSON_SCHEMA},
            }
        try:
            completion = self._client.chat.completions.create(
                model=self._model.provider_model,
                messages=messages,
                max_completion_tokens=self._max_output_tokens,
                **options,
            )
        except openai.APIError as error:
            raise _provider_error(error) from error

        # OpenRouter reports some upstream failures as a 200 without choices.
        if not completion.choices:
            raise ProviderError(ProviderFailure.SERVER_ERROR)
        choice = completion.choices[0]
        usage = TokenUsage(
            completion.usage.prompt_tokens if completion.usage else None,
            completion.usage.completion_tokens if completion.usage else None,
        )
        refused = choice.finish_reason == "content_filter" or bool(choice.message.refusal)
        return Reply(choice.message.content or "", usage, refused=refused)


def _provider_error(error: openai.APIError) -> ProviderError:
    # Most specific first: APITimeoutError is an APIConnectionError, and every
    # status error below is an APIStatusError.
    if isinstance(error, openai.APITimeoutError):
        return ProviderError(ProviderFailure.TIMEOUT)
    if isinstance(error, openai.APIConnectionError):
        return ProviderError(ProviderFailure.CONNECTION)
    if isinstance(error, openai.RateLimitError):
        return ProviderError(
            ProviderFailure.RATE_LIMITED, retry_after=retry_after_seconds(error.response)
        )
    if isinstance(error, openai.AuthenticationError | openai.PermissionDeniedError):
        return ProviderError(ProviderFailure.AUTHENTICATION)
    if isinstance(error, openai.NotFoundError):
        return ProviderError(ProviderFailure.MODEL_UNAVAILABLE)
    if isinstance(error, openai.APIStatusError) and error.status_code >= 500:
        return ProviderError(ProviderFailure.SERVER_ERROR)
    return ProviderError(ProviderFailure.REQUEST_REJECTED)


def retry_after_seconds(response: httpx2.Response) -> float | None:
    """The Retry-After header in seconds, when the provider sent one as a number."""
    try:
        return max(0.0, float(response.headers["retry-after"]))
    except (KeyError, ValueError):
        # Absent, or an HTTP date, which none of the supported providers send.
        return None
