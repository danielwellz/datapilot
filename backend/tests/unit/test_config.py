import os
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import API_KEY_ENV_PATTERN, ApiKeysSource, Settings
from tests.settings import PRODUCTION_SECRETS, make_test_settings

REQUIRED_ENVIRONMENT = {
    "SECRET_KEY": "secret-from-environment",
    "JWT_SECRET_KEY": "jwt-secret-from-environment-32-chars",
    "DATABASE_URL": "postgresql+psycopg://user:pass@db.internal:5432/datapilot",
    "REDIS_URL": "redis://cache.internal:6379/0",
    "READONLY_DATABASE_URL": "postgresql+psycopg://datapilot_readonly:pass@db.internal:5432/datapilot",
}
STRONG_SECRET = "x" * 32


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """A clean environment holding only the required variables, and no .env file."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    for name in list(os.environ):
        if API_KEY_ENV_PATTERN.fullmatch(name):
            monkeypatch.delenv(name)
    for name, value in REQUIRED_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def test_settings_load_required_values_and_defaults_from_environment(
    environment: pytest.MonkeyPatch,
) -> None:
    settings = Settings()

    assert settings.secret_key.get_secret_value() == "secret-from-environment"
    assert str(settings.database_url).endswith("@db.internal:5432/datapilot")
    assert settings.app_env == "development"
    assert settings.jwt_access_ttl_minutes == 15
    assert settings.llm_default_model is None
    assert settings.llm_api_keys == {}


def test_settings_parse_typed_values_from_environment(environment: pytest.MonkeyPatch) -> None:
    environment.setenv("JWT_ACCESS_TTL_MINUTES", "5")
    environment.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings()

    assert settings.jwt_access_ttl_minutes == 5
    assert settings.log_level == "DEBUG"


@pytest.mark.parametrize("name", sorted(REQUIRED_ENVIRONMENT))
def test_settings_fail_when_a_required_variable_is_missing(
    environment: pytest.MonkeyPatch, name: str
) -> None:
    environment.delenv(name)

    with pytest.raises(ValidationError, match=name.lower()):
        Settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DATABASE_URL", "mysql://user:pass@localhost/datapilot"),
        ("REDIS_URL", "http://localhost:6379"),
        ("APP_ENV", "staging"),
        ("JWT_ACCESS_TTL_MINUTES", "0"),
    ],
)
def test_settings_reject_invalid_values(
    environment: pytest.MonkeyPatch, name: str, value: str
) -> None:
    environment.setenv(name, value)

    with pytest.raises(ValidationError, match=name.lower()):
        Settings()


def test_settings_collect_every_non_empty_api_key_variable(
    environment: pytest.MonkeyPatch,
) -> None:
    environment.setenv("GROQ_API_KEY", "groq-key")
    environment.setenv("SOME_NEW_PROVIDER_API_KEY", "new-key")
    environment.setenv("ANTHROPIC_API_KEY", "")
    environment.setenv("API_KEY", "not-a-provider-key")

    keys = Settings().llm_api_keys

    assert {name: key.get_secret_value() for name, key in keys.items()} == {
        "GROQ_API_KEY": "groq-key",
        "SOME_NEW_PROVIDER_API_KEY": "new-key",
    }


def test_settings_read_api_keys_from_the_env_file_with_the_environment_winning(
    environment: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_API_KEY=from-file\nGEMINI_API_KEY=gemini-from-file\n")
    environment.setitem(Settings.model_config, "env_file", env_file)
    environment.setenv("GROQ_API_KEY", "from-environment")

    keys = Settings().llm_api_keys

    assert keys["GROQ_API_KEY"].get_secret_value() == "from-environment"
    assert keys["GEMINI_API_KEY"].get_secret_value() == "gemini-from-file"


def test_settings_keep_api_keys_out_of_their_repr(environment: pytest.MonkeyPatch) -> None:
    environment.setenv("GROQ_API_KEY", "do-not-print-this-key")

    assert "do-not-print-this-key" not in repr(Settings())


def test_settings_read_the_fallback_models_as_a_comma_separated_list(
    environment: pytest.MonkeyPatch,
) -> None:
    environment.setenv("LLM_FALLBACK_MODELS", " groq-gpt-oss-120b , gemini-3.5-flash,")
    environment.setenv("LLM_DEFAULT_MODEL", "")
    environment.setenv("LLM_MODELS_FILE", "")

    settings = Settings()

    assert settings.llm_fallback_models == ("groq-gpt-oss-120b", "gemini-3.5-flash")
    assert settings.llm_default_model is None
    assert settings.llm_models_file is None


def test_settings_keep_secrets_out_of_their_repr() -> None:
    settings = make_test_settings(secret_key="do-not-print-me")

    assert "do-not-print-me" not in repr(settings)


@pytest.mark.parametrize(
    ("secret_key", "jwt_secret_key", "rejected"),
    [
        ("change-me-flask-secret" + STRONG_SECRET, STRONG_SECRET, "SECRET_KEY"),
        (STRONG_SECRET, "too-short", "JWT_SECRET_KEY"),
    ],
)
def test_production_settings_reject_placeholder_or_short_secrets(
    secret_key: str, jwt_secret_key: str, rejected: str
) -> None:
    with pytest.raises(ValidationError, match=rejected):
        make_test_settings(
            app_env="production", secret_key=secret_key, jwt_secret_key=jwt_secret_key
        )


def test_settings_reject_a_jwt_secret_shorter_than_32_characters_in_any_environment() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY must be at least 32 characters"):
        make_test_settings(app_env="development", jwt_secret_key="x" * 31)


@pytest.mark.parametrize(
    "overrides",
    [
        {"jwt_secret_key": "short-SECRET-VALUE"},
        {"app_env": "production", "secret_key": "change-me-SECRET-VALUE" + STRONG_SECRET},
        {"app_env": "production", "jwt_secret_key": "SECRET-VALUE" + STRONG_SECRET},
    ],
)
def test_settings_errors_never_print_the_rejected_values(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError) as caught:
        make_test_settings(**overrides)

    assert "SECRET-VALUE" not in str(caught.value)
    assert "input_value" not in str(caught.value)


def test_token_lifetimes_are_exposed_as_durations() -> None:
    settings = make_test_settings(jwt_access_ttl_minutes=5, jwt_refresh_ttl_days=2)

    assert settings.access_token_ttl == timedelta(minutes=5)
    assert settings.refresh_token_ttl == timedelta(days=2)


def test_production_settings_reject_a_placeholder_readonly_password() -> None:
    with pytest.raises(ValidationError, match="READONLY_DATABASE_URL must not use a placeholder"):
        make_test_settings(
            app_env="production",
            secret_key=STRONG_SECRET,
            jwt_secret_key=STRONG_SECRET,
            readonly_database_url=(
                "postgresql+psycopg://datapilot_readonly:change-me-readonly@db:5432/datapilot"
            ),
        )


def test_production_settings_accept_strong_secrets() -> None:
    settings = make_test_settings(
        app_env="production",
        secret_key=STRONG_SECRET,
        jwt_secret_key=STRONG_SECRET,
        readonly_database_url=PRODUCTION_SECRETS["readonly_database_url"],
    )

    assert settings.is_production


def test_test_settings_ignore_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("SECRET_KEY", "from-environment")

    settings = make_test_settings()

    assert settings.log_level == "INFO"
    assert settings.secret_key.get_secret_value() == "test-secret-key"


def test_api_keys_source_provides_its_field_only_as_a_whole() -> None:
    # pydantic-settings asks sources field by field; this one answers through
    # __call__ instead, so the per-field lookup reports "not found".
    field = Settings.model_fields["llm_api_keys"]

    assert ApiKeysSource(Settings).get_field_value(field, "llm_api_keys") == (
        None,
        "llm_api_keys",
        False,
    )
