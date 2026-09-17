"""product publish attempts

Revision ID: 20260910_06
Revises: 20260909_05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260910_06"
down_revision: str | None = "20260909_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_publish_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("request_summary", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("external_product_id", sa.String(length=120), nullable=True),
        sa.Column("product_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["xianyu_accounts.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_publish_attempts_account_id", "product_publish_attempts", ["account_id"])
    op.create_index("ix_product_publish_attempts_created_at", "product_publish_attempts", ["created_at"])
    op.create_index("ix_product_publish_attempts_idempotency_key", "product_publish_attempts", ["idempotency_key"], unique=True)
    op.create_index("ix_product_publish_attempts_status", "product_publish_attempts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_product_publish_attempts_status", table_name="product_publish_attempts")
    op.drop_index("ix_product_publish_attempts_idempotency_key", table_name="product_publish_attempts")
    op.drop_index("ix_product_publish_attempts_created_at", table_name="product_publish_attempts")
    op.drop_index("ix_product_publish_attempts_account_id", table_name="product_publish_attempts")
    op.drop_table("product_publish_attempts")
