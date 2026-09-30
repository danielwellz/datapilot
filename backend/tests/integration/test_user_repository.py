from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, scoped_session

from app.models import User
from app.repositories.users import UserRepository
from tests.factories import build_user, create_user


@pytest.fixture
def users(db_session: scoped_session[Session]) -> UserRepository:
    return UserRepository(db_session())


def test_add_assigns_an_id_and_the_creation_time(users: UserRepository) -> None:
    user = users.add(User(email="ana@datapilot.dev", full_name="Ana Lima", password_hash="x"))

    assert user.id is not None
    assert user.created_at.tzinfo is not None
    assert abs(datetime.now(UTC) - user.created_at) < timedelta(minutes=1)
    assert user.last_login_at is None


def test_get_by_email_finds_the_user(users: UserRepository) -> None:
    user = create_user()

    assert users.get_by_email(user.email) is user


def test_get_by_email_returns_none_for_an_unknown_email(users: UserRepository) -> None:
    assert users.get_by_email("nobody@datapilot.dev") is None


def test_get_returns_none_for_an_unknown_id(users: UserRepository) -> None:
    assert users.get(987_654_321) is None


def test_add_raises_on_a_duplicate_email(users: UserRepository) -> None:
    create_user(email="ana@datapilot.dev")

    with pytest.raises(IntegrityError, match="uq_users_email"):
        users.add(User(email="ana@datapilot.dev", full_name="Other", password_hash="x"))


def test_database_rejects_an_email_that_is_not_lowercase(users: UserRepository) -> None:
    with pytest.raises(IntegrityError, match="ck_users_email_lowercase"):
        users.add(User(email="Ana@DataPilot.dev", full_name="Ana Lima", password_hash="x"))


def test_repr_does_not_include_the_password_hash() -> None:
    user = build_user()
    user.id = 7

    assert "argon2" not in repr(user)
    assert repr(user) == f"User(id=7, email={user.email!r})"
