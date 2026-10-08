"""The prompt's description of the analytics views, read from the database itself.

The views and their column comments are created by a migration, so reading
them from the catalog keeps the prompt in step with what the read-only role
can actually query: there is no second, hand-written copy to drift.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ai.sql_guard import ALLOWED_SCHEMA, ALLOWED_VIEWS

_COLUMNS_SQL = text(
    """
    SELECT c.relname AS view,
           obj_description(c.oid, 'pg_class') AS view_comment,
           a.attname AS column,
           format_type(a.atttypid, a.atttypmod) AS type,
           col_description(c.oid, a.attnum) AS column_comment
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
    WHERE n.nspname = :schema
      AND c.relkind = 'v'
      AND c.relname = ANY(:views)
      AND a.attnum > 0
      AND NOT a.attisdropped
    ORDER BY c.relname, a.attnum
    """
)


class SchemaDescriptionError(RuntimeError):
    """The analytics views are missing, so no prompt can describe them."""


def describe_analytics_views(session: Session) -> str:
    """One block per view: its name and purpose, then each column with its type and meaning."""
    rows = session.execute(
        _COLUMNS_SQL, {"schema": ALLOWED_SCHEMA, "views": sorted(ALLOWED_VIEWS)}
    ).all()
    found = {row.view for row in rows}
    if found != ALLOWED_VIEWS:
        missing = ", ".join(sorted(ALLOWED_VIEWS - found))
        raise SchemaDescriptionError(f"analytics views missing: {missing}; run the migrations")

    lines: list[str] = []
    current_view = None
    for row in rows:
        if row.view != current_view:
            current_view = row.view
            if lines:
                lines.append("")
            lines.append(f"{row.view}: {row.view_comment or ''}".rstrip())
        comment = f": {row.column_comment}" if row.column_comment else ""
        lines.append(f"  - {row.column} ({row.type}){comment}")
    return "\n".join(lines)
