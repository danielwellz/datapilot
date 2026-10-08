"""Builds the client for a registry model."""

from collections.abc import Callable

from app.ai.clients.anthropic import AnthropicClient
from app.ai.clients.base import LLMClient
from app.ai.clients.fake import FakeLLMClient
from app.ai.clients.openai_compatible import OpenAICompatibleClient
from app.ai.registry import ProviderType, RegisteredModel

ClientBuilder = Callable[[RegisteredModel, float, int], LLMClient]

# One entry per provider type; a test checks none is missing.
CLIENT_BUILDERS: dict[ProviderType, ClientBuilder] = {
    ProviderType.FAKE: lambda _model, _timeout, _tokens: FakeLLMClient(),
    ProviderType.OPENAI_COMPATIBLE: lambda model, timeout, tokens: OpenAICompatibleClient(
        model, timeout_seconds=timeout, max_output_tokens=tokens
    ),
    ProviderType.ANTHROPIC: lambda model, timeout, tokens: AnthropicClient(
        model, timeout_seconds=timeout, max_output_tokens=tokens
    ),
}


def create_llm_client(
    model: RegisteredModel, *, timeout_seconds: float, max_output_tokens: int
) -> LLMClient:
    return CLIENT_BUILDERS[model.provider.type](model, timeout_seconds, max_output_tokens)
