from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import Conversation, ConversationStatus, Message, Product, SenderType
from app.realtime import ws_manager
from app.services.message_processor import MessageProcessor
from app.services.xianyu_sync import normalize_peer_name

logger = logging.getLogger(__name__)


async def handle_xianyu_event(kind: str, payload: dict[str, Any]) -> None:
    if kind == "incoming_customer":
        await _handle_customer(payload)
    elif kind == "conversation_profile":
        await _handle_conversation_profile(payload)
    elif kind == "human_message":
        await _handle_non_customer(payload, SenderType.human)
    elif kind == "system_message":
        await _handle_non_customer(payload, SenderType.system)
    elif kind == "message_read":
        await _handle_read_receipt(payload)
    elif kind == "outbound_message_echo":
        await _handle_outbound_message_echo(payload)
    else:
        logger.warning("Ignoring unknown Xianyu event kind=%s", kind)


def _platform_message_ids(message_ids: list[str]) -> list[str]:
    result: list[str] = []
    for message_id in message_ids:
        value = str(message_id).strip()
        if value:
            result.extend((value, f"xianyu-history-{value}"))
    return list(dict.fromkeys(result))


def _receipt_time(value: object) -> datetime:
    try:
        numeric = int(str(value))
        while numeric > 10_000_000_000:
            numeric //= 1000
        return datetime.fromtimestamp(numeric, UTC)
    except (TypeError, ValueError, OSError):
        return datetime.now(UTC)


async def _handle_read_receipt(payload: dict[str, Any]) -> None:
    account_id = str(payload.get("account_id") or "")
    cid = str(payload.get("cid") or "")
    message_ids = _platform_message_ids(list(payload.get("message_ids") or []))
    if not account_id or not cid or not message_ids:
        return
    read = bool(payload.get("read"))
    external_cid = f"web:{account_id}:{cid}"

    # A receipt can arrive just before the request that sent the message has
    # committed its local row. Briefly retry so that true platform state is not
    # lost because of that race.
    for attempt in range(5):
        async with SessionLocal() as db:
            conversation = await db.scalar(
                select(Conversation).where(Conversation.external_conversation_id == external_cid)
            )
            if not conversation:
                return
            rows = (
                await db.scalars(
                    select(Message).where(
                        Message.conversation_id == conversation.id,
                        Message.external_message_id.in_(message_ids),
                        Message.sender_type.in_([SenderType.ai, SenderType.human]),
                    )
                )
            ).all()
            if rows:
                read_at = _receipt_time(payload.get("timestamp")) if read else None
                for row in rows:
                    row.platform_read_status = read
                    row.platform_read_at = read_at
                await db.commit()
                await ws_manager.broadcast(
                    "message_read",
                    {
                        "conversation_id": conversation.id,
                        "message_ids": [row.id for row in rows],
                        "read": read,
                        "read_at": read_at.isoformat() if read_at else None,
                    },
                )
                return
        if attempt < 4:
            await asyncio.sleep(0.25)


async def _handle_outbound_message_echo(payload: dict[str, Any]) -> None:
    """Replace the client send UUID with Xianyu's canonical message id.

    Read receipts refer to the server-side ``messageId`` rather than the UUID
    supplied to ``sendByReceiverScope``. Seller echoes contain both identities,
    so retain the canonical id before discarding the echo as a duplicate.
    """
    account_id = str(payload.get("account_id") or "")
    cid = str(payload.get("cid") or "")
    platform_message_id = str(payload.get("platform_message_id") or "").strip()
    client_message_id = str(payload.get("client_message_id") or "").strip()
    content = str(payload.get("content") or "").strip()
    if not account_id or not cid or not platform_message_id:
        return

    external_cid = f"web:{account_id}:{cid}"
    async with SessionLocal() as db:
        conversation = await db.scalar(
            select(Conversation).where(Conversation.external_conversation_id == external_cid)
        )
        if not conversation:
            return

        row = None
        if client_message_id:
            row = await db.scalar(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.external_message_id == client_message_id,
                    Message.sender_type.in_([SenderType.ai, SenderType.human]),
                    Message.sent.is_(True),
                )
            )
        if not row and content:
            cutoff = datetime.now(UTC) - timedelta(minutes=5)
            row = await db.scalar(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.sender_type.in_([SenderType.ai, SenderType.human]),
                    Message.sent.is_(True),
                    Message.content == content,
                    Message.created_at >= cutoff,
                )
                .order_by(Message.created_at.desc())
            )
        if not row:
            return

        row.external_message_id = f"xianyu-history-{platform_message_id}"
        if row.platform_read_status is None:
            row.platform_read_status = False
        await db.commit()


async def _handle_conversation_profile(payload: dict[str, Any]) -> None:
    account_id = str(payload.get("account_id") or "")
    cid = str(payload.get("cid") or "")
    nickname = normalize_peer_name(payload.get("buyer_nickname"))
    avatar = str(payload.get("buyer_avatar") or "").strip()
    if avatar.startswith("//"):
        avatar = f"https:{avatar}"
    if avatar.startswith("http://"):
        avatar = f"https://{avatar.removeprefix('http://')}"
    if avatar and not avatar.startswith("https://"):
        avatar = ""
    if not account_id or not cid or not (nickname or avatar):
        return

    async with SessionLocal() as db:
        conversation = await db.scalar(
            select(Conversation).where(
                Conversation.external_conversation_id == f"web:{account_id}:{cid}"
            )
        )
        if not conversation:
            return
        changed = False
        if nickname and conversation.buyer_nickname != nickname:
            conversation.buyer_nickname = nickname
            changed = True
        if avatar and conversation.buyer_avatar != avatar:
            conversation.buyer_avatar = avatar
            changed = True
        if changed:
            await db.commit()
        await ws_manager.broadcast(
            "conversation_profile",
            {
                "conversation_id": conversation.id,
                "buyer_nickname": conversation.buyer_nickname,
                "buyer_avatar": conversation.buyer_avatar,
            },
        )


async def _handle_customer(payload: dict[str, Any]) -> None:
    account_id = str(payload.get("account_id") or "")
    item_id = str(payload.get("item_id") or "")
    incoming = payload.get("incoming") or {}
    cid = str(incoming.get("cid") or "")
    buyer_id = str(incoming.get("send_user_id") or "")
    content = str(incoming.get("send_message") or "").strip()
    external_message_id = str(payload.get("external_message_id") or "") or None
    if not account_id or not cid or not buyer_id or not content:
        return

    async with SessionLocal() as db:
        product = await db.scalar(
            select(Product).where(
                Product.account_id == account_id,
                Product.external_product_id == item_id,
            )
        )
        if not product:
            logger.info(
                "Skipping unowned Xianyu conversation account=%s item=%s cid=%s",
                account_id,
                item_id,
                cid,
            )
            return
        external_cid = f"web:{account_id}:{cid}"
        conversation = await db.scalar(
            select(Conversation).where(
                Conversation.external_conversation_id == external_cid
            )
        )
        peer_name = normalize_peer_name(incoming.get("send_user_name"))
        peer_avatar = str(incoming.get("send_user_avatar") or "").strip()
        if peer_avatar.startswith("//"):
            peer_avatar = f"https:{peer_avatar}"
        if peer_avatar.startswith("http://"):
            peer_avatar = f"https://{peer_avatar.removeprefix('http://')}"
        if peer_avatar and not peer_avatar.startswith("https://"):
            peer_avatar = ""
        profile_changed = False
        if not conversation:
            conversation = Conversation(
                account_id=account_id,
                product_id=product.id,
                external_conversation_id=external_cid,
                buyer_id=buyer_id,
                buyer_avatar=peer_avatar or None,
                buyer_nickname=peer_name or f"闲鱼用户 {buyer_id[-4:]}",
                status=(
                    ConversationStatus.ACTIVE_AI
                    if product.ai_enabled
                    else ConversationStatus.NEEDS_HUMAN
                ),
                ai_enabled=product.ai_enabled,
                needs_human=not product.ai_enabled,
            )
            db.add(conversation)
            await db.commit()
            await db.refresh(conversation)
            profile_changed = bool(peer_name or peer_avatar)
        else:
            if peer_name and conversation.buyer_nickname != peer_name:
                conversation.buyer_nickname = peer_name
                profile_changed = True
            if peer_avatar and conversation.buyer_avatar != peer_avatar:
                conversation.buyer_avatar = peer_avatar
                profile_changed = True
            if profile_changed:
                await db.commit()

        if profile_changed:
            await ws_manager.broadcast(
                "conversation_profile",
                {
                    "conversation_id": conversation.id,
                    "buyer_nickname": conversation.buyer_nickname,
                    "buyer_avatar": conversation.buyer_avatar,
                },
            )

        await MessageProcessor(db).receive(
            conversation,
            content,
            external_message_id,
            debounce=True,
        )


async def _handle_non_customer(
    payload: dict[str, Any], sender_type: SenderType
) -> None:
    account_id = str(payload.get("account_id") or "")
    cid = str(payload.get("cid") or "")
    external_message_id = str(payload.get("external_message_id") or "")
    content = str(payload.get("content") or "").strip()
    if not account_id or not cid or not external_message_id or not content:
        return
    external_cid = f"web:{account_id}:{cid}"
    async with SessionLocal() as db:
        if await db.scalar(
            select(Message.id).where(Message.external_message_id == external_message_id)
        ):
            return
        conversation = await db.scalar(
            select(Conversation).where(
                Conversation.external_conversation_id == external_cid
            )
        )
        if not conversation:
            return
        db.add(
            Message(
                conversation_id=conversation.id,
                external_message_id=external_message_id,
                sender_type=sender_type,
                content=content,
                message_type=("platform_event" if sender_type == SenderType.system else "text"),
                sent=True,
                created_at=(
                    datetime.fromisoformat(str(payload["created_at"]))
                    if payload.get("created_at")
                    else datetime.now(UTC)
                ),
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return
        await ws_manager.broadcast(
            "new_message",
            {
                "conversation_id": conversation.id,
                "content": content,
                "sender_type": sender_type.value,
            },
        )
