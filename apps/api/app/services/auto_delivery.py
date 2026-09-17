from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.xianyu import adapter_for_account
from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    AutoDeliveryConfig,
    Conversation,
    DeliveryInventory,
    DeliveryRecord,
    Message,
    Notification,
    Product,
    SenderType,
    TradeOrder,
    XianyuAccount,
)
from app.realtime import ws_manager
from app.secrets import decrypt_secret

logger = logging.getLogger(__name__)


class DeliveryState(StrEnum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


_DELIVERY_TRANSITIONS = {
    DeliveryState.PENDING: {DeliveryState.SENDING, DeliveryState.FAILED},
    DeliveryState.SENDING: {
        DeliveryState.SENT,
        DeliveryState.FAILED,
        DeliveryState.UNKNOWN,
    },
    DeliveryState.UNKNOWN: {DeliveryState.SENT, DeliveryState.FAILED},
    DeliveryState.SENT: set(),
    DeliveryState.FAILED: set(),
}


def transition_delivery(record: DeliveryRecord, target: DeliveryState) -> None:
    """Apply only a declared delivery transition; terminal states cannot be reopened."""
    current = DeliveryState(record.status)
    if target not in _DELIVERY_TRANSITIONS[current]:
        raise RuntimeError(f"invalid delivery transition: {current} -> {target}")
    record.status = target.value


def utc_now() -> datetime:
    # Models currently store UTC without an offset. The timezone migration is
    # kept separate from the delivery state-machine migration.
    return datetime.now(UTC)


class AutoDeliveryService:
    """Product-scoped fulfillment with a recoverable external-send state machine."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def handle_paid_order(
        self,
        *,
        account_id: str,
        product_id: str,
        external_order_id: str,
        buyer_id: str,
        conversation_id: str | None,
        source: str,
        raw_payload: dict | None = None,
    ) -> dict:
        product = await self.db.get(Product, product_id)
        if not product or product.account_id != account_id:
            return {"status": "product_not_found", "sent": False}
        if product.status != "ACTIVE":
            return {"status": "product_inactive", "sent": False}
        config = await self.db.scalar(
            select(AutoDeliveryConfig).where(AutoDeliveryConfig.product_id == product_id)
        )
        if not config or not config.enabled:
            return {"status": "disabled_for_product", "sent": False}

        existing_order = await self.db.scalar(
            select(TradeOrder).where(
                TradeOrder.account_id == account_id,
                TradeOrder.external_order_id == external_order_id,
            )
        )
        if existing_order:
            existing_record = await self.db.scalar(
                select(DeliveryRecord).where(DeliveryRecord.order_id == existing_order.id)
            )
            if existing_record:
                return {
                    "status": "duplicate",
                    "sent": existing_record.status == "SENT",
                    "record_id": existing_record.id,
                    "delivery_status": existing_record.status,
                }

        conversation = await self._conversation(
            account_id, product_id, buyer_id, conversation_id
        )
        if not conversation:
            return {"status": "conversation_not_found", "sent": False}

        order = existing_order or TradeOrder(
            account_id=account_id,
            product_id=product_id,
            conversation_id=conversation.id,
            external_order_id=external_order_id,
            buyer_id=buyer_id,
            status="PAID",
            source=source,
            raw_payload=raw_payload or {},
            paid_at=utc_now(),
        )
        if not existing_order:
            self.db.add(order)
            await self.db.flush()

        inventory: DeliveryInventory | None = None
        mask = ""
        if config.delivery_type == "card":
            inventory = await self.db.scalar(
                select(DeliveryInventory)
                .where(
                    DeliveryInventory.config_id == config.id,
                    DeliveryInventory.status == "AVAILABLE",
                )
                .order_by(DeliveryInventory.created_at, DeliveryInventory.id)
                .with_for_update(skip_locked=True)
            )
            if not inventory:
                await self._notify(
                    "DELIVERY_STOCK_EMPTY",
                    "自动发货库存不足",
                    f"商品“{product.name}”已付款，但没有可用卡密，未向买家发送。",
                )
                await self.db.commit()
                return {"status": "stock_empty", "sent": False}
            mask = inventory.content_mask
            inventory.status = "RESERVED"
            inventory.delivered_order_id = order.id
        elif config.delivery_type == "image":
            if not config.image_url or not config.image_url.startswith("https://"):
                await self.db.rollback()
                return {"status": "image_not_configured", "sent": False}
            mask = config.image_url
        else:
            await self.db.rollback()
            return {"status": "invalid_delivery_type", "sent": False}

        record_id = str(uuid.uuid4())
        record = DeliveryRecord(
            id=record_id,
            order_id=order.id,
            config_id=config.id,
            inventory_id=inventory.id if inventory else None,
            delivery_type=config.delivery_type,
            content_mask=mask,
            status=DeliveryState.PENDING.value,
            reply_id=f"delivery-{record_id}",
            attempts=0,
        )
        self.db.add(record)
        await self.db.commit()
        return await self.deliver_record(record.id)

    async def deliver_record(self, record_id: str) -> dict:
        """Claim a safe-to-send record, commit SENDING, then perform the side effect."""
        record = await self.db.scalar(
            select(DeliveryRecord)
            .where(DeliveryRecord.id == record_id)
            .with_for_update(skip_locked=True)
        )
        if not record:
            return {"status": "record_not_found", "sent": False}
        if record.status != DeliveryState.PENDING:
            return {
                "status": record.status.lower(),
                "sent": record.status == "SENT",
                "record_id": record.id,
            }

        order = await self.db.get(TradeOrder, record.order_id)
        config = await self.db.get(AutoDeliveryConfig, record.config_id)
        inventory = (
            await self.db.get(DeliveryInventory, record.inventory_id)
            if record.inventory_id
            else None
        )
        if not order or not config:
            return await self._fail(record, inventory, "自动发货上下文不完整")
        conversation = (
            await self.db.get(Conversation, order.conversation_id)
            if order.conversation_id
            else None
        )
        account = await self.db.get(XianyuAccount, order.account_id)
        if not conversation or not account:
            return await self._fail(record, inventory, "闲鱼账号或会话不存在")

        secret = ""
        if record.delivery_type == "card":
            if not inventory or inventory.status != "RESERVED":
                return await self._fail(record, inventory, "预留卡密不存在或状态异常")
            secret = decrypt_secret(inventory.encrypted_content)
            try:
                outbound = config.message_template.format(content=secret)
            except (KeyError, ValueError):
                return await self._fail(record, inventory, "发货模板格式无效")
            audit_content = config.message_template.replace("{content}", inventory.content_mask)
            message_type = "delivery_card"
        elif record.delivery_type == "image" and config.image_url:
            outbound = config.image_url
            audit_content = f"自动发货图片：{config.image_url}"
            message_type = "delivery_image"
        else:
            return await self._fail(record, inventory, "发货配置无效")

        transition_delivery(record, DeliveryState.SENDING)
        record.attempts += 1
        record.lease_expires_at = utc_now() + timedelta(
            seconds=max(10, get_settings().delivery_lease_seconds)
        )
        await self.db.commit()

        try:
            adapter = adapter_for_account(account)
            if record.delivery_type == "card":
                result = await adapter.send_message(
                    conversation.external_conversation_id,
                    outbound,
                    record.reply_id,
                    recipient_id=conversation.buyer_id,
                )
            else:
                result = await adapter.send_image_message(
                    conversation.external_conversation_id,
                    outbound,
                    record.reply_id,
                    recipient_id=conversation.buyer_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return await self._unknown(record, f"发送结果无法确认：{exc}")

        if not result.success:
            error = result.error or "发送失败"
            if result.outcome_unknown:
                return await self._unknown(record, error)
            return await self._fail(record, inventory, error)

        now = utc_now()
        transition_delivery(record, DeliveryState.SENT)
        record.external_message_id = result.external_message_id
        record.delivered_at = now
        record.resolved_at = now
        record.lease_expires_at = None
        record.error = None
        if inventory:
            inventory.status = "DELIVERED"
            inventory.delivered_at = now
        self.db.add(
            Message(
                conversation_id=conversation.id,
                external_message_id=result.external_message_id,
                reply_id=record.reply_id,
                sender_type=SenderType.system,
                content=audit_content,
                message_type=message_type,
                sent=True,
            )
        )
        await self.db.commit()
        await ws_manager.broadcast(
            "delivery.sent", {"record_id": record.id, "product_id": order.product_id}
        )
        return {"status": "sent", "sent": True, "record_id": record.id}

    async def resolve_unknown(
        self,
        record_id: str,
        *,
        sent: bool,
        external_message_id: str | None = None,
    ) -> dict:
        record = await self.db.scalar(
            select(DeliveryRecord)
            .where(DeliveryRecord.id == record_id)
            .with_for_update()
        )
        if not record:
            return {"status": "record_not_found", "resolved": False}
        if record.status != DeliveryState.UNKNOWN:
            return {"status": "not_unknown", "resolved": False, "record_id": record.id}
        inventory = (
            await self.db.get(DeliveryInventory, record.inventory_id)
            if record.inventory_id
            else None
        )
        now = utc_now()
        record.lease_expires_at = None
        record.resolved_at = now
        if sent:
            transition_delivery(record, DeliveryState.SENT)
            record.delivered_at = now
            record.external_message_id = external_message_id or record.external_message_id
            record.error = None
            if inventory:
                inventory.status = "DELIVERED"
                inventory.delivered_at = now
        else:
            transition_delivery(record, DeliveryState.FAILED)
            record.error = "操作员确认平台未发送，库存已释放"
            if inventory:
                inventory.status = "AVAILABLE"
                inventory.delivered_order_id = None
        await self.db.commit()
        await ws_manager.broadcast(
            "delivery.resolved", {"record_id": record.id, "status": record.status}
        )
        return {"status": record.status.lower(), "resolved": True, "record_id": record.id}

    async def _conversation(
        self,
        account_id: str,
        product_id: str,
        buyer_id: str,
        conversation_id: str | None,
    ) -> Conversation | None:
        if conversation_id:
            row = await self.db.scalar(
                select(Conversation).where(
                    Conversation.account_id == account_id,
                    Conversation.product_id == product_id,
                    (
                        (Conversation.id == conversation_id)
                        | (Conversation.external_conversation_id == conversation_id)
                    ),
                )
            )
            if row:
                return row
        return await self.db.scalar(
            select(Conversation)
            .where(
                Conversation.account_id == account_id,
                Conversation.product_id == product_id,
                Conversation.buyer_id == buyer_id,
            )
            .order_by(Conversation.updated_at.desc())
        )

    async def _fail(
        self,
        record: DeliveryRecord,
        inventory: DeliveryInventory | None,
        error: str,
    ) -> dict:
        safe_error = error[:500]
        transition_delivery(record, DeliveryState.FAILED)
        record.error = safe_error
        record.lease_expires_at = None
        record.resolved_at = utc_now()
        if inventory:
            inventory.status = "AVAILABLE"
            inventory.delivered_order_id = None
        await self._notify(
            "DELIVERY_FAILED",
            "自动发货失败",
            f"订单自动发货未成功，库存已释放。原因：{safe_error}",
        )
        await self.db.commit()
        await ws_manager.broadcast("delivery.failed", {"record_id": record.id})
        return {"status": "failed", "sent": False, "record_id": record.id, "error": safe_error}

    async def _unknown(self, record: DeliveryRecord, error: str) -> dict:
        transition_delivery(record, DeliveryState.UNKNOWN)
        record.error = error[:500]
        record.lease_expires_at = None
        await self._notify(
            "DELIVERY_OUTCOME_UNKNOWN",
            "自动发货结果待确认",
            "平台发送结果无法确认，库存仍保持预留。请先在闲鱼核对，再人工标记结果。",
        )
        await self.db.commit()
        await ws_manager.broadcast("delivery.unknown", {"record_id": record.id})
        return {
            "status": "unknown",
            "sent": False,
            "record_id": record.id,
            "error": record.error,
        }

    async def _notify(self, type_: str, title: str, content: str) -> None:
        self.db.add(Notification(type=type_, title=title, content=content))


class AutoDeliveryReconciler:
    """Recovers pre-send records and parks expired in-flight sends as UNKNOWN."""

    async def run(self) -> None:
        interval = max(5, get_settings().delivery_reconcile_interval_seconds)
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Auto-delivery reconciliation failed")
            await asyncio.sleep(interval)

    async def run_once(self) -> None:
        now = utc_now()
        async with SessionLocal() as db:
            expired = (
                await db.scalars(
                    select(DeliveryRecord)
                    .where(
                        DeliveryRecord.status == DeliveryState.SENDING,
                        DeliveryRecord.lease_expires_at.is_not(None),
                        DeliveryRecord.lease_expires_at <= now,
                    )
                    .order_by(DeliveryRecord.lease_expires_at, DeliveryRecord.id)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for record in expired:
                transition_delivery(record, DeliveryState.UNKNOWN)
                record.lease_expires_at = None
                record.error = "发送进程在确认平台结果前中断"
                db.add(
                    Notification(
                        type="DELIVERY_OUTCOME_UNKNOWN",
                        title="自动发货结果待确认",
                        content="发送任务超时中断，库存仍保持预留，请在闲鱼核对后人工处理。",
                    )
                )
            pending_ids = list(
                await db.scalars(
                    select(DeliveryRecord.id)
                    .where(DeliveryRecord.status == DeliveryState.PENDING)
                    .order_by(DeliveryRecord.created_at, DeliveryRecord.id)
                    .limit(20)
                )
            )
            await db.commit()

        for record_id in pending_ids:
            async with SessionLocal() as db:
                with suppress(Exception):
                    await AutoDeliveryService(db).deliver_record(record_id)


auto_delivery_reconciler = AutoDeliveryReconciler()


def make_mock_order_id() -> str:
    return f"mock-order-{uuid.uuid4()}"
