"""DataPilot backend application package."""

from flask import Flask


def create_app() -> Flask:
    """Build a new, fully independent Flask application.

    A factory rather than a module-level app lets tests create isolated
    instances and lets each process (dev server, Gunicorn worker, CLI)
    configure its own.
    """
    return Flask(__name__)
