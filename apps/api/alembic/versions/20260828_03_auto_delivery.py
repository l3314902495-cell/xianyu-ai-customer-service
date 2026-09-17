"""product-scoped auto delivery

Revision ID: 20260828_03
Revises: 20260819_02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_03"
down_revision: str | None = "20260819_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auto_delivery_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "product_id", sa.String(36), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("delivery_type", sa.String(20), nullable=False, server_default="card"),
        sa.Column(
            "message_template", sa.Text(), nullable=False, server_default="感谢购买，您的卡密是：{content}"
        ),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("product_id", name="uq_auto_delivery_product"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_auto_delivery_configs_product_id",
        "auto_delivery_configs",
        ["product_id"],
        if_not_exists=True,
    )
    op.create_table(
        "trade_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("xianyu_accounts.id"), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("external_order_id", sa.String(200), nullable=False),
        sa.Column("buyer_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PAID"),
        sa.Column("source", sa.String(30), nullable=False, server_default="mock"),
        sa.Column("raw_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "external_order_id", name="uq_trade_order_account_external"),
        if_not_exists=True,
    )
    for column in ("account_id", "product_id", "conversation_id", "external_order_id"):
        op.create_index(f"ix_trade_orders_{column}", "trade_orders", [column], if_not_exists=True)
    op.create_table(
        "delivery_inventory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "config_id",
            sa.String(36),
            sa.ForeignKey("auto_delivery_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("content_mask", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="AVAILABLE"),
        sa.Column("delivered_order_id", sa.String(36), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )
    for column in ("config_id", "status", "delivered_order_id"):
        op.create_index(f"ix_delivery_inventory_{column}", "delivery_inventory", [column], if_not_exists=True)
    op.create_table(
        "delivery_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "order_id", sa.String(36), sa.ForeignKey("trade_orders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("config_id", sa.String(36), sa.ForeignKey("auto_delivery_configs.id"), nullable=False),
        sa.Column("inventory_id", sa.String(36), sa.ForeignKey("delivery_inventory.id"), nullable=True),
        sa.Column("delivery_type", sa.String(20), nullable=False),
        sa.Column("content_mask", sa.String(255), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("external_message_id", sa.String(200), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("order_id", name="uq_delivery_record_order"),
        if_not_exists=True,
    )
    for column in ("order_id", "config_id", "inventory_id", "status"):
        op.create_index(f"ix_delivery_records_{column}", "delivery_records", [column], if_not_exists=True)


def downgrade() -> None:
    op.drop_table("delivery_records")
    op.drop_table("delivery_inventory")
    op.drop_table("trade_orders")
    op.drop_table("auto_delivery_configs")
