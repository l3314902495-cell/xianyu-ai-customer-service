"""cursor pagination indexes

Revision ID: 20260917_08
Revises: 20260917_07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_08"
down_revision: str | None = "20260917_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = (
    ("ix_products_status_updated_id", "products", ["status", "updated_at", "id"]),
    ("ix_products_account_updated_id", "products", ["account_id", "updated_at", "id"]),
    ("ix_conversations_status_updated_id", "conversations", ["status", "updated_at", "id"]),
    ("ix_conversations_attention_updated_id", "conversations", ["needs_human", "updated_at", "id"]),
    ("ix_messages_conversation_created_id", "messages", ["conversation_id", "created_at", "id"]),
    ("ix_ai_logs_created_id", "ai_reply_logs", ["created_at", "id"]),
    ("ix_notifications_created_id", "notifications", ["created_at", "id"]),
    ("ix_delivery_records_created_id", "delivery_records", ["created_at", "id"]),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
