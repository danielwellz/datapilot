"""HTTP layer: every endpoint lives under the ``/api`` blueprint.

Feature blueprints are nested into ``api`` here, at import time: Flask does
not allow nesting once ``api`` has been registered on an application, and
the app factory registers it on every app it builds.
"""

from flask import Blueprint, Flask, request
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from app.api.docs import docs
from app.api.system import system

_METHODS_WITH_BODY = frozenset({"POST", "PUT", "PATCH"})

api = Blueprint("api", __name__, url_prefix="/api")
api.register_blueprint(docs)
api.register_blueprint(system)


def require_json_body() -> None:
    """Reject request bodies that are not JSON before validation sees them.

    Without this, spectree reads a malformed or non-JSON body as ``{}`` and
    the client gets a misleading "field required" error.
    """
    if request.method not in _METHODS_WITH_BODY or not request.get_data(cache=True):
        return
    if not request.is_json:
        raise UnsupportedMediaType("Request bodies must be JSON (Content-Type: application/json).")
    if request.get_json(silent=True) is None:
        raise BadRequest("The request body is not valid JSON.")


def register_blueprints(app: Flask) -> None:
    """Register the API and the JSON-only body policy that applies to every endpoint."""
    app.before_request(require_json_body)
    app.register_blueprint(api)
