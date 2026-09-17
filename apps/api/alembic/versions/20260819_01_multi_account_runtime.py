"""multi-account runtime state and product isolation

Revision ID: 20260819_01
Revises: 8396d6bbbe5d
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260819_01"
down_revision: str | None = "8396d6bbbe5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    account_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("xianyu_accounts")
    }
    if "last_error" not in account_columns:
        op.add_column("xianyu_accounts", sa.Column("last_error", sa.Text(), nullable=True))
    if "updated_at" not in account_columns:
        op.add_column(
            "xianyu_accounts",
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.execute(
            sa.text("UPDATE xianyu_accounts SET updated_at = CURRENT_TIMESTAMP")
        )
        with op.batch_alter_table("xianyu_accounts") as batch_op:
            batch_op.alter_column(
                "updated_at",
                existing_type=sa.DateTime(),
                nullable=False,
            )
    op.drop_index("ix_products_external_product_id", table_name="products")
    with op.batch_alter_table("products") as batch_op:
        batch_op.create_unique_constraint(
            "uq_product_account_external",
            ["account_id", "external_product_id"],
        )
    op.create_index(
        "ix_products_external_product_id",
        "products",
        ["external_product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_products_external_product_id", table_name="products")
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_constraint("uq_product_account_external", type_="unique")
    op.create_index(
        "ix_products_external_product_id",
        "products",
        ["external_product_id"],
        unique=True,
    )
    op.drop_column("xianyu_accounts", "updated_at")
    op.drop_column("xianyu_accounts", "last_error")
