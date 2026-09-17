import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.xianyu import adapter_for_account
from app.cursor_pagination import before_cursor, cursor_page, decode_cursor
from app.database import get_db
from app.models import (
    AIProviderConfig,
    Conversation,
    ConversationStatus,
    Message,
    Notification,
    Product,
    ProductKnowledge,
    SenderType,
    XianyuAccount,
)
from app.realtime import ws_manager
from app.schemas import HumanReplyRequest
from app.security import current_user
from app.services.product_scope import seller_product_filter
from app.time_utils import utc_iso

router = APIRouter(prefix="/api/conversations", tags=["conversations"], dependencies=[Depends(current_user)])


async def dismiss_pending_ai_suggestions(db: AsyncSession, conversation_id: str) -> None:
    """Remove stale AI drafts from the operator's active chat timeline."""
    suggestions = await db.scalars(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.sender_type == SenderType.ai,
            Message.sent.is_(False),
        )
    )
    for suggestion in suggestions:
        if suggestion.message_type not in {"ai_suggestion_sent", "ai_suggestion_ignored"}:
            suggestion.message_type = "ai_suggestion_ignored"


def conv_dict(c: Conversation) -> dict:
    return {
        "id": c.id,
        "account_id": c.account_id,
        "product_id": c.product_id,
        "external_conversation_id": c.external_conversation_id,
        "buyer_id": c.buyer_id,
        "buyer_nickname": c.buyer_nickname,
        "buyer_avatar": c.buyer_avatar,
        "status": c.status.value,
        "ai_enabled": c.ai_enabled,
        "human_takeover": c.human_takeover,
        "needs_human": c.needs_human,
        "unread_count": c.unread_count,
        "last_intent": c.last_intent,
        "last_confidence": c.last_confidence,
        "risk_level": c.risk_level,
        "created_at": utc_iso(c.created_at),
        "updated_at": utc_iso(c.updated_at),
    }


@router.get("")
async def list_conversations(
    status: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Conversation, Product).join(Product, Product.id == Conversation.product_id)
    stmt = stmt.where(seller_product_filter())
    if status == "needs_human":
        stmt = stmt.where(Conversation.needs_human.is_(True))
    elif status in {None, "active"}:
        stmt = stmt.where(Conversation.status != ConversationStatus.CLOSED)
    elif status in {item.value for item in ConversationStatus}:
        stmt = stmt.where(Conversation.status == ConversationStatus(status))
    else:
        raise HTTPException(422, "无效的会话状态")
    stmt = before_cursor(stmt, Conversation.updated_at, Conversation.id, decode_cursor(cursor))
    stmt = stmt.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit + 1)
    rows = [
        conv_dict(conversation)
        for conversation, _product in (await db.execute(stmt)).all()
    ]
    return cursor_page(
        rows,
        limit,
        timestamp=lambda item: datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00")),
        row_id=lambda item: item["id"],
    )


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    c = await db.get(Conversation, conversation_id)
    if not c:
        raise HTTPException(404, "会话不存在")
    product = await db.get(Product, c.product_id)
    knowledge_count = await db.scalar(
        select(func.count()).select_from(ProductKnowledge).where(ProductKnowledge.product_id == c.product_id)
    )
    provider = await db.scalar(select(AIProviderConfig).where(AIProviderConfig.enabled.is_(True)))
    return {
        **conv_dict(c),
        "current_model": provider.model_name if provider else "mock-v1",
        "product": {
            "id": product.id,
            "external_product_id": product.external_product_id,
            "name": product.name,
            "price": float(product.price),
            "image_url": product.image_url,
            "ai_enabled": product.ai_enabled,
            "knowledge_count": knowledge_count or 0,
        }
        if product
        else None,
    }


@router.get("/{conversation_id}/messages")
async def messages(
    conversation_id: str,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conversation = await db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "会话不存在")
    account = await db.get(XianyuAccount, conversation.account_id)
    stmt = select(Message).where(Message.conversation_id == conversation_id)
    stmt = before_cursor(stmt, Message.created_at, Message.id, decode_cursor(cursor))
    stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
    queried = list((await db.scalars(stmt)).all())
    has_more = len(queried) > limit
    selected = queried[:limit]
    next_cursor = (
        cursor_page(
            selected + ([queried[limit]] if has_more else []),
            limit,
            timestamp=lambda item: item.created_at,
            row_id=lambda item: item.id,
        )["next_cursor"]
        if selected
        else None
    )
    rows = list(reversed(selected))
    items = [
        {
            "id": m.id,
            "reply_id": m.reply_id,
            "sender_type": m.sender_type.value,
            "content": m.content,
            "message_type": m.message_type,
            "sent": m.sent,
            "platform_read_state": (
                "read"
                if m.platform_read_status is True
                else "unread"
                if m.platform_read_status is False
                else "unknown"
                if account and account.adapter_type == "experimental-web"
                and m.sender_type in {SenderType.ai, SenderType.human} and m.sent
                else "not_applicable"
            ),
            "platform_read_at": utc_iso(m.platform_read_at),
            "created_at": utc_iso(m.created_at),
        }
        for m in rows
    ]
    return {"items": items, "next_cursor": next_cursor}


@router.post("/{conversation_id}/read")
async def mark_read(conversation_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    c = await db.get(Conversation, conversation_id)
    if not c:
        raise HTTPException(404, "会话不存在")
    c.unread_count = 0
    await db.commit()
    await ws_manager.broadcast("conversation_status", conv_dict(c))
    return conv_dict(c)


@router.post("/{conversation_id}/close")
async def close_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    c = await db.get(Conversation, conversation_id)
    if not c:
        raise HTTPException(404, "会话不存在")
    c.ai_enabled = False
    c.human_takeover = False
    c.needs_human = False
    c.status = ConversationStatus.CLOSED
    await db.commit()
    await ws_manager.broadcast("conversation_status", conv_dict(c))
    return conv_dict(c)


@router.post("/{conversation_id}/reopen")
async def reopen_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    c = await db.get(Conversation, conversation_id)
    if not c:
        raise HTTPException(404, "会话不存在")
    c.ai_enabled = True
    c.human_takeover = False
    c.needs_human = False
    c.status = ConversationStatus.ACTIVE_AI
    await db.commit()
    await ws_manager.broadcast("conversation_status", conv_dict(c))
    return conv_dict(c)


@router.post("/{conversation_id}/takeover")
async def takeover(conversation_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    c = await db.get(Conversation, conversation_id)
    if not c:
        raise HTTPException(404, "会话不存在")
    if c.status == ConversationStatus.CLOSED:
        raise HTTPException(409, "会话已关闭，请先重新打开")
    await dismiss_pending_ai_suggestions(db, c.id)
    c.human_takeover = True; c.ai_enabled = False; c.status = ConversationStatus.ACTIVE_HUMAN
    await db.commit(); await ws_manager.broadcast("conversation_status", conv_dict(c)); return conv_dict(c)


@router.post("/{conversation_id}/resume-ai")
async def resume_ai(conversation_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    c = await db.get(Conversation, conversation_id)
    if not c:
        raise HTTPException(404, "会话不存在")
    c.human_takeover = False; c.ai_enabled = True; c.needs_human = False; c.status = ConversationStatus.ACTIVE_AI
    await db.commit(); await ws_manager.broadcast("conversation_status", conv_dict(c)); return conv_dict(c)


@router.post("/{conversation_id}/reply")
async def human_reply(conversation_id: str, body: HumanReplyRequest, db: AsyncSession = Depends(get_db)) -> dict:
    c = await db.get(Conversation, conversation_id)
    if not c:
        raise HTTPException(404, "会话不存在")
    if c.status == ConversationStatus.CLOSED:
        raise HTTPException(409, "会话已关闭，请先重新打开")
    account = await db.get(XianyuAccount, c.account_id)
    if not account:
        raise HTTPException(409, "会话所属账号不存在")
    suggestion = None
    if body.suggestion_id:
        suggestion = await db.scalar(
            select(Message).where(
                Message.id == body.suggestion_id,
                Message.conversation_id == conversation_id,
            )
        )
        if not suggestion:
            raise HTTPException(404, "AI 建议不存在")
        if suggestion.sender_type != SenderType.ai or suggestion.sent:
            raise HTTPException(409, "该消息不是待处理的 AI 建议")
    reply_id = f"human-{uuid.uuid4()}"
    content = body.content.strip()
    if not content:
        raise HTTPException(422, "回复内容不能为空")
    try:
        result = await adapter_for_account(account).send_message(
            c.external_conversation_id,
            content,
            reply_id,
            c.buyer_id,
        )
    except Exception as exc:
        result = None
        error = str(exc)
    else:
        error = result.error or "消息发送失败"
    sent = bool(result and result.success)
    row = Message(
        conversation_id=c.id,
        external_message_id=result.external_message_id if sent and result else None,
        reply_id=reply_id,
        sender_type=SenderType.human,
        content=content,
        sent=sent,
        platform_read_status=(
            False if sent and account.adapter_type == "experimental-web" else None
        ),
    )
    db.add(row)
    await dismiss_pending_ai_suggestions(db, c.id)
    if suggestion:
        suggestion.message_type = "ai_suggestion_sent"
    c.human_takeover = True
    c.ai_enabled = False
    c.status = ConversationStatus.ACTIVE_HUMAN
    if not sent:
        db.add(
            Notification(
                type="XIANYU_SEND_ERROR",
                title=f"人工消息发送失败：{account.nickname}",
                content=error,
            )
        )
    await db.commit()
    await ws_manager.broadcast(
        "human_reply",
        {"conversation_id": c.id, "content": content, "sent": sent},
    )
    if not sent:
        raise HTTPException(502, error)
    return {"ok": True, "id": row.id, "suggestion_id": body.suggestion_id}


@router.post("/{conversation_id}/messages/{message_id}/ignore")
async def ignore_ai_suggestion(
    conversation_id: str,
    message_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.scalar(
        select(Message).where(Message.id == message_id, Message.conversation_id == conversation_id)
    )
    if not row:
        raise HTTPException(404, "消息不存在")
    if row.sender_type != SenderType.ai or row.sent:
        raise HTTPException(409, "只有未发送的 AI 建议可以忽略")
    row.message_type = "ai_suggestion_ignored"
    await db.commit()
    await ws_manager.broadcast(
        "ai_suggestion_ignored", {"conversation_id": conversation_id, "message_id": message_id}
    )
    return {"ok": True}
