"""Token checks for protected endpoints, the current user, and their 401 responses.

flask-jwt-extended does the token work. This module decides where each token
type may come from, loads the user a token belongs to, and renders every
token failure in the standard error envelope instead of the extension's own.
"""

from collections.abc import Callable
from typing import Any, cast

from flask import Response
from flask_jwt_extended import get_current_user, jwt_required

from app.errors import Unauthorized, render_app_error
from app.extensions import db, jwt
from app.models import User
from app.repositories.users import UserRepository

# OpenAPI security requirement for endpoints that take an access token.
BEARER_AUTH: dict[str, list[str]] = {"bearerAuth": []}


class TokenRejected(Unauthorized):
    """A missing or unusable token.

    RFC 6750 asks a 401 from a bearer-protected resource to name the scheme,
    so clients know how to authenticate.
    """

    @property
    def headers(self) -> dict[str, str]:
        return {"WWW-Authenticate": "Bearer"}


def require_access_token[**P, R](view: Callable[P, R]) -> Callable[P, R]:
    """Protect ``view`` with an access token from the Authorization header.

    Refresh tokens are rejected, and a token in a cookie is never looked at,
    so a cross-site request cannot authenticate through the browser's cookies.
    """
    protected: Callable[P, R] = jwt_required(locations=["headers"])(view)
    return protected


def current_user() -> User:
    """The user whose token authenticated this request.

    Only valid inside an endpoint protected by ``require_access_token``.
    """
    # The extension raises when no token was verified, and _load_user only
    # ever returns a User (or None, which the extension turns into a 401).
    return cast(User, get_current_user())


def init_security() -> None:
    """Connect the token callbacks. Idempotent, so every app built can call it."""
    jwt.user_lookup_loader(_load_user)
    jwt.unauthorized_loader(_reject_missing_token)
    jwt.invalid_token_loader(_reject_invalid_token)
    jwt.expired_token_loader(_reject_expired_token)
    jwt.user_lookup_error_loader(_reject_unknown_user)


def _load_user(_header: dict[str, Any], payload: dict[str, Any]) -> User | None:
    # Returning None makes the extension call _reject_unknown_user.
    return UserRepository(db.session()).get(int(payload["sub"]))


def _reject(message: str) -> Response:
    return render_app_error(TokenRejected(message))


def _reject_missing_token(_reason: str) -> Response:
    return _reject("Authentication is required.")


def _reject_invalid_token(_reason: str) -> Response:
    # The reason (bad signature, wrong token type, malformed header) stays
    # server-side: it helps an attacker more than a legitimate client.
    return _reject("The token is invalid.")


def _reject_expired_token(_header: dict[str, Any], _payload: dict[str, Any]) -> Response:
    return _reject("The token has expired.")


def _reject_unknown_user(_header: dict[str, Any], _payload: dict[str, Any]) -> Response:
    return _reject("The account for this token no longer exists.")
