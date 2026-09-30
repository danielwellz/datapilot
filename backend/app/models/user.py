"""Accounts of the analysts who use DataPilot."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Identity, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base

# RFC 5321 limits a forward path to 256 octets including the angle brackets.
EMAIL_MAX_LENGTH = 254
FULL_NAME_MAX_LENGTH = 100


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Emails are compared case-insensitively. Storing them lowercase lets a
        # plain unique index enforce that; this check stops any write path from
        # bypassing the normalization.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True)
    full_name: Mapped[str] = mapped_column(String(FULL_NAME_MAX_LENGTH))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_login_at: Mapped[datetime | None]

    def __repr__(self) -> str:
        # Never include the password hash: reprs end up in logs and tracebacks.
        return f"User(id={self.id!r}, email={self.email!r})"
