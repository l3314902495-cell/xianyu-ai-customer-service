"""store application timestamps as timezone-aware UTC

Revision ID: 20260917_09
Revises: 20260917_08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_09"
down_revision: str | None = "20260917_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP_COLUMNS = {
    "users": ("created_at",),
    "xianyu_accounts": ("last_connected_at", "created_at", "updated_at"),
    "xianyu_account_credentials": ("last_verified_at", "created_at", "updated_at"),
    "products": ("created_at", "updated_at"),
    "product_publish_attempts": ("created_at", "updated_at"),
    "product_knowledge": ("created_at", "updated_at"),
    "product_faqs": ("created_at", "updated_at"),
    "conversations": ("created_at", "updated_at"),
    "messages": ("platform_read_at", "created_at"),
    "auto_delivery_configs": ("created_at", "updated_at"),
    "delivery_inventory": ("delivered_at", "created_at"),
    "trade_orders": ("paid_at", "created_at", "updated_at"),
    "delivery_records": (
        "lease_expires_at",
        "delivered_at",
        "resolved_at",
        "created_at",
        "updated_at",
    ),
    "ai_reply_logs": ("created_at",),
    "knowledge_gaps": ("created_at", "resolved_at"),
    "prompt_templates": ("created_at",),
    "system_settings": ("updated_at",),
    "notifications": ("created_at",),
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, columns in TIMESTAMP_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                type_=sa.DateTime(timezone=True),
                postgresql_using=f"{column} AT TIME ZONE 'UTC'",
            )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, columns in reversed(tuple(TIMESTAMP_COLUMNS.items())):
        for column in columns:
            op.alter_column(
                table,
                column,
                type_=sa.DateTime(timezone=False),
                postgresql_using=f"{column} AT TIME ZONE 'UTC'",
            )
