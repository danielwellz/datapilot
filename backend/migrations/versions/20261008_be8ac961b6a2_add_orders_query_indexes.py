"""add orders query indexes

Revision ID: be8ac961b6a2
Revises: 6d4127eca7e1
Create Date: 2026-10-08 18:05:00.000000

Each index was chosen from EXPLAIN (ANALYZE, BUFFERS) on the full dataset;
docs/performance.md shows the plans before and after. Every one ends with
``id`` so keyset pagination can seek to (sort value, id) inside it.
"""

from alembic import op

# Revision identifiers, used by Alembic.
revision = "be8ac961b6a2"
down_revision = "6d4127eca7e1"
branch_labels = None
depends_on = None

# name, columns. Ascending: a B-tree is read backwards just as fast, so the
# descending sorts of the orders list need no DESC index.
_INDEXES = (
    # Default list, date ranges, deep pages, and min/max order date.
    ("ix_orders_created_at_id", ["created_at", "id"]),
    # The list sorted by total.
    ("ix_orders_total_id", ["total", "id"]),
    # One customer's orders, newest first; also serves lookups by customer_id.
    ("ix_orders_customer_id_created_at_id", ["customer_id", "created_at", "id"]),
)


def upgrade() -> None:
    # CONCURRENTLY builds an index without blocking writes to the table for
    # the length of the build, but cannot run inside a transaction. If a build
    # fails it leaves an INVALID index behind: drop it, then upgrade again.
    with op.get_context().autocommit_block():
        for name, columns in _INDEXES:
            op.create_index(name, "orders", columns, postgresql_concurrently=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _ in reversed(_INDEXES):
            op.drop_index(name, table_name="orders", postgresql_concurrently=True)
