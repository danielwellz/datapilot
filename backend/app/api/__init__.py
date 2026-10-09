"""HTTP layer: every endpoint lives under the ``/api`` blueprint.

Feature blueprints are nested into ``api`` here, at import time: Flask does
not allow nesting once ``api`` has been registered on an application, and
the app factory registers it on every app it builds.
"""

from flask import Blueprint, Flask, Response, request

from app.api.ai import ai
from app.api.analytics import analytics
from app.api.auth import auth
from app.api.docs import docs
from app.api.meta import meta
from app.api.orders import orders
from app.api.system import system
from app.errors import BadRequest, UnsupportedMediaType

_METHODS_WITH_BODY = frozenset({"POST", "PUT", "PATCH"})

# JSON is never a page: a browser must not render, frame or sniff it. A
# response that is a page (the Swagger UI) sets its own policy first.
_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

api = Blueprint("api", __name__, url_prefix="/api")
api.register_blueprint(ai)
api.register_blueprint(analytics)
api.register_blueprint(auth)
api.register_blueprint(docs)
api.register_blueprint(meta)
api.register_blueprint(orders)
api.register_blueprint(system)


def require_json_body() -> None:
    """Reject request bodies that are not JSON before validation sees them.

    Without this, spectree reads a malformed or non-JSON body as ``{}`` and
    the client gets a misleading "field required" error.
    """
    if request.method not in _METHODS_WITH_BODY or not request.get_data(cache=True):
        return
    # An unknown URL or method must still answer 404 or 405, which Flask raises
    # only after the before_request hooks have run.
    if request.routing_exception is not None:
        return
    if not request.is_json:
        raise UnsupportedMediaType("Request bodies must be JSON (Content-Type: application/json).")
    if request.get_json(silent=True) is None:
        raise BadRequest("The request body is not valid JSON.")


def add_security_headers(response: Response) -> Response:
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


def register_blueprints(app: Flask) -> None:
    """Register the API, its JSON-only body policy and the headers of every response."""
    app.before_request(require_json_body)
    app.after_request(add_security_headers)
    app.register_blueprint(api)
