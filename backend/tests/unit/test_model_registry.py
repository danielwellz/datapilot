from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from pydantic import SecretStr, ValidationError

from app.ai.errors import ModelNotAvailable
from app.ai.registry import (
    DEFAULT_REGISTRY_FILE,
    MAX_FALLBACKS,
    ModelRegistry,
    ProviderType,
    RegistryConfig,
    RegistryError,
)
from app.extensions import get_model_registry
from tests.conftest import AppFactory

GROQ_KEY = {"GROQ_API_KEY": SecretStr("groq-key")}

LOCAL_SERVER_REGISTRY = """
[providers.local]
type = "openai_compatible"
label = "Local server"
base_url = "http://localhost:11434/v1"

[[models]]
id = "local-model"
provider = "local"
label = "Local model"
provider_model = "some-model:8b"
json_schema = false
"""


def _config(**overrides: Any) -> RegistryConfig:
    """A small registry: one keyed provider with two models, plus the fake model."""
    data: dict[str, Any] = {
        "providers": {
            "groq": {
                "type": "openai_compatible",
                "label": "Groq",
                "base_url": "https://api.groq.com/openai/v1",
                "api_key_env": "GROQ_API_KEY",
            },
            "gemini": {
                "type": "openai_compatible",
                "label": "Gemini",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "api_key_env": "GEMINI_API_KEY",
            },
            "fake": {"type": "fake", "label": "Demo"},
        },
        "models": [
            {
                "id": "groq-a",
                "provider": "groq",
                "label": "A",
                "provider_model": "a",
                "json_schema": True,
            },
            {
                "id": "groq-b",
                "provider": "groq",
                "label": "B",
                "provider_model": "b",
                "json_schema": False,
            },
            {
                "id": "gemini-c",
                "provider": "gemini",
                "label": "C",
                "provider_model": "c",
                "json_schema": True,
            },
            {
                "id": "fake",
                "provider": "fake",
                "label": "Demo",
                "provider_model": "fake",
                "json_schema": False,
            },
        ],
    }
    return RegistryConfig.model_validate(data | overrides)


def test_shipped_registry_is_valid_and_offers_the_fake_model_without_keys() -> None:
    config = RegistryConfig.load(DEFAULT_REGISTRY_FILE)

    registry = ModelRegistry(config, api_keys={})

    assert [model.id for model in registry.enabled_models] == ["fake"]
    assert registry.default_model.id == "fake"
    assert {provider.type for provider in config.providers.values()} == set(ProviderType)
    for provider in config.providers.values():
        assert provider.base_url is None or provider.base_url.scheme == "https"


def test_shipped_registry_enables_the_models_of_providers_with_a_key() -> None:
    config = RegistryConfig.load(DEFAULT_REGISTRY_FILE)

    registry = ModelRegistry(config, api_keys=GROQ_KEY | {"GEMINI_API_KEY": SecretStr("g")})

    assert {model.provider_id for model in registry.enabled_models} == {"groq", "gemini", "fake"}
    assert registry.default_model.id == "groq-gpt-oss-120b"


def test_models_of_providers_without_a_key_are_not_enabled() -> None:
    registry = ModelRegistry(_config(), api_keys=GROQ_KEY)

    assert [model.id for model in registry.enabled_models] == ["groq-a", "groq-b", "fake"]
    assert registry.resolve("groq-b").api_key == GROQ_KEY["GROQ_API_KEY"]
    assert registry.resolve("fake").api_key is None


def test_a_provider_without_a_key_variable_is_always_enabled(tmp_path: Path) -> None:
    # A local server such as Ollama is added to the registry file alone.
    models_file = tmp_path / "models.toml"
    models_file.write_text(LOCAL_SERVER_REGISTRY)

    registry = ModelRegistry.from_settings(
        models_file=models_file, api_keys={}, default_model=None, fallback_models=()
    )

    model = registry.default_model
    assert (model.id, model.provider_model, model.api_key) == ("local-model", "some-model:8b", None)


def test_default_model_is_the_first_enabled_model_unless_one_is_configured() -> None:
    assert ModelRegistry(_config(), api_keys=GROQ_KEY).default_model.id == "groq-a"
    configured = ModelRegistry(_config(), api_keys=GROQ_KEY, default_model="groq-b")
    assert configured.default_model.id == "groq-b"


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"default_model": "nope"}, "'nope' is not a model in the registry"),
        ({"fallback_models": ["groq-a", "nope"]}, "'nope' is not a model in the registry"),
        ({"default_model": "gemini-c"}, "LLM_DEFAULT_MODEL 'gemini-c' is not enabled"),
    ],
)
def test_settings_that_contradict_the_registry_are_refused(
    settings: dict[str, Any], message: str
) -> None:
    with pytest.raises(RegistryError, match=message):
        ModelRegistry(_config(), api_keys=GROQ_KEY, **settings)


def test_a_registry_with_no_enabled_model_is_refused() -> None:
    config = _config(models=[_config().models[0]])

    with pytest.raises(RegistryError, match="no model is enabled"):
        ModelRegistry(config, api_keys={})


def test_resolve_returns_the_default_for_no_model_and_refuses_unknown_or_disabled_ids() -> None:
    registry = ModelRegistry(_config(), api_keys=GROQ_KEY)

    assert registry.resolve(None).id == "groq-a"
    for model_id in ("gemini-c", "gpt-anything", "openai/gpt-oss-120b"):
        with pytest.raises(ModelNotAvailable) as caught:
            registry.resolve(model_id)
        assert caught.value.status == 422
        assert caught.value.code == "model_not_available"


def test_attempt_order_tries_enabled_fallbacks_after_the_chosen_model() -> None:
    registry = ModelRegistry(
        _config(),
        api_keys=GROQ_KEY,
        fallback_models=["gemini-c", "groq-a", "fake", "groq-b"],
    )

    order = registry.attempt_order(registry.resolve("groq-b"))

    # gemini-c has no key, groq-b is the chosen model, and the fake model
    # only knows the example questions.
    assert [model.id for model in order] == ["groq-b", "groq-a"]


def test_attempt_order_is_capped() -> None:
    providers = {"p": {"type": "openai_compatible", "label": "P", "base_url": "https://p.example"}}
    models = [
        {
            "id": f"m{index}",
            "provider": "p",
            "label": "M",
            "provider_model": "m",
            "json_schema": False,
        }
        for index in range(5)
    ]
    registry = ModelRegistry(
        RegistryConfig.model_validate({"providers": providers, "models": models}),
        api_keys={},
        fallback_models=[f"m{index}" for index in range(5)],
    )

    assert len(registry.attempt_order(registry.resolve("m0"))) == 1 + MAX_FALLBACKS


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda data: data["models"].append(dict(data["models"][0])), "appears more than once"),
        (lambda data: data["models"][0].update(provider="nope"), "unknown provider 'nope'"),
        (lambda data: data["models"][0].update(id="Groq-A"), "String should match pattern"),
        (lambda data: data["models"][0].update(temperature=0), "Extra inputs are not permitted"),
        (lambda data: data["providers"]["groq"].pop("base_url"), "needs a base_url"),
        (
            lambda data: data["providers"]["groq"].update(api_key_env="groq_key"),
            "should match pattern",
        ),
        (
            lambda data: data["providers"].update(anthropic={"type": "anthropic", "label": "A"}),
            "needs an api_key_env",
        ),
        (
            lambda data: data["providers"]["fake"].update(base_url="https://x.example"),
            "takes no base_url",
        ),
    ],
)
def test_invalid_registry_files_are_refused(change: Any, message: str) -> None:
    data = _config().model_dump(mode="json", exclude_none=True)
    change(data)

    with pytest.raises(ValidationError, match=message):
        RegistryConfig.model_validate(data)


def test_api_keys_stay_out_of_model_reprs() -> None:
    registry = ModelRegistry(_config(), api_keys={"GROQ_API_KEY": SecretStr("secret-groq-key")})

    assert "secret-groq-key" not in repr(registry.resolve("groq-a"))


@pytest.mark.usefixtures("app_context")
def test_the_app_builds_its_registry_from_settings(app: Flask) -> None:
    assert get_model_registry().default_model.id == "fake"


def test_the_app_refuses_to_start_with_a_default_model_outside_the_registry(
    make_app: AppFactory,
) -> None:
    with pytest.raises(RegistryError, match="'gpt-9' is not a model in the registry"):
        make_app(llm_default_model="gpt-9")
