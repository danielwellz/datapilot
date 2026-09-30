"""Builders for test data, created inside the current test's transaction.

Plain typed functions rather than factory_boy: its declarations are not
annotated, so under ``mypy --strict`` every factory call would need an
exception and every test would get ``Any`` back.
"""

import itertools
from functools import cache

from app.extensions import db
from app.models import User
from app.services.passwords import PasswordHasher

DEFAULT_PASSWORD = "factory-password-2026"

_sequence = itertools.count(1)


@cache
def default_password_hash() -> str:
    # argon2 is slow on purpose; one hash shared by every built user keeps the
    # suite fast. It uses the production parameters, so logging in with it
    # does not trigger a rehash.
    return PasswordHasher().hash(DEFAULT_PASSWORD)


def build_user(
    *,
    email: str | None = None,
    full_name: str = "Ana Lima",
    password_hash: str | None = None,
) -> User:
    """Build an unsaved user; each call gets a unique email unless one is given."""
    return User(
        email=email or f"analyst{next(_sequence)}@datapilot.dev",
        full_name=full_name,
        password_hash=password_hash or default_password_hash(),
    )


def create_user(
    *,
    email: str | None = None,
    full_name: str = "Ana Lima",
    password_hash: str | None = None,
) -> User:
    """Insert a user and flush, so it has an id and its server defaults."""
    user = build_user(email=email, full_name=full_name, password_hash=password_hash)
    db.session.add(user)
    db.session.flush()
    return user
