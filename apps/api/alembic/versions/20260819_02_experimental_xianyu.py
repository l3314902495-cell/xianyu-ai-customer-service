"""encrypted credentials for experimental Xianyu adapter

Revision ID: 20260819_02
Revises: 20260819_01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260819_02"
down_revision: str | None = "20260819_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "xianyu_account_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("credential_type", sa.String(length=40), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["xianyu_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id"),
    )
    op.create_index(
        op.f("ix_xianyu_account_credentials_account_id"),
        "xianyu_account_credentials",
        ["account_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_xianyu_account_credentials_account_id"), table_name="xianyu_account_credentials")
    op.drop_table("xianyu_account_credentials")
