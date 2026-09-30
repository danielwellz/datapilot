import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.settings import make_test_settings

REQUIRED_ENVIRONMENT = {
    "SECRET_KEY": "secret-from-environment",
    "JWT_SECRET_KEY": "jwt-secret-from-environment",
    "DATABASE_URL": "postgresql+psycopg://user:pass@db.internal:5432/datapilot",
    "REDIS_URL": "redis://cache.internal:6379/0",
}
STRONG_SECRET = "x" * 32


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """A clean environment holding only the required variables, and no .env file."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
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
    assert settings.llm_provider == "fake"
    assert settings.readonly_database_url is None


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


def test_settings_treat_empty_anthropic_api_key_as_missing(
    environment: pytest.MonkeyPatch,
) -> None:
    environment.setenv("ANTHROPIC_API_KEY", "")

    assert Settings().anthropic_api_key is None


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


def test_production_settings_accept_strong_secrets() -> None:
    settings = make_test_settings(
        app_env="production", secret_key=STRONG_SECRET, jwt_secret_key=STRONG_SECRET
    )

    assert settings.is_production


def test_test_settings_ignore_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("SECRET_KEY", "from-environment")

    settings = make_test_settings()

    assert settings.log_level == "INFO"
    assert settings.secret_key.get_secret_value() == "test-secret-key"
