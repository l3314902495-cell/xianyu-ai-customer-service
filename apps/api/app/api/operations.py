from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cursor_pagination import before_cursor, cursor_page, decode_cursor
from app.database import get_db
from app.models import (
    AIReplyLog,
    Conversation,
    ConversationStatus,
    KnowledgeGap,
    Message,
    Notification,
    ProductKnowledge,
    SenderType,
    SystemSetting,
)
from app.realtime import ws_manager
from app.schemas import KnowledgeGapResolve, ReplyRulesUpdate, RuntimeSettingsUpdate, SystemSwitch
from app.security import current_user
from app.services.global_ai_control import global_ai_control
from app.time_utils import utc_iso

router = APIRouter(prefix="/api", tags=["operations"], dependencies=[Depends(current_user)])

DEFAULT_REPLY_RULES = ReplyRulesUpdate().model_dump()
DEFAULT_RUNTIME_SETTINGS = RuntimeSettingsUpdate().model_dump()


async def setting_value(db: AsyncSession, key: str, defaults: dict) -> dict:
    row = await db.get(SystemSetting, key)
    return {**defaults, **(row.value if row else {})}


async def save_setting(db: AsyncSession, key: str, value: dict) -> dict:
    row = await db.get(SystemSetting, key)
    if not row:
        row = SystemSetting(key=key, value={})
        db.add(row)
    row.value = value
    await db.commit()
    return value


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db)) -> dict:
    today = (
        datetime.now(ZoneInfo("Asia/Shanghai"))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )
    conversations = await db.scalar(select(func.count()).select_from(Conversation).where(Conversation.created_at >= today)) or 0
    buyers = await db.scalar(select(func.count()).select_from(Message).where(Message.created_at >= today, Message.sender_type == SenderType.customer)) or 0
    ai_replies = await db.scalar(select(func.count()).select_from(AIReplyLog).where(AIReplyLog.created_at >= today, AIReplyLog.should_send.is_(True))) or 0
    human = await db.scalar(select(func.count()).select_from(Conversation).where(Conversation.created_at >= today, Conversation.human_takeover.is_(True))) or 0
    gaps = await db.scalar(select(func.count()).select_from(KnowledgeGap).where(KnowledgeGap.created_at >= today)) or 0
    high = await db.scalar(select(func.count()).select_from(AIReplyLog).where(AIReplyLog.created_at >= today, AIReplyLog.risk_level == "HIGH")) or 0
    latency = await db.scalar(select(func.avg(AIReplyLog.latency_ms)).where(AIReplyLog.created_at >= today)) or 0
    tokens = await db.scalar(select(func.sum(AIReplyLog.input_tokens + AIReplyLog.output_tokens)).where(AIReplyLog.created_at >= today)) or 0
    cost = await db.scalar(select(func.sum(AIReplyLog.estimated_cost)).where(AIReplyLog.created_at >= today)) or 0
    avg_cost = await db.scalar(
        select(func.avg(AIReplyLog.estimated_cost)).where(AIReplyLog.created_at >= today)
    ) or 0
    return {
        "today_conversations": conversations,
        "today_buyer_messages": buyers,
        "ai_replies": ai_replies,
        "human_takeovers": human,
        "automation_rate": round(ai_replies / buyers * 100, 1) if buyers else 0,
        "knowledge_gaps": gaps,
        "high_risk": high,
        "avg_response_ms": round(float(latency)),
        "today_tokens": tokens,
        "today_cost": float(cost),
        "average_ai_cost": float(avg_cost),
    }


@router.get("/knowledge-gaps")
async def gaps(status: str = "pending", db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.scalars(select(KnowledgeGap).where(KnowledgeGap.status == status).order_by(KnowledgeGap.created_at.desc()))).all()
    return [{"id": r.id, "product_id": r.product_id, "conversation_id": r.conversation_id, "user_message": r.user_message, "missing_knowledge": r.missing_knowledge, "ai_reply": r.ai_reply, "status": r.status, "created_at": utc_iso(r.created_at)} for r in rows]


@router.post("/knowledge-gaps/{gap_id}/save-knowledge")
async def save_gap(gap_id: str, body: KnowledgeGapResolve, db: AsyncSession = Depends(get_db)) -> dict:
    gap = await db.get(KnowledgeGap, gap_id)
    if not gap:
        raise HTTPException(404, "知识缺口不存在")
    if gap.status != "pending":
        raise HTTPException(409, "该知识缺口已经处理，不能重复保存")
    row = ProductKnowledge(
        product_id=gap.product_id,
        title=body.title.strip(),
        content=body.content.strip(),
        category=body.category,
        source="knowledge_gap",
    )
    db.add(row)
    gap.status = "resolved"
    gap.resolved_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True, "knowledge_id": row.id}


@router.post("/knowledge-gaps/{gap_id}/ignore")
async def ignore_gap(gap_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    gap = await db.get(KnowledgeGap, gap_id)
    if not gap:
        raise HTTPException(404, "知识缺口不存在")
    if gap.status != "pending":
        raise HTTPException(409, "该知识缺口已经处理")
    gap.status = "ignored"
    gap.resolved_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True}


@router.get("/logs/messages")
async def message_logs(
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = before_cursor(select(Message), Message.created_at, Message.id, decode_cursor(cursor))
    rows = list((await db.scalars(
        stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
    )).all())
    page = cursor_page(rows, limit, timestamp=lambda row: row.created_at, row_id=lambda row: row.id)
    page["items"] = [{"id": r.id, "conversation_id": r.conversation_id, "sender_type": r.sender_type.value, "content": r.content, "external_message_id": r.external_message_id, "sent": r.sent, "created_at": utc_iso(r.created_at)} for r in page["items"]]
    return page


def ai_log_dict(r: AIReplyLog) -> dict:
    raw_json = r.raw_json or {}
    response_action = raw_json.get("response_action")
    if not response_action:
        response_action = "REPLY" if r.should_send else "ANALYZE_ONLY"
    return {
        "id": r.id,
        "conversation_id": r.conversation_id,
        "product_id": r.product_id,
        "user_message": r.user_message,
        "prompt_version": r.prompt_version,
        "provider": r.provider,
        "model": r.model,
        "intent": r.intent,
        "confidence": r.confidence,
        "risk_level": r.risk_level,
        "risk_flag": r.risk_flag,
        "knowledge_gap": r.knowledge_gap,
        "missing_knowledge": r.missing_knowledge,
        "need_human": r.need_human,
        "should_send": r.should_send,
        "response_action": response_action,
        "silence_reason": raw_json.get("silence_reason"),
        "reply": r.reply,
        "latency_ms": r.latency_ms,
        "input_tokens": r.input_tokens,
        "output_tokens": r.output_tokens,
        "estimated_cost": r.estimated_cost,
        "error": r.error,
        "raw_json": raw_json,
        "created_at": utc_iso(r.created_at),
    }


@router.get("/logs/ai")
async def ai_logs(
    risk_level: str | None = None,
    conversation_id: str | None = None,
    product_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(AIReplyLog)
    if risk_level:
        if risk_level not in {"LOW", "MEDIUM", "HIGH"}:
            raise HTTPException(422, "无效的风险等级")
        stmt = stmt.where(AIReplyLog.risk_level == risk_level)
    if conversation_id:
        stmt = stmt.where(AIReplyLog.conversation_id == conversation_id)
    if product_id:
        stmt = stmt.where(AIReplyLog.product_id == product_id)
    stmt = before_cursor(stmt, AIReplyLog.created_at, AIReplyLog.id, decode_cursor(cursor))
    rows = list((await db.scalars(
        stmt.order_by(AIReplyLog.created_at.desc(), AIReplyLog.id.desc()).limit(limit + 1)
    )).all())
    page = cursor_page(rows, limit, timestamp=lambda row: row.created_at, row_id=lambda row: row.id)
    page["items"] = [ai_log_dict(row) for row in page["items"]]
    return page


@router.get("/logs/risks")
async def risk_logs(
    cursor: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(AIReplyLog)
        .where(
            (AIReplyLog.risk_level != "LOW")
            | AIReplyLog.risk_flag.is_not(None)
            | AIReplyLog.need_human.is_(True)
        )
    )
    stmt = before_cursor(stmt, AIReplyLog.created_at, AIReplyLog.id, decode_cursor(cursor))
    rows = list((await db.scalars(
        stmt.order_by(AIReplyLog.created_at.desc(), AIReplyLog.id.desc()).limit(limit + 1)
    )).all())
    page = cursor_page(rows, limit, timestamp=lambda row: row.created_at, row_id=lambda row: row.id)
    page["items"] = [ai_log_dict(row) for row in page["items"]]
    return page


@router.get("/notifications")
async def notifications(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.scalars(select(Notification).order_by(Notification.created_at.desc()).limit(50))).all()
    return [{"id": r.id, "type": r.type, "title": r.title, "content": r.content, "read": r.read, "created_at": utc_iso(r.created_at)} for r in rows]


@router.post("/notifications/read-all")
async def read_all_notifications(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.scalars(select(Notification).where(Notification.read.is_(False)))).all()
    for row in rows:
        row.read = True
    await db.commit()
    return {"ok": True, "updated": len(rows)}


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(Notification, notification_id)
    if not row:
        raise HTTPException(404, "通知不存在")
    row.read = True
    await db.commit()
    return {"ok": True}


@router.get("/ai/reply-rules")
async def get_reply_rules(db: AsyncSession = Depends(get_db)) -> dict:
    return await setting_value(db, "reply_rules", DEFAULT_REPLY_RULES)


@router.put("/ai/reply-rules")
async def update_reply_rules(body: ReplyRulesUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    value = body.model_dump()
    value["forbidden_reply_phrases"] = sorted(
        {item.strip() for item in body.forbidden_reply_phrases if item.strip()}
    )
    value["silence_custom_phrases"] = sorted(
        {item.strip() for item in body.silence_custom_phrases if item.strip()}
    )
    return await save_setting(db, "reply_rules", value)


@router.get("/system/settings")
async def get_runtime_settings(db: AsyncSession = Depends(get_db)) -> dict:
    return await setting_value(db, "runtime_settings", DEFAULT_RUNTIME_SETTINGS)


@router.put("/system/settings")
async def update_runtime_settings(body: RuntimeSettingsUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    value = body.model_dump()
    value["ignored_message_prefixes"] = sorted(
        {item.strip() for item in body.ignored_message_prefixes if item.strip()}
    )
    return await save_setting(db, "runtime_settings", value)


@router.get("/system/ai-switch")
async def get_switch(db: AsyncSession = Depends(get_db)) -> dict:
    s = await db.get(SystemSetting, "global_ai_enabled"); return {"enabled": True if not s else s.value.get("enabled", True)}


@router.put("/system/ai-switch")
async def set_switch(body: SystemSwitch, db: AsyncSession = Depends(get_db)) -> dict:
    s = await db.get(SystemSetting, "global_ai_enabled")
    if not s: s = SystemSetting(key="global_ai_enabled", value={}); db.add(s)
    s.value = {"enabled": body.enabled}; await db.commit()
    global_ai_control.set_enabled(body.enabled)
    await ws_manager.broadcast("global_ai_switch", {"enabled": body.enabled})
    return s.value


@router.post("/system/emergency-stop")
async def emergency_stop(db: AsyncSession = Depends(get_db)) -> dict:
    s = await db.get(SystemSetting, "global_ai_enabled")
    if not s: s = SystemSetting(key="global_ai_enabled", value={}); db.add(s)
    s.value = {"enabled": False, "emergency": True, "stopped_at": datetime.now(UTC).isoformat()}; db.add(Notification(type="EMERGENCY_STOP", title="AI 自动发送已紧急停止", content="管理员触发全局停止")); await db.commit()
    global_ai_control.stop()
    await ws_manager.broadcast("global_ai_switch", {"enabled": False, "emergency": True})
    return {"ok": True, "enabled": False, "emergency": True}


@router.post("/system/all-human-takeover")
async def all_human_takeover(db: AsyncSession = Depends(get_db)) -> dict:
    """Stop global automation and hand every open conversation to operators."""
    switch = await db.get(SystemSetting, "global_ai_enabled")
    if not switch:
        switch = SystemSetting(key="global_ai_enabled", value={})
        db.add(switch)
    switch.value = {
        "enabled": False,
        "bulk_human_takeover": True,
        "changed_at": datetime.now(UTC).isoformat(),
    }
    conversations = (
        await db.scalars(
            select(Conversation).where(Conversation.status != ConversationStatus.CLOSED)
        )
    ).all()
    for conversation in conversations:
        conversation.human_takeover = True
        conversation.ai_enabled = False
        conversation.status = ConversationStatus.ACTIVE_HUMAN
    db.add(
        Notification(
            type="ALL_HUMAN_TAKEOVER",
            title="全部会话已切换为人工接管",
            content=f"共切换 {len(conversations)} 个未关闭会话，AI 不再分析或回复新消息。",
        )
    )
    await db.commit()
    global_ai_control.stop()
    await ws_manager.broadcast(
        "all_conversations_takeover",
        {"mode": "human", "enabled": False, "updated": len(conversations)},
    )
    await ws_manager.broadcast("global_ai_switch", {"enabled": False})
    return {"ok": True, "mode": "human", "enabled": False, "updated": len(conversations)}


@router.post("/system/all-ai-takeover")
async def all_ai_takeover(db: AsyncSession = Depends(get_db)) -> dict:
    """Enable global automation and resume AI on every open conversation."""
    switch = await db.get(SystemSetting, "global_ai_enabled")
    if not switch:
        switch = SystemSetting(key="global_ai_enabled", value={})
        db.add(switch)
    switch.value = {
        "enabled": True,
        "bulk_human_takeover": False,
        "changed_at": datetime.now(UTC).isoformat(),
    }
    conversations = (
        await db.scalars(
            select(Conversation).where(Conversation.status != ConversationStatus.CLOSED)
        )
    ).all()
    for conversation in conversations:
        conversation.human_takeover = False
        conversation.ai_enabled = True
        conversation.needs_human = False
        conversation.status = ConversationStatus.ACTIVE_AI
    db.add(
        Notification(
            type="ALL_AI_TAKEOVER",
            title="全部会话已恢复 AI 托管",
            content=f"共恢复 {len(conversations)} 个未关闭会话；账号和商品自身的 AI 开关仍然有效。",
        )
    )
    await db.commit()
    global_ai_control.resume()
    await ws_manager.broadcast(
        "all_conversations_takeover",
        {"mode": "ai", "enabled": True, "updated": len(conversations)},
    )
    await ws_manager.broadcast("global_ai_switch", {"enabled": True})
    return {"ok": True, "mode": "ai", "enabled": True, "updated": len(conversations)}
