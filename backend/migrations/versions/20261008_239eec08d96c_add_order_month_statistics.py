"""add order month statistics

Revision ID: 239eec08d96c
Revises: be8ac961b6a2
Create Date: 2026-10-08 14:27:15.795739

Extended statistics on the UTC month of ``orders.created_at``, the group key
of the monthly revenue query. PostgreSQL keeps no statistics on an
expression by default, so it assumed a GROUP BY on it yields almost one
group per row (1.86 million instead of 36) and rejected the parallel
aggregate. docs/performance.md shows the plans before and after.

The expression must match the one in app/analytics/sql/revenue_monthly.sql:
the planner uses these statistics only for an identical expression.
"""

from alembic import op

# Revision identifiers, used by Alembic.
revision = "239eec08d96c"
down_revision = "be8ac961b6a2"
branch_labels = None
depends_on = None

_NAME = "st_orders_created_month_utc"


def upgrade() -> None:
    op.execute(
        f"CREATE STATISTICS {_NAME} "
        "ON (CAST(date_trunc('month', created_at AT TIME ZONE 'UTC') AS date)) FROM orders"
    )
    # The statistics stay empty until the table is analysed; the seed
    # analyses after every load, and this covers a database loaded before.
    op.execute("ANALYZE orders")


def downgrade() -> None:
    op.execute(f"DROP STATISTICS {_NAME}")
