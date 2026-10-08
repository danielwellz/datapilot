"""Queries for the Ask your data audit log."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import literal, select, tuple_
from sqlalchemy.orm import Session

from app.models import AiQuery


@dataclass(frozen=True, slots=True)
class HistoryKeyset:
    """Where the previous history page ended: its last row's creation time and id."""

    created_at: datetime
    id: int


class AiQueryRepository:
    """Stores and lists audit rows within the caller's session and transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, query: AiQuery) -> AiQuery:
        """Insert ``query`` and flush, so its id and creation time are loaded."""
        self._session.add(query)
        self._session.flush()
        return query

    def list_for_user(
        self, user_id: int, *, limit: int, after: HistoryKeyset | None = None
    ) -> list[AiQuery]:
        """One user's questions, newest first, starting after ``after``."""
        statement = (
            select(AiQuery)
            .where(AiQuery.user_id == user_id)
            # id breaks ties between questions asked in the same microsecond.
            .order_by(AiQuery.created_at.desc(), AiQuery.id.desc())
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(
                tuple_(AiQuery.created_at, AiQuery.id)
                < tuple_(
                    literal(after.created_at, AiQuery.created_at.type),
                    literal(after.id, AiQuery.id.type),
                )
            )
        return list(self._session.scalars(statement))
