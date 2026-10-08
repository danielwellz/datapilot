"""create analytics views and readonly role

Revision ID: 6e5cbd81682d
Revises: 959f4df99a26
Create Date: 2026-10-08 20:21:17.182016

Ask your data runs SQL written by a language model. That SQL never touches
the application tables directly: it runs as ``datapilot_readonly``, which can
read only the curated views in the ``analytics`` schema created here. The
views leave out every personal field (customer names and emails), and the
role is read-only with a statement timeout, whatever SQL it is given.

The role is created without a password. A password in a migration would end
up in the repository, so ``flask db-roles`` sets it from READONLY_DATABASE_URL.
Every statement is idempotent, so the migration also succeeds on a cluster
where another database already created the role (roles are cluster-wide).

The column comments are part of the feature, not decoration: the prompt's
schema description is generated from them.
"""

from alembic import op

# Revision identifiers, used by Alembic.
revision = "6e5cbd81682d"
down_revision = "959f4df99a26"
branch_labels = None
depends_on = None

_ROLE = "datapilot_readonly"

_CREATE_ROLE = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{_ROLE}') THEN
        CREATE ROLE {_ROLE} NOLOGIN;
    END IF;
END
$$
"""

# Stated explicitly so a role that existed before with other attributes is
# brought back to exactly these.
_ROLE_ATTRIBUTES = (
    f"ALTER ROLE {_ROLE} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
)

# Applied by the server at login, before any SQL from the application runs.
# The executor sets the same values per transaction as well, because
# ``SET ROLE`` (used by the tests) does not apply login-time settings.
_ROLE_SETTINGS = (
    f"ALTER ROLE {_ROLE} SET default_transaction_read_only = on",
    f"ALTER ROLE {_ROLE} SET statement_timeout = '5s'",
    f"ALTER ROLE {_ROLE} SET idle_in_transaction_session_timeout = '10s'",
    f"ALTER ROLE {_ROLE} SET search_path = analytics",
)

_VIEWS = {
    "v_orders": "SELECT id, customer_id, status, channel, total, created_at FROM public.orders",
    "v_order_items": ("SELECT order_id, product_id, quantity, unit_price FROM public.order_items"),
    "v_customers": "SELECT id, country, signed_up_at FROM public.customers",
    "v_products": "SELECT id, name, category, price FROM public.products",
}

_VIEW_COMMENTS = {
    "v_orders": "One row per order placed in the store, in any status.",
    "v_order_items": "The products in each order: one row per order and product.",
    "v_customers": "Customers of the store. Personal details are deliberately not available.",
    "v_products": "The product catalog.",
}

_COLUMN_COMMENTS = {
    "v_orders": {
        "id": "Order id.",
        "customer_id": "The customer who placed the order (v_customers.id).",
        "status": (
            "'paid', 'refunded' or 'cancelled'. Only paid orders count as revenue and "
            "as sales; refunded and cancelled orders do not."
        ),
        "channel": "Where the order was placed: 'web', 'mobile' or 'marketplace'.",
        "total": (
            "Order value in the store currency, numeric(12,2). Equals the sum of "
            "quantity * unit_price over the order's items."
        ),
        "created_at": "When the order was placed (timestamptz; dates are in UTC).",
    },
    "v_order_items": {
        "order_id": "The order (v_orders.id).",
        "product_id": "The product (v_products.id).",
        "quantity": "Units of the product in the order, at least 1.",
        "unit_price": "Price of one unit when the order was placed, numeric(10,2).",
    },
    "v_customers": {
        "id": "Customer id.",
        "country": "ISO 3166-1 alpha-2 country code, for example 'US', 'GB' or 'DE'.",
        "signed_up_at": "When the customer created their account (timestamptz, UTC).",
    },
    "v_products": {
        "id": "Product id.",
        "name": "Product name.",
        "category": (
            "One of 'Electronics', 'Home & Kitchen', 'Clothing', 'Books', "
            "'Sports & Outdoors', 'Beauty', 'Toys & Games', 'Office', 'Garden', 'Grocery'."
        ),
        "price": "Current list price, numeric(10,2).",
    },
}


def _literal(text: str) -> str:
    # The comments are constants in this file; doubling quotes is all a
    # literal needs here.
    return "'" + text.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(_CREATE_ROLE)
    op.execute(_ROLE_ATTRIBUTES)
    for statement in _ROLE_SETTINGS:
        op.execute(statement)

    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")
    for view, query in _VIEWS.items():
        op.execute(f"CREATE OR REPLACE VIEW analytics.{view} AS {query}")
        op.execute(f"COMMENT ON VIEW analytics.{view} IS {_literal(_VIEW_COMMENTS[view])}")
        for column, comment in _COLUMN_COMMENTS[view].items():
            op.execute(f"COMMENT ON COLUMN analytics.{view}.{column} IS {_literal(comment)}")

    # Views run with their owner's privileges, so SELECT on a view is all the
    # role needs: it never receives any privilege on the tables behind them.
    op.execute("REVOKE ALL ON SCHEMA analytics FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA analytics TO {_ROLE}")
    for view in _VIEWS:
        op.execute(f"REVOKE ALL ON analytics.{view} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON analytics.{view} TO {_ROLE}")

    # PostgreSQL lets every role use the public schema by default. Revoking
    # that (the "secure schema usage pattern" of the PostgreSQL docs) means
    # the role is refused at the schema before table privileges are even
    # checked. The database owner, which owns the schema, keeps its access.
    op.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO {_ROLE}', current_database());
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM {_ROLE}', current_database());
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO PUBLIC")
    op.execute("DROP SCHEMA analytics CASCADE")
    # The role stays: it is shared by every database of the cluster (the
    # development and test databases both use it), so one database's
    # downgrade must not remove it from the others.
