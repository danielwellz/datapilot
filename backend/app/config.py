"""Application settings, loaded from environment variables."""

import os
import re
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from dotenv import dotenv_values
from flask import current_app
from pydantic import (
    FilePath,
    PositiveInt,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from sqlalchemy.engine import make_url

# The repository root, so the same .env is found whether the process starts
# in the repository root (Docker, CI) or in backend/ (Makefile targets).
_REPO_ROOT = Path(__file__).resolve().parents[2]

SETTINGS_EXTENSION_KEY = "datapilot.settings"

_MIN_PRODUCTION_SECRET_LENGTH = 32
# RFC 7518 (section 3.2): an HS256 key must be at least as long as the hash
# output. Shorter keys are brute-forceable offline from any issued token.
_MIN_JWT_SECRET_LENGTH = 32
_PLACEHOLDER_MARKER = "change-me"

# Provider API keys follow one naming rule, so the model registry can name the
# variable for each provider without a matching field here (see ApiKeysSource).
API_KEY_ENV_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*_API_KEY")

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Every runtime setting of the backend, validated once at startup.

    Connection strings and secrets have no defaults so a misconfigured
    process fails at startup instead of on its first request.
    """

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        # .env also holds Docker Compose variables that are not ours.
        extra="ignore",
        frozen=True,
        # Validation errors end up in startup logs; by default pydantic prints
        # the rejected input, which here means secrets and connection strings.
        hide_input_in_errors=True,
    )

    app_env: AppEnv = "development"
    secret_key: SecretStr
    database_url: PostgresDsn
    # Ask your data runs model-written SQL through this connection only: it
    # logs in as datapilot_readonly, which can read the analytics views and
    # nothing else.
    readonly_database_url: PostgresDsn
    redis_url: RedisDsn

    jwt_secret_key: SecretStr
    jwt_access_ttl_minutes: PositiveInt = 15
    jwt_refresh_ttl_days: PositiveInt = 7

    log_level: LogLevel = "INFO"
    # Per statement, for requests only: no API query comes close (the slowest
    # measured p95 is under 0.5 s at full scale), so a statement this slow is
    # an unmeasured filter combination or a request the client gave up on.
    api_statement_timeout_ms: PositiveInt = 3000

    # Model registry ids; validated against the registry when the app starts.
    llm_default_model: str | None = None
    llm_fallback_models: Annotated[tuple[str, ...], NoDecode] = ()
    # A replacement for the registry that ships with the backend.
    llm_models_file: FilePath | None = None
    # Every *_API_KEY variable, by name; the registry says which provider uses which.
    llm_api_keys: dict[str, SecretStr] = {}
    llm_timeout_seconds: PositiveInt = 30
    # Generous, because some models reason at length before answering.
    llm_max_output_tokens: PositiveInt = 8192
    ai_rate_limit_per_minute: PositiveInt = 10
    ai_max_rows: PositiveInt = 1000
    ai_statement_timeout_ms: PositiveInt = 5000

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            ApiKeysSource(settings_cls),
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )

    @field_validator("llm_default_model", "llm_models_file", mode="before")
    @classmethod
    def _empty_means_unset(cls, value: object) -> object:
        # An empty LLM_DEFAULT_MODEL= line in .env means "not set".
        return None if value == "" else value

    @field_validator("llm_fallback_models", mode="before")
    @classmethod
    def _split_model_list(cls, value: object) -> object:
        # Written as a comma-separated list in the environment.
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def _jwt_secret_long_enough_for_hs256(cls, value: SecretStr) -> SecretStr:
        # Enforced in every environment: tokens signed with a weak key in
        # development would pass tests that production then fails.
        if len(value.get_secret_value()) < _MIN_JWT_SECRET_LENGTH:
            raise ValueError(
                f"JWT_SECRET_KEY must be at least {_MIN_JWT_SECRET_LENGTH} characters long"
            )
        return value

    @model_validator(mode="after")
    def _reject_weak_production_secrets(self) -> Self:
        if not self.is_production:
            return self
        for name, secret in (
            ("SECRET_KEY", self.secret_key),
            ("JWT_SECRET_KEY", self.jwt_secret_key),
        ):
            value = secret.get_secret_value()
            if _PLACEHOLDER_MARKER in value or len(value) < _MIN_PRODUCTION_SECRET_LENGTH:
                raise ValueError(
                    f"{name} must be a random value of at least "
                    f"{_MIN_PRODUCTION_SECRET_LENGTH} characters in production"
                )
        readonly_password = make_url(str(self.readonly_database_url)).password or ""
        if _PLACEHOLDER_MARKER in readonly_password:
            raise ValueError(
                "READONLY_DATABASE_URL must not use a placeholder password in production"
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def access_token_ttl(self) -> timedelta:
        return timedelta(minutes=self.jwt_access_ttl_minutes)

    @property
    def refresh_token_ttl(self) -> timedelta:
        return timedelta(days=self.jwt_refresh_ttl_days)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read from the environment once."""
    return Settings()


def current_settings() -> Settings:
    """Return the settings of the application serving the current request or command."""
    settings: Settings = current_app.extensions[SETTINGS_EXTENSION_KEY]
    return settings


class ApiKeysSource(PydanticBaseSettingsSource):
    """Collects every non-empty ``*_API_KEY`` variable into ``llm_api_keys``.

    The model registry names the variable holding each provider's key, so a
    new provider is a registry entry rather than a new settings field. The
    process environment wins over .env, as for every other setting.
    """

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        # Unused: __call__ builds the one field this source provides.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        env_file = self.config.get("env_file")
        from_file: dict[str, str | None] = {}
        if isinstance(env_file, Path) and env_file.is_file():
            from_file = dotenv_values(env_file)
        candidates = {**from_file, **os.environ}
        keys = {
            name: value
            for name, value in candidates.items()
            if value and API_KEY_ENV_PATTERN.fullmatch(name)
        }
        return {"llm_api_keys": keys} if keys else {}
