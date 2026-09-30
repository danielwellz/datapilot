"""Account registration and credential checks."""

from datetime import UTC, datetime

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import Conflict, Unauthorized
from app.models import User
from app.repositories.users import UserRepository
from app.schemas.auth import UserCreate
from app.services.passwords import PasswordHasher

_EMAIL_UNIQUE_CONSTRAINT = "uq_users_email"


class EmailAlreadyRegistered(Conflict):
    default_message = "An account with this email address already exists."


class InvalidCredentials(Unauthorized):
    # One message for an unknown email and a wrong password, so the answer
    # never reveals which emails have accounts.
    default_message = "Email or password is incorrect."


class AuthService:
    """Business rules for accounts; owns the transaction of each operation."""

    def __init__(self, session: Session, passwords: PasswordHasher) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._passwords = passwords

    def register(self, data: UserCreate) -> User:
        """Create an account, or raise ``EmailAlreadyRegistered``.

        The lookup gives the common case a clear answer without a failed
        insert; the unique constraint still decides when two registrations
        for the same email race each other.
        """
        if self._users.get_by_email(data.email) is not None:
            raise EmailAlreadyRegistered(details=[{"field": "email"}])
        user = User(
            email=data.email,
            full_name=data.full_name,
            password_hash=self._passwords.hash(data.password.get_secret_value()),
        )
        try:
            self._users.add(user)
        except IntegrityError as error:
            self._session.rollback()
            if _violates_unique(error, _EMAIL_UNIQUE_CONSTRAINT):
                raise EmailAlreadyRegistered(details=[{"field": "email"}]) from error
            raise
        self._session.commit()
        return user

    def authenticate(self, email: str, password: str) -> User:
        """Return the user these credentials belong to, or raise ``InvalidCredentials``.

        Both failure paths cost one argon2 verification, so response time
        does not reveal whether the email exists either. A successful login
        upgrades a hash made with outdated parameters, the only moment the
        plain password is available to rehash.
        """
        user = self._users.get_by_email(email)
        if user is None:
            self._passwords.verify_against_dummy(password)
            raise InvalidCredentials
        if not self._passwords.verify(user.password_hash, password):
            raise InvalidCredentials
        if self._passwords.needs_rehash(user.password_hash):
            user.password_hash = self._passwords.hash(password)
        user.last_login_at = datetime.now(UTC)
        self._session.commit()
        return user


def _violates_unique(error: IntegrityError, constraint: str) -> bool:
    cause = error.orig
    return isinstance(cause, UniqueViolation) and cause.diag.constraint_name == constraint
