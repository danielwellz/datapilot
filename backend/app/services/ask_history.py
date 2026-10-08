"""The current user's past questions, newest first, in signed keyset pages."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.models import AiQuery
from app.repositories.ai_queries import AiQueryRepository, HistoryKeyset
from app.services.cursors import CursorSigner, InvalidCursor

CURSOR_PURPOSE = "datapilot.ai-history-cursor"


class _CursorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Bumped when the format changes, so older cursors fail validation.
    v: Literal[1] = 1
    created_at: datetime
    id: int


@dataclass(frozen=True, slots=True)
class HistoryPage:
    queries: list[AiQuery]
    next_cursor: str | None


class AskHistoryService:
    def __init__(self, session: Session, cursor_secret: bytes) -> None:
        self._repository = AiQueryRepository(session)
        self._cursors = CursorSigner(cursor_secret, CURSOR_PURPOSE)

    def history(self, user_id: int, *, limit: int, cursor: str | None) -> HistoryPage:
        """One page of ``user_id``'s questions; raises ``InvalidCursor`` for a foreign cursor."""
        after = self._read_cursor(cursor) if cursor is not None else None
        # One row more than the page shows whether another page follows.
        rows = self._repository.list_for_user(user_id, limit=limit + 1, after=after)
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            payload = _CursorPayload(created_at=last.created_at, id=last.id)
            next_cursor = self._cursors.sign(payload.model_dump_json().encode())
        return HistoryPage(queries=page, next_cursor=next_cursor)

    def _read_cursor(self, cursor: str) -> HistoryKeyset:
        try:
            payload = _CursorPayload.model_validate_json(self._cursors.unsign(cursor))
        except ValidationError as error:
            raise InvalidCursor() from error
        if payload.created_at.tzinfo is None:
            raise InvalidCursor()
        return HistoryKeyset(created_at=payload.created_at, id=payload.id)
