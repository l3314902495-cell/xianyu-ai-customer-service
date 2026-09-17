"""delivery saga leases and manual resolution

Revision ID: 20260917_07
Revises: 20260910_06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_07"
down_revision: str | None = "20260910_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("delivery_records", sa.Column("reply_id", sa.String(length=160), nullable=True))
    op.add_column("delivery_records", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column("delivery_records", sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE delivery_records SET reply_id = 'delivery-' || id WHERE reply_id IS NULL")
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("delivery_records", "reply_id", nullable=False)
    op.create_index("ix_delivery_records_reply_id", "delivery_records", ["reply_id"], unique=True)
    op.create_index(
        "ix_delivery_records_status_lease",
        "delivery_records",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_records_status_lease", table_name="delivery_records")
    op.drop_index("ix_delivery_records_reply_id", table_name="delivery_records")
    op.drop_column("delivery_records", "resolved_at")
    op.drop_column("delivery_records", "lease_expires_at")
    op.drop_column("delivery_records", "reply_id")
