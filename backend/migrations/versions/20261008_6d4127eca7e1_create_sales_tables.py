"""create sales tables

Revision ID: 6d4127eca7e1
Revises: 826bf59f5c11
Create Date: 2026-10-08 11:59:35.827903
"""

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision = "6d4127eca7e1"
down_revision = "826bf59f5c11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keys and constraints only. Indexes for filtering and joining (customer_id,
    # created_at, status, product_id) come in a later migration, once their
    # effect has been measured on the seeded data.
    op.create_table(
        "customers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("country", sa.CHAR(length=2), nullable=False),
        sa.Column("signed_up_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("country ~ '^[A-Z]{2}$'", name=op.f("ck_customers_country_iso_alpha2")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("email", name=op.f("uq_customers_email")),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.CheckConstraint("price >= 0", name=op.f("ck_products_price_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "channel IN ('web', 'mobile', 'marketplace')", name=op.f("ck_orders_channel_allowed")
        ),
        sa.CheckConstraint(
            "status IN ('paid', 'refunded', 'cancelled')", name=op.f("ck_orders_status_allowed")
        ),
        sa.CheckConstraint("total >= 0", name=op.f("ck_orders_total_non_negative")),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name=op.f("fk_orders_customer_id_customers")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
    )
    op.create_table(
        "order_items",
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_items_quantity_positive")),
        sa.CheckConstraint("unit_price >= 0", name=op.f("ck_order_items_unit_price_non_negative")),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_items_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_order_items_product_id_products")
        ),
        sa.PrimaryKeyConstraint("order_id", "product_id", name=op.f("pk_order_items")),
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("products")
    op.drop_table("customers")
