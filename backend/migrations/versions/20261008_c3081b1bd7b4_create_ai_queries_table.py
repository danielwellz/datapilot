"""create ai queries table

Revision ID: c3081b1bd7b4
Revises: 6e5cbd81682d
Create Date: 2026-10-08 16:48:27.441591

The audit log of Ask your data: every question, the model that answered it,
the SQL it wrote and what became of it. Result rows are not stored. The
index serves the history endpoint, which pages through one user's questions
newest first; the table starts empty, so it is built in the same
transaction rather than concurrently.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision = "c3081b1bd7b4"
down_revision = "6e5cbd81682d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_queries",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("requested_model", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("executed_sql", sa.Text(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("truncated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("repaired", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("chart", sa.Text(), nullable=True),
        sa.Column(
            "assumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'ok') = (error_code IS NULL)",
            name=op.f("ck_ai_queries_error_code_matches_status"),
        ),
        sa.CheckConstraint(
            "chart IN ('none', 'bar', 'line')", name=op.f("ck_ai_queries_chart_allowed")
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'rejected', 'error')", name=op.f("ck_ai_queries_status_allowed")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ai_queries_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_queries")),
    )
    op.create_index(
        "ix_ai_queries_user_id_created_at_id", "ai_queries", ["user_id", "created_at", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ai_queries_user_id_created_at_id", table_name="ai_queries")
    op.drop_table("ai_queries")
