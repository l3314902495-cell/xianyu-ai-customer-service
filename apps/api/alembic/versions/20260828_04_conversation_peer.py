"""conversation peer profile

Revision ID: 20260828_04
Revises: 20260828_03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_04"
down_revision: str | None = "20260828_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("buyer_avatar", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "buyer_avatar")
