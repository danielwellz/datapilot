"""Authentication endpoints: registration, login, token refresh, logout and the current user."""

from flask import Blueprint, request
from spectree import Response

from app.api.rate_limits import RateLimitRule, enforce_rate_limit
from app.api.security import BEARER_AUTH, current_user, require_access_token, start_session
from app.api.spec import spec
from app.extensions import db
from app.schemas.auth import LoginIn, SessionOut, UserCreate, UserOut
from app.schemas.errors import ErrorOut
from app.services.auth import AuthService
from app.services.passwords import PasswordHasher

REGISTER_PER_IP = RateLimitRule(
    name="register-ip",
    limit=10,
    window_seconds=3600,
    message="Too many accounts were registered from this address. Try again later.",
)

# Two limits: per address and email, against guessing one account's password,
# and a looser one per address, against spraying one password over many emails.
LOGIN_PER_IP_AND_EMAIL = RateLimitRule(
    name="login-ip-email",
    limit=5,
    window_seconds=60,
    message="Too many login attempts for this account. Try again later.",
)
LOGIN_PER_IP = RateLimitRule(
    name="login-ip",
    limit=30,
    window_seconds=60,
    message="Too many login attempts from this address. Try again later.",
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


@auth.post("/login")
@spec.validate(
    json=LoginIn,
    resp=Response(HTTP_200=SessionOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut, HTTP_429=ErrorOut),
    tags=["auth"],
)
def login(json: LoginIn) -> SessionOut:
    """Log in with email and password.

    Returns an access token and sets the refresh token as an httpOnly cookie
    scoped to `/api/auth`, plus a readable `csrf_refresh_token` cookie whose
    value must be sent as `X-CSRF-TOKEN` to refresh or log out. Wrong
    credentials answer 401 with the same message whether or not the email
    exists. Limited to 5 attempts per minute per address and email, and 30
    per minute per address.
    """
    # Checked before the password: refused attempts cost no hashing time.
    client_ip = _client_ip()
    enforce_rate_limit(LOGIN_PER_IP, client_ip)
    enforce_rate_limit(LOGIN_PER_IP_AND_EMAIL, f"{client_ip}|{json.email}")
    user = _auth_service().authenticate(json.email, json.password.get_secret_value())
    return start_session(user)


@auth.get("/me")
@spec.validate(
    resp=Response(HTTP_200=UserOut, HTTP_401=ErrorOut), tags=["auth"], security=BEARER_AUTH
)
@require_access_token
def me() -> UserOut:
    """The user the access token belongs to."""
    return UserOut.model_validate(current_user())
