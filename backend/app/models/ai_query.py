"""The audit log of Ask your data: one row per question asked."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base


class AiQueryStatus(StrEnum):
    OK = "ok"
    # The guard refused the model's SQL; nothing ran.
    REJECTED = "rejected"
    # Anything else that ended without an answer: no usable model output,
    # a database error after the repair, a timeout, every provider failing.
    ERROR = "error"


class AiQuery(Base):
    __tablename__ = "ai_queries"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'rejected', 'error')", name="status_allowed"),
        # A failure always says which one; a success never carries a code.
        CheckConstraint("(status = 'ok') = (error_code IS NULL)", name="error_code_matches_status"),
        CheckConstraint("chart IN ('none', 'bar', 'line')", name="chart_allowed"),
        # The history endpoint pages through one user's questions, newest first.
        Index("ix_ai_queries_user_id_created_at_id", "user_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # A user's questions go with their account.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    # The registry id the analyst chose (or the default), and the model and
    # provider that actually answered after any fallback; None when none did.
    requested_model: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    # What the model wrote last, verbatim, kept for audit even when refused,
    # and what actually ran after the guard rewrote it.
    generated_sql: Mapped[str | None] = mapped_column(Text)
    executed_sql: Mapped[str | None] = mapped_column(Text)
    row_count: Mapped[int | None]
    truncated: Mapped[bool] = mapped_column(server_default=text("false"))
    repaired: Mapped[bool] = mapped_column(server_default=text("false"))
    latency_ms: Mapped[int]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    # The answer as shown, so history can show it again; result rows are
    # never stored (they can be large, and the data changes).
    explanation: Mapped[str | None] = mapped_column(Text)
    chart: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def __repr__(self) -> str:
        # Never the question or SQL: reprs end up in logs.
        return f"AiQuery(id={self.id!r}, status={self.status!r}, model={self.model!r})"
