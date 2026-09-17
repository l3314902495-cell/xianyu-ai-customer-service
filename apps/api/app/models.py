import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def uid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ConversationStatus(StrEnum):
    ACTIVE_AI = "ACTIVE_AI"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    ACTIVE_HUMAN = "ACTIVE_HUMAN"
    CLOSED = "CLOSED"


class SenderType(StrEnum):
    customer = "customer"
    ai = "ai"
    human = "human"
    system = "system"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class XianyuAccount(Base):
    __tablename__ = "xianyu_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    nickname: Mapped[str] = mapped_column(String(120))
    external_account_id: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="CONNECTED")
    adapter_type: Mapped[str] = mapped_column(String(30), default="mock")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    products: Mapped[list["Product"]] = relationship(back_populates="account")
    credential: Mapped["XianyuAccountCredential | None"] = relationship(
        back_populates="account", cascade="all, delete-orphan", uselist=False
    )


class XianyuAccountCredential(Base):
    __tablename__ = "xianyu_account_credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("xianyu_accounts.id", ondelete="CASCADE"), unique=True, index=True
    )
    credential_type: Mapped[str] = mapped_column(String(40), default="experimental-web")
    encrypted_payload: Mapped[str] = mapped_column(Text)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    account: Mapped[XianyuAccount] = relationship(back_populates="credential")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("account_id", "external_product_id", name="uq_product_account_external"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    account_id: Mapped[str] = mapped_column(ForeignKey("xianyu_accounts.id"), index=True)
    external_product_id: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_prompt: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    account: Mapped[XianyuAccount] = relationship(back_populates="products")
    knowledge: Mapped[list["ProductKnowledge"]] = relationship(cascade="all, delete-orphan")
    faqs: Mapped[list["ProductFAQ"]] = relationship(cascade="all, delete-orphan")


class ProductPublishAttempt(Base):
    """Audit and idempotency record for an externally visible product publish."""

    __tablename__ = "product_publish_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    account_id: Mapped[str] = mapped_column(ForeignKey("xianyu_accounts.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    request_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    external_product_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ProductKnowledge(Base):
    __tablename__ = "product_knowledge"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), default="other")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ProductFAQ(Base):
    __tablename__ = "product_faqs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    account_id: Mapped[str] = mapped_column(ForeignKey("xianyu_accounts.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    external_conversation_id: Mapped[str] = mapped_column(String(120), unique=True)
    buyer_id: Mapped[str] = mapped_column(String(120))
    buyer_nickname: Mapped[str] = mapped_column(String(120))
    buyer_avatar: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ConversationStatus] = mapped_column(Enum(ConversationStatus), default=ConversationStatus.ACTIVE_AI)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    human_takeover: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_human: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    last_intent: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("external_message_id", name="uq_external_message"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    external_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reply_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    sender_type: Mapped[SenderType] = mapped_column(Enum(SenderType))
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(30), default="text")
    sent: Mapped[bool] = mapped_column(Boolean, default=True)
    platform_read_status: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    platform_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class AutoDeliveryConfig(Base):
    """Per-product delivery policy. Disabled unless explicitly enabled by an admin."""

    __tablename__ = "auto_delivery_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), unique=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_type: Mapped[str] = mapped_column(String(20), default="card")
    message_template: Mapped[str] = mapped_column(
        Text, default="感谢购买，您的卡密是：{content}"
    )
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class DeliveryInventory(Base):
    __tablename__ = "delivery_inventory"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    config_id: Mapped[str] = mapped_column(
        ForeignKey("auto_delivery_configs.id", ondelete="CASCADE"), index=True
    )
    encrypted_content: Mapped[str] = mapped_column(Text)
    content_mask: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE", index=True)
    delivered_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TradeOrder(Base):
    __tablename__ = "trade_orders"
    __table_args__ = (
        UniqueConstraint("account_id", "external_order_id", name="uq_trade_order_account_external"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    account_id: Mapped[str] = mapped_column(ForeignKey("xianyu_accounts.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id"), nullable=True, index=True
    )
    external_order_id: Mapped[str] = mapped_column(String(200), index=True)
    buyer_id: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="PAID")
    source: Mapped[str] = mapped_column(String(30), default="mock")
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class DeliveryRecord(Base):
    __tablename__ = "delivery_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("trade_orders.id", ondelete="CASCADE"), unique=True, index=True
    )
    config_id: Mapped[str] = mapped_column(ForeignKey("auto_delivery_configs.id"), index=True)
    inventory_id: Mapped[str | None] = mapped_column(
        ForeignKey("delivery_inventory.id"), nullable=True, index=True
    )
    delivery_type: Mapped[str] = mapped_column(String(20))
    content_mask: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    reply_id: Mapped[str] = mapped_column(String(160), unique=True)
    external_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AIReplyLog(Base):
    __tablename__ = "ai_reply_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    user_message: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(String(30), default="global-v1")
    provider: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(120))
    intent: Mapped[str] = mapped_column(String(60))
    confidence: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(20))
    risk_flag: Mapped[str | None] = mapped_column(String(120), nullable=True)
    knowledge_gap: Mapped[bool] = mapped_column(Boolean)
    missing_knowledge: Mapped[str | None] = mapped_column(Text, nullable=True)
    need_human: Mapped[bool] = mapped_column(Boolean)
    should_send: Mapped[bool] = mapped_column(Boolean)
    reply: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_message: Mapped[str] = mapped_column(Text)
    missing_knowledge: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_reply: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(50))
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AIProviderConfig(Base):
    __tablename__ = "ai_provider_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(60), default="mock")
    base_url: Mapped[str] = mapped_column(Text, default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(120), default="mock-v1")
    temperature: Mapped[float] = mapped_column(Float, default=0.2)
    max_tokens: Mapped[int] = mapped_column(Integer, default=800)
    timeout: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    type: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
