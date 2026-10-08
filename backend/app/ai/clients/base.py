"""What every LLM client provides, and the failures the service must tell apart.

Provider failures come in two kinds, and the service treats them differently:

- ``ProviderError``: the provider could not answer (rate limited, failing,
  unreachable, the model withdrawn). Another model may well answer, so the
  service falls back to the next one.
- ``InvalidModelOutputError``: the model answered, but not usably, even after
  one retry. Another model is not tried: the failure says something about
  the question or the model, not about the provider's availability.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.ai.answer import InvalidAnswerError, LLMAnswer, parse_answer
from app.ai.prompt import Prompt, format_retry


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            _add(self.input_tokens, other.input_tokens),
            _add(self.output_tokens, other.output_tokens),
        )


def _add(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)


@dataclass(frozen=True, slots=True)
class LLMResult:
    answer: LLMAnswer
    # Summed over every request the answer took, the format retry included.
    usage: TokenUsage


class LLMClient(Protocol):
    def answer(self, prompt: Prompt) -> LLMResult:
        """Ask the model; raise ``ProviderError`` or ``InvalidModelOutputError`` on failure."""
        ...


class ProviderFailure(StrEnum):
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    # The key was refused: a configuration problem, but another provider can still answer.
    AUTHENTICATION = "authentication"
    MODEL_UNAVAILABLE = "model_unavailable"
    # The provider refused the request itself (a 4xx other than the above).
    REQUEST_REJECTED = "request_rejected"


# Worth one quick retry: these usually pass within a second. A rate limit is
# not retried here; the service moves on to another model instead of
# keeping the analyst waiting for the provider's window to reopen.
_TRANSIENT_FAILURES = frozenset(
    {ProviderFailure.SERVER_ERROR, ProviderFailure.TIMEOUT, ProviderFailure.CONNECTION}
)
_TRANSIENT_RETRY_DELAY_SECONDS = 0.5


class ProviderError(Exception):
    """The provider could not answer. ``retry_after`` is in seconds, when the provider said."""

    def __init__(self, failure: ProviderFailure, *, retry_after: float | None = None) -> None:
        super().__init__(failure.value)
        self.failure = failure
        self.retry_after = retry_after


class InvalidModelOutputError(Exception):
    """The model answered, but with nothing usable, after the one allowed retry."""

    def __init__(self, problem: str, usage: TokenUsage) -> None:
        super().__init__(problem)
        self.problem = problem
        self.usage = usage


@dataclass(frozen=True, slots=True)
class Reply:
    """One raw reply from a provider."""

    text: str
    usage: TokenUsage
    # Set when the provider declined to answer (a refusal), whatever the text.
    refused: bool = False


class TextReplyClient:
    """Shared answer logic for providers that return text: parse, retry once, give up.

    Subclasses implement ``send`` and raise ``ProviderError`` for provider
    failures. The SDKs' own retries are turned off, so this class alone
    decides what is retried, and how long the analyst can be kept waiting.
    """

    def __init__(self, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self._sleep = sleep

    def send(self, prompt: Prompt) -> Reply:
        raise NotImplementedError

    def _send_with_retry(self, prompt: Prompt) -> Reply:
        try:
            return self.send(prompt)
        except ProviderError as error:
            if error.failure not in _TRANSIENT_FAILURES:
                raise
        self._sleep(_TRANSIENT_RETRY_DELAY_SECONDS)
        return self.send(prompt)

    def answer(self, prompt: Prompt) -> LLMResult:
        reply = self._send_with_retry(prompt)
        usage = reply.usage
        if reply.refused:
            raise InvalidModelOutputError("The model declined to answer.", usage)
        try:
            return LLMResult(parse_answer(reply.text), usage)
        except InvalidAnswerError as first_error:
            # One retry, telling the model what was wrong: most format slips
            # are fixed by it, and a second failure rarely is by another.
            retry = self._send_with_retry(
                prompt.followed_by(*format_retry(reply.text, str(first_error)))
            )
            usage += retry.usage
            if retry.refused:
                raise InvalidModelOutputError("The model declined to answer.", usage) from None
            try:
                return LLMResult(parse_answer(retry.text), usage)
            except InvalidAnswerError as second_error:
                raise InvalidModelOutputError(str(second_error), usage) from second_error
