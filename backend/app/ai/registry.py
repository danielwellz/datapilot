"""The registry of models Ask your data may use, and which of them are enabled.

The registry is configuration (``llm_models.toml``, or the file named by
LLM_MODELS_FILE) validated into the types below when the app starts. Client
requests may only name a model by its registry id, and only an enabled one:
the model name sent to a provider always comes from here, never from a client.
"""

import tomllib
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, model_validator

from app.ai.errors import ModelNotAvailable
from app.config import API_KEY_ENV_PATTERN

DEFAULT_REGISTRY_FILE = Path(__file__).with_name("llm_models.toml")
# The fake model only knows the example questions, so it is never a fallback.
FAKE_MODEL_ID = "fake"
# The requested model plus at most this many fallbacks: each attempt can take
# up to LLM_TIMEOUT_SECONDS, and the analyst is waiting.
MAX_FALLBACKS = 2

_MODEL_ID_PATTERN = r"^[a-z0-9][a-z0-9.:-]{0,63}$"


class ProviderType(StrEnum):
    FAKE = "fake"
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: ProviderType
    label: str = Field(min_length=1)
    base_url: HttpUrl | None = None
    api_key_env: Annotated[str, Field(pattern=API_KEY_ENV_PATTERN.pattern)] | None = None

    @model_validator(mode="after")
    def _fields_match_the_type(self) -> Self:
        if self.type is ProviderType.OPENAI_COMPATIBLE and self.base_url is None:
            raise ValueError("an openai_compatible provider needs a base_url")
        if self.type is ProviderType.ANTHROPIC and self.api_key_env is None:
            raise ValueError("the anthropic provider needs an api_key_env")
        if self.type is ProviderType.FAKE and (self.base_url or self.api_key_env):
            raise ValueError("the fake provider takes no base_url or api_key_env")
        return self


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(pattern=_MODEL_ID_PATTERN)]
    provider: str
    label: str = Field(min_length=1)
    provider_model: str = Field(min_length=1)
    json_schema: bool
    # Why `make eval-ask` leaves this model out unless it is named; None to include it.
    skip_evaluation: str | None = Field(default=None, min_length=1)


class RegistryConfig(BaseModel):
    """The registry file, validated as a whole."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    providers: dict[str, ProviderConfig]
    models: list[ModelConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _models_are_unique_and_reference_providers(self) -> Self:
        seen: set[str] = set()
        for model in self.models:
            if model.id in seen:
                raise ValueError(f"model id {model.id!r} appears more than once")
            seen.add(model.id)
            if model.provider not in self.providers:
                raise ValueError(f"model {model.id!r} names unknown provider {model.provider!r}")
        return self

    @classmethod
    def load(cls, path: Path) -> "RegistryConfig":
        with path.open("rb") as file:
            return cls.model_validate(tomllib.load(file))


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    """A model as the rest of the application sees it."""

    id: str
    label: str
    provider_id: str
    provider: ProviderConfig
    provider_model: str
    json_schema: bool
    skip_evaluation: str | None
    # None for providers that need no key (the fake model, a local server).
    api_key: SecretStr | None


class RegistryError(ValueError):
    """The model settings contradict the registry; raised when the app starts."""


class ModelRegistry:
    """The enabled models, the default one, and the order to try them in."""

    def __init__(
        self,
        config: RegistryConfig,
        *,
        api_keys: Mapping[str, SecretStr],
        default_model: str | None = None,
        fallback_models: Sequence[str] = (),
    ) -> None:
        known = {model.id for model in config.models}
        for model_id in (*([default_model] if default_model else []), *fallback_models):
            if model_id not in known:
                raise RegistryError(f"{model_id!r} is not a model in the registry")

        self._enabled: dict[str, RegisteredModel] = {}
        for model in config.models:
            provider = config.providers[model.provider]
            api_key = api_keys.get(provider.api_key_env) if provider.api_key_env else None
            if provider.api_key_env is None or api_key is not None:
                self._enabled[model.id] = RegisteredModel(
                    id=model.id,
                    label=model.label,
                    provider_id=model.provider,
                    provider=provider,
                    provider_model=model.provider_model,
                    json_schema=model.json_schema,
                    skip_evaluation=model.skip_evaluation,
                    api_key=api_key,
                )
        if not self._enabled:
            raise RegistryError("no model is enabled; add one that needs no key, such as fake")

        if default_model is None:
            self._default = next(iter(self._enabled.values()))
        elif default_model in self._enabled:
            self._default = self._enabled[default_model]
        else:
            raise RegistryError(
                f"LLM_DEFAULT_MODEL {default_model!r} is not enabled; set its provider's API key"
            )
        if fallback_models:
            # Fallbacks whose provider has no key are skipped rather than
            # refused: the list can name every provider the deployment might have.
            self._fallbacks = tuple(
                self._enabled[model_id] for model_id in fallback_models if model_id in self._enabled
            )
        else:
            self._fallbacks = tuple(_alternate_providers(self._enabled.values()))
        self._check_fallbacks_reach_another_provider()

    @classmethod
    def from_settings(
        cls,
        *,
        models_file: Path | None,
        api_keys: Mapping[str, SecretStr],
        default_model: str | None,
        fallback_models: Sequence[str],
    ) -> "ModelRegistry":
        config = RegistryConfig.load(models_file or DEFAULT_REGISTRY_FILE)
        return cls(
            config,
            api_keys=api_keys,
            default_model=default_model,
            fallback_models=fallback_models,
        )

    @property
    def enabled_models(self) -> list[RegisteredModel]:
        return list(self._enabled.values())

    @property
    def default_model(self) -> RegisteredModel:
        return self._default

    def resolve(self, model_id: str | None) -> RegisteredModel:
        """The enabled model with this id, or the default when ``model_id`` is None."""
        if model_id is None:
            return self._default
        model = self._enabled.get(model_id)
        if model is None:
            raise ModelNotAvailable(
                f"The model {model_id!r} is not available. "
                "GET /api/ai/models lists the models you can choose."
            )
        return model

    def attempt_order(self, first: RegisteredModel) -> list[RegisteredModel]:
        """``first``, then the configured fallbacks to try if its provider fails."""
        fallbacks = [
            model for model in self._fallbacks if model.id != first.id and _can_fall_back(model)
        ]
        return [first, *fallbacks[:MAX_FALLBACKS]]

    def _check_fallbacks_reach_another_provider(self) -> None:
        """Refuse fallbacks that leave any model stuck on its own provider.

        An outage, a refused key or a region block takes out every model of a
        provider at once, so a fallback on the same provider rarely helps.
        """
        providers = {model.provider_id for model in self._enabled.values() if _can_fall_back(model)}
        if len(providers) < 2:
            return
        for model in self._enabled.values():
            if not _can_fall_back(model):
                continue
            if {attempt.provider_id for attempt in self.attempt_order(model)} == {
                model.provider_id
            }:
                raise RegistryError(
                    f"LLM_FALLBACK_MODELS leaves {model.id!r} without a fallback on another "
                    f"provider, although {len(providers)} providers are enabled; add a model "
                    "of another provider, or leave LLM_FALLBACK_MODELS empty to alternate "
                    "providers in registry order"
                )


def _can_fall_back(model: RegisteredModel) -> bool:
    return model.id != FAKE_MODEL_ID


def _alternate_providers(models: Iterable[RegisteredModel]) -> list[RegisteredModel]:
    """Every model but the fake one, taking one per provider in turn, in registry order.

    The default fallback order: whichever model is asked first, the next
    attempt goes to another provider whenever one is enabled.
    """
    queues: dict[str, deque[RegisteredModel]] = {}
    for model in models:
        if _can_fall_back(model):
            queues.setdefault(model.provider_id, deque()).append(model)
    order: list[RegisteredModel] = []
    while queues:
        for provider_id, queue in list(queues.items()):
            order.append(queue.popleft())
            if not queue:
                del queues[provider_id]
    return order
