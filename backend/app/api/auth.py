"""Authentication endpoints: registration, login, token refresh, logout and the current user."""

from flask import Blueprint, request
from spectree import Response

from app.api.rate_limits import RateLimitRule, enforce_rate_limit
from app.api.spec import spec
from app.extensions import db
from app.schemas.auth import UserCreate, UserOut
from app.schemas.errors import ErrorOut
from app.services.auth import AuthService
from app.services.passwords import PasswordHasher

REGISTER_PER_IP = RateLimitRule(
    name="register-ip",
    limit=10,
    window_seconds=3600,
    message="Too many accounts were registered from this address. Try again later.",
)

auth = Blueprint("auth", __name__, url_prefix="/auth")

# One hasher per process: it holds the lazily computed dummy hash.
_passwords = PasswordHasher()


def _auth_service() -> AuthService:
    return AuthService(db.session(), _passwords)


def _client_ip() -> str:
    # The direct peer. Behind a reverse proxy this must come from a trusted
    # X-Forwarded-For hop instead (ProxyFix), or every client shares one limit.
    return request.remote_addr or "unknown"


@auth.post("/register")
@spec.validate(
    json=UserCreate,
    resp=Response(HTTP_201=UserOut, HTTP_409=ErrorOut, HTTP_422=ErrorOut, HTTP_429=ErrorOut),
    tags=["auth"],
)
def register(json: UserCreate) -> tuple[UserOut, int]:
    """Create an account.

    Answers 409 when the email is already registered. Limited to 10
    registrations per hour per client address.
    """
    enforce_rate_limit(REGISTER_PER_IP, _client_ip())
    user = _auth_service().register(json)
    return UserOut.model_validate(user), 201
