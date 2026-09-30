"""Queries for user accounts."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


class UserRepository:
    """Loads and stores users within the caller's session and transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: int) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        """Find a user by an email that the caller has already normalized to lowercase."""
        return self._session.scalars(select(User).where(User.email == email)).one_or_none()

    def add(self, user: User) -> User:
        """Insert ``user`` and flush, so its id and server defaults are loaded.

        Flushing here also surfaces a unique-constraint violation at this call,
        where the caller can translate it, rather than at commit.
        """
        self._session.add(user)
        self._session.flush()
        return user
