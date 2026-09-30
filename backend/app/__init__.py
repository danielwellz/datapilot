"""DataPilot backend application package."""

from flask import Flask

# Imported for its side effect: every model registers its table on the shared
# metadata, which Alembic autogenerate compares against the database.
import app.models  # noqa: F401
from app.api import register_blueprints
from app.cli import register_cli
from app.config import SETTINGS_EXTENSION_KEY, Settings, get_settings
from app.errors import register_error_handlers
from app.extensions import init_extensions
from app.logging import configure_logging, init_request_logging

_MAX_REQUEST_BODY_BYTES = 1024 * 1024


def create_app(settings: Settings | None = None) -> Flask:
    """Build a new, fully independent Flask application.

    A factory rather than a module-level app lets tests create isolated
    instances and lets each process (dev server, Gunicorn worker, CLI)
    configure its own. Tests pass their own ``settings`` so they never read
    the developer's environment or ``.env`` file.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    # A JSON API: there are no static files to serve.
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=settings.secret_key.get_secret_value(),
        TESTING=settings.app_env == "test",
        # Bodies are small JSON documents; anything larger is refused with 413.
        MAX_CONTENT_LENGTH=_MAX_REQUEST_BODY_BYTES,
    )
    app.extensions[SETTINGS_EXTENSION_KEY] = settings

    # Registered first so every later hook and handler can use the request id.
    init_request_logging(app)
    register_error_handlers(app)
    init_extensions(app, settings)
    register_blueprints(app)
    register_cli(app)
    return app
