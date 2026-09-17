from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Conversation,
    ConversationStatus,
    Message,
    Product,
    ProductKnowledge,
    SenderType,
    XianyuAccount,
)
from app.services.xianyu_protocol import WebSession, XianyuFlowControlled, mtop_call

ITEM_LIST_API = "mtop.idle.web.xyh.item.list"
USER_INFO_API = "mtop.taobao.idlemessage.pc.user.query"


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def text_value(value: Any) -> str:
    """Return human-readable text without stringifying nested message objects."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "content", "title", "message"):
            text = text_value(value.get(key))
            if text:
                return text
    return ""


def _image(value: Any) -> str | None:
    text = str(value or "").strip()
    if text.startswith("//"):
        return f"https:{text}"
    return text or None


def _nested_objects(value: Any, *, max_depth: int = 5) -> list[dict[str, Any]]:
    """Return nested objects from a user-profile response in stable breadth-first order."""
    result: list[dict[str, Any]] = []
    queue: list[tuple[Any, int]] = [(value, 0)]
    seen: set[int] = set()
    while queue:
        current, depth = queue.pop(0)
        if depth > max_depth:
            continue
        if isinstance(current, dict):
            if id(current) in seen:
                continue
            seen.add(id(current))
            result.append(current)
            queue.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            queue.extend((child, depth + 1) for child in current)
    return result


def normalize_peer_name(value: Any) -> str:
    text = str(value or "").strip()
    blocked = (
        "交易消息", "工作台通知", "系统通知", "订单提醒", "等待你发货",
        "买家已拍下", "我已付款", "我",
    )
    if not text or any(word in text for word in blocked):
        return ""
    return text[:120]


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0").replace("¥", "").replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def parse_product_card(card: dict[str, Any]) -> dict[str, Any] | None:
    data = _object(card.get("cardData") or card)
    detail = _object(data.get("detailParams"))
    price_info = _object(data.get("priceInfo"))
    pic_info = _object(data.get("picInfo"))
    item_info = _object(data.get("itemInfo"))
    product_id = str(data.get("id") or detail.get("itemId") or data.get("itemId") or "").strip()
    if not product_id:
        return None
    remote_status = data.get("itemStatus")
    return {
        "external_product_id": product_id,
        "name": str(data.get("title") or detail.get("title") or f"闲鱼商品 {product_id}").strip(),
        "price": _money(price_info.get("price") or data.get("price") or data.get("soldPrice") or detail.get("soldPrice")),
        "image_url": _image(pic_info.get("picUrl") or detail.get("picUrl") or data.get("picUrl")),
        "description": str(
            data.get("desc")
            or data.get("description")
            or detail.get("desc")
            or detail.get("description")
            or item_info.get("desc")
            or ""
        ).strip(),
        "category": str(
            data.get("categoryName")
            or detail.get("categoryName")
            or item_info.get("categoryName")
            or ""
        ).strip(),
        "shipping_origin": str(
            data.get("location")
            or detail.get("location")
            or item_info.get("location")
            or ""
        ).strip(),
        "status": "ACTIVE" if str(remote_status) in {"0", "None", ""} else "DISABLED",
        "remote_status": remote_status,
    }


async def upsert_synced_product_knowledge(
    db: Any,
    product: Product,
    parsed: dict[str, Any],
) -> tuple[int, int]:
    """Persist only facts returned by the seller's product list, never inferred facts."""
    price = parsed["price"]
    facts = [
        ("商品名称", parsed["name"], "other", 30),
        ("当前售价", f"当前展示售价为 ¥{price}", "parameter", 20),
        (
            "商品状态",
            "商品当前在售" if parsed["status"] == "ACTIVE" else "商品当前已下架或不可售",
            "other",
            20,
        ),
    ]
    if parsed.get("description"):
        facts.append(("闲鱼商品描述", parsed["description"], "other", 40))
    if parsed.get("shipping_origin"):
        facts.append(("发货地", parsed["shipping_origin"], "shipping", 25))

    existing = {
        row.title: row
        for row in (
            await db.scalars(
                select(ProductKnowledge).where(
                    ProductKnowledge.product_id == product.id,
                    ProductKnowledge.source == "xianyu_product_sync",
                )
            )
        ).all()
    }
    created = updated = 0
    active_titles: set[str] = set()
    for title, content, category, priority in facts:
        active_titles.add(title)
        row = existing.get(title)
        if row:
            if row.content != str(content) or not row.enabled:
                row.content = str(content)
                row.category = category
                row.priority = priority
                row.enabled = True
                updated += 1
        else:
            db.add(
                ProductKnowledge(
                    product_id=product.id,
                    title=title,
                    content=str(content),
                    category=category,
                    priority=priority,
                    enabled=True,
                    source="xianyu_product_sync",
                )
            )
            created += 1
    for title, row in existing.items():
        if title not in active_titles and row.enabled:
            row.enabled = False
            updated += 1
    return created, updated


async def reconcile_missing_synced_products(
    db: Any,
    account_id: str,
    seen_external_product_ids: set[str],
) -> tuple[int, int]:
    """Mark remotely missing synced products as unavailable without deleting history.

    This must only be called after a complete, successful traversal of the seller
    item list. Calling it for a partial or flow-controlled snapshot could disable
    products that simply were not fetched yet.
    """
    products = (
        await db.scalars(select(Product).where(Product.account_id == account_id))
    ).all()
    disabled = knowledge_updated = 0
    missing_at = datetime.now(UTC).isoformat()
    for product in products:
        details = dict(product.details or {})
        if details.get("source") != "xianyu_sync":
            continue
        if product.external_product_id in seen_external_product_ids:
            continue
        already_missing = bool(details.get("remote_missing"))
        if not already_missing:
            details["ai_enabled_before_remote_missing"] = bool(product.ai_enabled)
            disabled += 1
        details.update(
            {
                "remote_missing": True,
                "remote_missing_since": details.get("remote_missing_since") or missing_at,
            }
        )
        product.details = details
        product.status = "DISABLED"
        product.ai_enabled = False
        if not already_missing:
            _, fact_updated = await upsert_synced_product_knowledge(
                db,
                product,
                {
                    "name": product.name,
                    "price": product.price,
                    "status": "DISABLED",
                    "description": details.get("description", ""),
                    "shipping_origin": details.get("shipping_origin", ""),
                },
            )
            knowledge_updated += fact_updated
    return disabled, knowledge_updated


async def sync_products(account_id: str, session: WebSession, max_pages: int = 10) -> dict[str, int]:
    created = updated = knowledge_created = knowledge_updated = disabled = 0
    seen_external_product_ids: set[str] = set()
    complete_snapshot = False
    async with SessionLocal() as db:
        account = await db.get(XianyuAccount, account_id)
        default_ai_enabled = bool(account and account.ai_enabled)
        for page in range(1, max_pages + 1):
            try:
                raw = await asyncio.to_thread(
                    mtop_call,
                    session,
                    ITEM_LIST_API,
                    {"pageNumber": page, "pageSize": 20, "needGroupInfo": True, "userId": session.unb},
                )
            except XianyuFlowControlled:
                # A single delayed retry is safer than a tight retry loop, which
                # can extend the platform cooldown.
                await asyncio.sleep(8)
                raw = await asyncio.to_thread(
                    mtop_call,
                    session,
                    ITEM_LIST_API,
                    {"pageNumber": page, "pageSize": 20, "needGroupInfo": True, "userId": session.unb},
                )
            data = _object(raw.get("data"))
            cards = data.get("cardList") or []
            if not isinstance(cards, list):
                break
            for raw_card in cards:
                parsed = parse_product_card(_object(raw_card))
                if not parsed:
                    continue
                seen_external_product_ids.add(parsed["external_product_id"])
                product = await db.scalar(
                    select(Product).where(
                        Product.account_id == account_id,
                        Product.external_product_id == parsed["external_product_id"],
                    )
                )
                if product:
                    previous_details = dict(product.details or {})
                    product.name = parsed["name"]
                    product.price = parsed["price"]
                    product.image_url = parsed["image_url"] or product.image_url
                    product.status = parsed["status"]
                    product.category = parsed["category"] or product.category
                    product.details = {
                        **previous_details,
                        "source": "xianyu_sync",
                        "remote_status": parsed["remote_status"],
                        **({"description": parsed["description"]} if parsed["description"] else {}),
                        **({"shipping_origin": parsed["shipping_origin"]} if parsed["shipping_origin"] else {}),
                    }
                    if previous_details.get("remote_missing"):
                        product.details.pop("remote_missing", None)
                        product.details.pop("remote_missing_since", None)
                        product.details.pop("ai_enabled_before_remote_missing", None)
                    updated += 1
                else:
                    product = Product(
                        account_id=account_id,
                        external_product_id=parsed["external_product_id"],
                        name=parsed["name"],
                        category=parsed["category"] or None,
                        price=parsed["price"],
                        image_url=parsed["image_url"],
                        status=parsed["status"],
                        ai_enabled=default_ai_enabled,
                        ai_prompt="",
                        details={
                            "source": "xianyu_sync",
                            "remote_status": parsed["remote_status"],
                            **({"description": parsed["description"]} if parsed["description"] else {}),
                            **({"shipping_origin": parsed["shipping_origin"]} if parsed["shipping_origin"] else {}),
                        },
                    )
                    db.add(product)
                    await db.flush()
                    created += 1
                fact_created, fact_updated = await upsert_synced_product_knowledge(
                    db, product, parsed
                )
                knowledge_created += fact_created
                knowledge_updated += fact_updated
            await db.commit()
            if len(cards) < 20:
                complete_snapshot = True
                break
            await asyncio.sleep(1)
        if complete_snapshot:
            disabled, missing_knowledge_updated = await reconcile_missing_synced_products(
                db, account_id, seen_external_product_ids
            )
            knowledge_updated += missing_knowledge_updated
            await db.commit()
    return {
        "products_created": created,
        "products_updated": updated,
        "products_disabled": disabled,
        "knowledge_created": knowledge_created,
        "knowledge_updated": knowledge_updated,
    }


def fetch_conversation_user_info(session: WebSession, cid: str) -> dict[str, str]:
    """Fetch the other party's public nickname/avatar for a conversation."""
    raw = mtop_call(session, USER_INFO_API, {
        "type": 0,
        "sessionType": 1,
        "sessionId": cid,
        "isOwner": False,
    }, version="4.0")
    data = _object(raw.get("data"))
    best_nickname = ""
    for candidate in _nested_objects(data):
        nickname = normalize_peer_name(
            candidate.get("fishNick")
            or candidate.get("nickname")
            or candidate.get("userNick")
            or candidate.get("nick")
            or candidate.get("displayName")
        )
        avatar = _image(
            candidate.get("logo")
            or candidate.get("avatar")
            or candidate.get("userIcon")
            or candidate.get("avatarUrl")
            or candidate.get("headImg")
            or candidate.get("headUrl")
        )
        if avatar and avatar.startswith("http://"):
            avatar = f"https://{avatar.removeprefix('http://')}"
        if nickname and not best_nickname:
            best_nickname = nickname
        if avatar:
            return {"nickname": nickname or best_nickname, "avatar": avatar}
    return {"nickname": best_nickname, "avatar": ""}


def parse_conversation(item: dict[str, Any], seller_id: str) -> dict[str, Any] | None:
    wrapper = _object(item.get("singleChatUserConversation") or item)
    conversation = _object(wrapper.get("singleChatConversation"))
    cid = str(conversation.get("cid") or wrapper.get("cid") or item.get("cid") or "").removesuffix("@goofish")
    if not cid:
        return None
    first = str(conversation.get("pairFirst") or "").removesuffix("@goofish")
    second = str(conversation.get("pairSecond") or "").removesuffix("@goofish")
    buyer_id = second if first == seller_id else first if second == seller_id else (second or first)
    extension = _object(conversation.get("extension"))
    last_wrapper = _object(wrapper.get("lastMessage"))
    last_message = _object(last_wrapper.get("message") or last_wrapper)
    signature_source = last_message or {
        "redPoint": wrapper.get("redPoint"),
        "modifyTime": wrapper.get("modifyTime") or conversation.get("modifyTime"),
    }
    last_message_signature = hashlib.sha256(
        json.dumps(signature_source, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    last_extension = _object(last_message.get("extension"))
    last_sender_id = str(last_extension.get("senderUserId") or "").removesuffix("@goofish")
    history_peer_name = normalize_peer_name(last_extension.get("reminderTitle"))
    if last_sender_id and last_sender_id != buyer_id:
        history_peer_name = ""
    peer_name = normalize_peer_name(
        extension.get("buyerNick")
        or extension.get("userNick")
        or extension.get("peerUserName")
        or history_peer_name
    )
    peer_avatar = _image(
        extension.get("buyerAvatar")
        or extension.get("userAvatar")
        or extension.get("peerUserAvatar")
        or last_extension.get("senderAvatar")
        or last_extension.get("userAvatar")
    )
    product_id = str(
        extension.get("itemId") or extension.get("itemid") or extension.get("goodsId")
        or extension.get("id") or ""
    ).strip()
    return {
        "cid": cid,
        "buyer_id": buyer_id or f"sid:{cid}",
        "buyer_nickname": peer_name,
        "buyer_avatar": peer_avatar,
        "product_id": product_id,
        "product_name": str(extension.get("itemTitle") or extension.get("goodsTitle") or extension.get("title") or "").strip(),
        "product_image": _image(extension.get("itemPic") or extension.get("itemImage") or extension.get("imageUrl") or extension.get("picUrl")),
        "unread_count": int(wrapper.get("redPoint") or 0),
        "last_message_signature": last_message_signature,
    }


def decode_history_message(model: dict[str, Any], seller_id: str, cid: str) -> dict[str, Any] | None:
    from app.services.xianyu_message_filter import is_platform_message_text

    message = _object(model.get("message") or model)
    content = _object(message.get("content"))
    custom = _object(content.get("custom"))
    decoded: dict[str, Any] = {}
    encoded = custom.get("data")
    if encoded:
        try:
            decoded = _object(base64.b64decode(str(encoded)).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            decoded = {}
    extension = _object(message.get("extension"))
    sender_id = str(extension.get("senderUserId") or decoded.get("sendUserId") or "").removesuffix("@goofish")
    buyer_text = text_value(
        decoded.get("text") or decoded.get("content") or content.get("text")
    )
    reminder_text = text_value(extension.get("reminderContent"))
    text = buyer_text or reminder_text
    if not text:
        return None
    message_id = str(message.get("messageId") or model.get("messageId") or "").strip()
    stamp = message.get("createAt") or message.get("time")
    try:
        numeric = int(stamp)
        # Accept seconds, milliseconds, microseconds and nanoseconds.
        while numeric > 10_000_000_000:
            numeric //= 1000
        created_at = datetime.fromtimestamp(numeric, UTC)
    except (TypeError, ValueError, OSError):
        created_at = datetime.now(UTC)
    return {
        "external_message_id": f"xianyu-history-{message_id}" if message_id else f"xianyu-history-{cid}-{int(created_at.timestamp())}-{hashlib.sha256(text.encode()).hexdigest()[:16]}",
        "sender_type": (
            SenderType.human
            if sender_id == seller_id
            else SenderType.system
            if (not buyer_text and reminder_text)
            or (
                (
                    sender_id.casefold() in {"platform", "system", "xianyu"}
                    or (text.strip().startswith("[") and text.strip().endswith("]"))
                )
                and is_platform_message_text(text)
            )
            else SenderType.customer
        ),
        "sender_name": normalize_peer_name(extension.get("reminderTitle")),
        "content": text,
        "created_at": created_at,
    }


async def persist_conversations(
    account_id: str,
    seller_id: str,
    items: list[dict[str, Any]],
    histories: dict[str, list[dict[str, Any]]],
    profiles: dict[str, dict[str, str]] | None = None,
) -> dict[str, int]:
    conversations_created = messages_created = purchase_conversations_skipped = 0
    profiles = profiles or {}
    async with SessionLocal() as db:
        products = (
            await db.scalars(select(Product).where(Product.account_id == account_id))
        ).all()
        owned_products = {
            product.external_product_id: product
            for product in products
            if not bool((product.details or {}).get("auto_created"))
            and (product.details or {}).get("source") != "xianyu_conversation_sync"
        }
        for raw_item in items:
            parsed = parse_conversation(_object(raw_item), seller_id)
            if not parsed:
                continue
            product = owned_products.get(parsed["product_id"])
            if not product:
                purchase_conversations_skipped += 1
                continue
            profile = profiles.get(parsed["cid"], {})
            peer_name = normalize_peer_name(profile.get("nickname") or parsed["buyer_nickname"])
            peer_avatar = _image(profile.get("avatar") or parsed["buyer_avatar"])
            external_cid = f"web:{account_id}:{parsed['cid']}"
            conversation = await db.scalar(select(Conversation).where(Conversation.external_conversation_id == external_cid))
            if not conversation:
                conversation = Conversation(
                    account_id=account_id, product_id=product.id,
                    external_conversation_id=external_cid,
                    buyer_id=parsed["buyer_id"],
                    buyer_nickname=peer_name or f"闲鱼用户 {parsed['buyer_id'][-4:]}",
                    buyer_avatar=peer_avatar,
                    status=(
                        ConversationStatus.ACTIVE_AI
                        if product.ai_enabled
                        else ConversationStatus.NEEDS_HUMAN
                    ),
                    ai_enabled=product.ai_enabled,
                    needs_human=False,
                    unread_count=parsed["unread_count"],
                )
                db.add(conversation)
                await db.flush()
                conversations_created += 1
            else:
                conversation.unread_count = parsed["unread_count"]
                conversation.buyer_id = parsed["buyer_id"]
                if peer_name:
                    conversation.buyer_nickname = peer_name
                if peer_avatar:
                    conversation.buyer_avatar = peer_avatar
            for model in histories.get(parsed["cid"], []):
                msg = decode_history_message(_object(model), seller_id, parsed["cid"])
                if not msg:
                    continue
                sender_name = msg.pop("sender_name", "")
                if msg["sender_type"] == SenderType.customer and sender_name:
                    conversation.buyer_nickname = sender_name
                if await db.scalar(
                    select(Message.id).where(
                        Message.external_message_id == msg["external_message_id"]
                    )
                ):
                    continue
                # The platform history returns our own sent text with a new remote
                # message id. Link it to the local AI/human row instead of showing
                # the same reply as a second bubble.
                if msg["sender_type"] == SenderType.human:
                    existing_outbound = await db.scalar(
                        select(Message)
                        .where(
                            Message.conversation_id == conversation.id,
                            Message.sender_type.in_([SenderType.ai, SenderType.human]),
                            Message.content == msg["content"],
                            Message.created_at >= msg["created_at"] - timedelta(minutes=2),
                            Message.created_at <= msg["created_at"] + timedelta(minutes=2),
                        )
                        .order_by(Message.created_at.desc())
                    )
                    if existing_outbound:
                        if not existing_outbound.external_message_id:
                            existing_outbound.external_message_id = msg["external_message_id"]
                        continue
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        message_type=(
                            "platform_event"
                            if msg["sender_type"] == SenderType.system
                            else "text"
                        ),
                        sent=True,
                        **msg,
                    )
                )
                messages_created += 1
        await db.commit()
    return {
        "conversations_created": conversations_created,
        "messages_created": messages_created,
        "purchase_conversations_skipped": purchase_conversations_skipped,
    }
