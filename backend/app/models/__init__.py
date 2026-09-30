"""SQLAlchemy models.

Every model is imported here so that ``db.metadata`` is complete whenever the
application is built, which Alembic autogenerate relies on.
"""

from app.models.user import User

__all__ = ["User"]
