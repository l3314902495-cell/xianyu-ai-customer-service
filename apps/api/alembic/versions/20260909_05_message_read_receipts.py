"""message read receipts

Revision ID: 20260909_05
Revises: 20260828_04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260909_05"
down_revision: str | None = "20260828_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("platform_read_status", sa.Boolean(), nullable=True))
    op.add_column("messages", sa.Column("platform_read_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "platform_read_at")
    op.drop_column("messages", "platform_read_status")
