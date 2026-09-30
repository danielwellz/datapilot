"""Application settings, loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from flask import current_app
from pydantic import (
    Field,
    PositiveInt,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repository root, so the same .env is found whether the process starts
# in the repository root (Docker, CI) or in backend/ (Makefile targets).
_REPO_ROOT = Path(__file__).resolve().parents[2]

SETTINGS_EXTENSION_KEY = "datapilot.settings"

_MIN_PRODUCTION_SECRET_LENGTH = 32
# RFC 7518 (section 3.2): an HS256 key must be at least as long as the hash
# output. Shorter keys are brute-forceable offline from any issued token.
_MIN_JWT_SECRET_LENGTH = 32
_PLACEHOLDER_MARKER = "change-me"

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
    # Required from Stage 6, when Ask your data starts using the read-only role.
    readonly_database_url: PostgresDsn | None = None
    redis_url: RedisDsn

    jwt_secret_key: SecretStr
    jwt_access_ttl_minutes: PositiveInt = 15
    jwt_refresh_ttl_days: PositiveInt = 7

    log_level: LogLevel = "INFO"

    llm_provider: Literal["anthropic", "fake"] = "fake"
    anthropic_api_key: SecretStr | None = None
    llm_model: str = Field(default="claude-sonnet-5", min_length=1)
    llm_timeout_seconds: PositiveInt = 30
    ai_rate_limit_per_minute: PositiveInt = 10
    ai_max_rows: PositiveInt = 1000
    ai_statement_timeout_ms: PositiveInt = 5000

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _empty_key_means_none(cls, value: object) -> object:
        # An empty ANTHROPIC_API_KEY= line in .env means "no key", not a key.
        return None if value == "" else value

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
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read from the environment once."""
    return Settings()


def current_settings() -> Settings:
    """Return the settings of the application serving the current request or command."""
    settings: Settings = current_app.extensions[SETTINGS_EXTENSION_KEY]
    return settings
