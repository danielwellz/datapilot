"""Token checks for protected endpoints, the current user, and their 401 responses.

flask-jwt-extended does the token work. This module decides where each token
type may come from, loads the user a token belongs to, and renders every
token failure in the standard error envelope instead of the extension's own.
"""

import uuid
from collections.abc import Callable
from http import HTTPStatus
from typing import Any, cast

from flask import Flask, Response, after_this_request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    jwt_required,
    set_refresh_cookies,
)
from flask_jwt_extended.exceptions import CSRFError

from app.config import current_settings
from app.errors import Forbidden, Unauthorized, render_app_error
from app.extensions import db, get_redis, jwt
from app.models import User
from app.repositories.users import UserRepository
from app.schemas.auth import SessionOut, UserOut
from app.services.refresh_tokens import DEFAULT_REUSE_GRACE_SECONDS, RefreshTokenStore

# OpenAPI security requirements: an access token, or the refresh cookie
# together with its CSRF header.
BEARER_AUTH: dict[str, list[str]] = {"bearerAuth": []}
REFRESH_AUTH: dict[str, list[str]] = {"refreshCookie": [], "csrfHeader": []}

# Refresh-token claim naming the family (one per login) the token belongs to.
FAMILY_CLAIM = "fam"

# Read on every refresh rather than fixed in the store, so tests can shorten it.
REFRESH_REUSE_GRACE_SECONDS = DEFAULT_REUSE_GRACE_SECONDS


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


def require_refresh_token[**P, R](view: Callable[P, R]) -> Callable[P, R]:
    """Protect ``view`` with a refresh token from its cookie, plus the CSRF header.

    The cookie is sent by the browser automatically, even on requests another
    site triggers; the matching X-CSRF-TOKEN header proves the request came
    from a page that could read the CSRF cookie, which only our own origin can.
    """
    protected: Callable[P, R] = jwt_required(refresh=True, locations=["cookies"])(view)
    return protected


def refresh_token_store() -> RefreshTokenStore:
    return RefreshTokenStore(
        get_redis(),
        family_ttl_seconds=int(current_settings().refresh_token_ttl.total_seconds()),
        reuse_grace_seconds=REFRESH_REUSE_GRACE_SECONDS,
    )


def current_user() -> User:
    """The user whose token authenticated this request.

    Only valid inside an endpoint protected by ``require_access_token`` or
    ``require_refresh_token``.
    """
    # The extension raises when no token was verified, and _load_user only
    # ever returns a User (or None, which the extension turns into a 401).
    return cast(User, get_current_user())


def start_session(user: User, family: str | None = None) -> SessionOut:
    """Issue an access token for the response body and a refresh token for the cookie.

    A login starts a new token ``family``; a refresh passes on the family of
    the token it rotates. The cookie is attached only if the response
    succeeds, so a request that fails after this point never leaves a valid
    refresh token behind.
    """
    identity = str(user.id)
    access_token: str = create_access_token(identity=identity)
    refresh_token: str = create_refresh_token(
        identity=identity, additional_claims={FAMILY_CLAIM: family or uuid.uuid4().hex}
    )

    settings = current_settings()
    # The cookie lives exactly as long as the token inside it. Left alone, the
    # extension gives persistent cookies a one-year Max-Age.
    cookie_max_age = int(settings.refresh_token_ttl.total_seconds())

    @after_this_request
    def _set_refresh_cookie(response: Response) -> Response:
        if response.status_code == HTTPStatus.OK:
            set_refresh_cookies(response, refresh_token, max_age=cookie_max_age)
            # Token responses must never be stored by browsers or proxies (RFC 6749, 5.1).
            response.headers["Cache-Control"] = "no-store"
        return response

    return SessionOut(
        access_token=access_token,
        expires_in=int(settings.access_token_ttl.total_seconds()),
        user=UserOut.model_validate(user),
    )


def init_security(app: Flask) -> None:
    """Connect the token callbacks. Idempotent, so every app built can call it."""
    jwt.user_lookup_loader(_load_user)
    jwt.token_in_blocklist_loader(_is_revoked)
    jwt.unauthorized_loader(_reject_missing_token)
    jwt.invalid_token_loader(_reject_invalid_token)
    jwt.expired_token_loader(_reject_expired_token)
    jwt.revoked_token_loader(_reject_revoked_token)
    jwt.user_lookup_error_loader(_reject_unknown_user)
    # Replaces the extension's handler, which answers a CSRF failure with 401:
    # the caller did present a valid token, the request itself is refused.
    app.register_error_handler(CSRFError, _reject_csrf_failure)


def _load_user(_header: dict[str, Any], payload: dict[str, Any]) -> User | None:
    # Returning None makes the extension call _reject_unknown_user.
    return UserRepository(db.session()).get(int(payload["sub"]))


def _is_revoked(_header: dict[str, Any], payload: dict[str, Any]) -> bool:
    # Access tokens are not tracked: they expire within minutes, and checking
    # them would cost a Redis round trip on every API request.
    if payload["type"] != "refresh":
        return False
    family = payload.get(FAMILY_CLAIM)
    # A refresh token without a family was not issued by start_session.
    if not isinstance(family, str):
        return True
    return refresh_token_store().is_revoked(payload["jti"], family)


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


def _reject_revoked_token(_header: dict[str, Any], _payload: dict[str, Any]) -> Response:
    return _reject("The token has been revoked.")


def _reject_csrf_failure(_error: CSRFError) -> Response:
    return render_app_error(
        Forbidden(
            "The X-CSRF-TOKEN header is missing or does not match the csrf_refresh_token cookie."
        )
    )


def _reject_unknown_user(_header: dict[str, Any], _payload: dict[str, Any]) -> Response:
    return _reject("The account for this token no longer exists.")
