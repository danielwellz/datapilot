"""add paid orders customer index

Revision ID: 959f4df99a26
Revises: 239eec08d96c
Create Date: 2026-10-08 14:42:04.113852

A partial index on the paid orders of each customer, for the cohort query:
it joins cohort members to their paid orders and needs only customer_id and
created_at. With the index the join reads it alone (an index-only scan)
instead of fetching each order's row to check its status, which took the
24-month cohorts past the 800 ms target. docs/performance.md shows the plans
before and after, and the alternatives measured.
"""

from alembic import op

# Revision identifiers, used by Alembic.
revision = "959f4df99a26"
down_revision = "239eec08d96c"
branch_labels = None
depends_on = None

_NAME = "ix_orders_paid_customer_id_created_at"


def upgrade() -> None:
    # Built without blocking writes, as in be8ac961b6a2. If the build fails
    # it leaves an INVALID index behind: drop it, then upgrade again.
    with op.get_context().autocommit_block():
        op.create_index(
            _NAME,
            "orders",
            ["customer_id", "created_at"],
            postgresql_where="status = 'paid'",
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(_NAME, table_name="orders", postgresql_concurrently=True)
