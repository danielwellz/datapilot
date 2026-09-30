"""Settings for tests, built only from explicit values.

Tests must behave the same on every machine, so they never read the
developer's shell environment or ``.env`` file. The two connection strings
are the exception: CI and developers point them at their own services.
"""

import os
from typing import Any

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from app.config import Settings

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://datapilot:datapilot@localhost:5433/datapilot_test"
DEFAULT_TEST_REDIS_URL = "redis://localhost:6379/15"


class IsolatedSettings(Settings):
    """Settings that read constructor arguments and nothing else."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def make_test_settings(**overrides: Any) -> Settings:
    """Build test settings; keyword arguments replace individual values."""
    values: dict[str, Any] = {
        "app_env": "test",
        "secret_key": "test-secret-key",
        "jwt_secret_key": "test-jwt-secret-key-of-32-characters",
        "database_url": os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
        "redis_url": os.environ.get("TEST_REDIS_URL", DEFAULT_TEST_REDIS_URL),
    }
    return IsolatedSettings(**(values | overrides))
