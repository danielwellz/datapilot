"""DataPilot backend application package."""

from flask import Flask

from app.config import SETTINGS_EXTENSION_KEY, Settings, get_settings
from app.errors import register_error_handlers
from app.logging import configure_logging, init_request_logging


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
    )
    app.extensions[SETTINGS_EXTENSION_KEY] = settings

    # Registered first so every later hook and handler can use the request id.
    init_request_logging(app)
    register_error_handlers(app)
    return app
