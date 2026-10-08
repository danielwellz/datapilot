from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, scoped_session

from app.models import AiQuery, AiQueryStatus, User
from app.repositories.ai_queries import AiQueryRepository, HistoryKeyset
from tests.factories import create_ai_query, create_user

T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)


def test_add_stores_the_row_with_its_defaults(db_session: scoped_session[Session]) -> None:
    user = create_user()
    query = AiQuery(
        user_id=user.id,
        question="Orders?",
        requested_model="groq-gpt-oss-120b",
        model=None,
        provider=None,
        prompt_version="2026-10-08.1",
        status=AiQueryStatus.ERROR,
        error_code="llm_unavailable",
        latency_ms=30_000,
    )

    stored = AiQueryRepository(db_session()).add(query)

    assert stored.id is not None
    assert stored.created_at is not None
    assert (stored.truncated, stored.repaired, stored.assumptions) == (False, False, [])


def test_history_lists_one_users_questions_newest_first_in_keyset_pages(
    db_session: scoped_session[Session],
) -> None:
    user, other = create_user(), create_user()
    # Two questions share a timestamp: id must order them.
    times = [T0, T0 + timedelta(minutes=1), T0 + timedelta(minutes=1), T0 + timedelta(minutes=2)]
    rows = [create_ai_query(user, created_at=moment) for moment in times]
    create_ai_query(other, created_at=T0 + timedelta(minutes=5))
    repository = AiQueryRepository(db_session())

    first = repository.list_for_user(user.id, limit=2)
    last = first[-1]
    second = repository.list_for_user(
        user.id, limit=2, after=HistoryKeyset(last.created_at, last.id)
    )

    expected = [rows[3].id, rows[2].id, rows[1].id, rows[0].id]
    assert [row.id for row in first + second] == expected
    tail = second[-1]
    assert (
        repository.list_for_user(user.id, limit=2, after=HistoryKeyset(tail.created_at, tail.id))
        == []
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "pending"},
        {"status": AiQueryStatus.OK, "error_code": "sql_rejected"},
        {"status": AiQueryStatus.REJECTED, "error_code": None},
        {"chart": "pie"},
    ],
)
def test_the_table_refuses_inconsistent_rows(overrides: dict[str, object]) -> None:
    with pytest.raises(IntegrityError):
        create_ai_query(create_user(), **overrides)


def test_a_users_questions_are_deleted_with_the_account(
    db_session: scoped_session[Session],
) -> None:
    user = create_user()
    create_ai_query(user)

    db_session.execute(delete(User).where(User.id == user.id))

    assert AiQueryRepository(db_session()).list_for_user(user.id, limit=10) == []


def test_repr_leaves_out_the_question_and_sql() -> None:
    query = create_ai_query(create_user(), question="secret plans?")

    assert repr(query) == f"AiQuery(id={query.id!r}, status='ok', model='fake')"
