import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Conversation,
    ConversationStatus,
    Message,
    Notification,
    SenderType,
    SystemSetting,
)
from app.realtime import ws_manager
from app.schemas import ResponseAction
from app.services.ai_reply import AIReplyService
from app.services.redis_runtime import redis_runtime


class MessageProcessor:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def receive(self, conversation: Conversation, content: str, external_message_id: str | None = None, debounce: bool = True) -> bool:
        content = content.strip()
        if not content:
            return False
        runtime = await self.db.get(SystemSetting, "runtime_settings")
        runtime_value = runtime.value if runtime else {}
        ignored_prefixes = runtime_value.get("ignored_message_prefixes", [])
        if any(content.startswith(prefix) for prefix in ignored_prefixes if prefix):
            return False
        external_id = external_message_id or f"mock-in-{uuid.uuid4()}"
        exists = await self.db.scalar(select(Message.id).where(Message.external_message_id == external_id))
        if exists:
            return False
        self.db.add(Message(conversation_id=conversation.id, external_message_id=external_id, sender_type=SenderType.customer, content=content))
        conversation.unread_count += 1
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            return False
        await ws_manager.broadcast("new_message", {"conversation_id": conversation.id, "content": content, "sender_type": "customer"})

        async def run(merged: str) -> None:
            token = await redis_runtime.acquire_lock(conversation.id)
            if not token:
                current = await self.db.get(Conversation, conversation.id)
                if current:
                    current.needs_human = True
                    current.status = (
                        ConversationStatus.ACTIVE_HUMAN
                        if current.human_takeover
                        else ConversationStatus.NEEDS_HUMAN
                    )
                    self.db.add(
                        Notification(
                            type="AI_REPLY_LOCK_UNAVAILABLE",
                            title="AI 回复已安全转人工",
                            content=f"会话 {current.id} 的回复锁繁忙或 Redis 不可用，系统未自动发送。",
                        )
                    )
                    await self.db.commit()
                    await ws_manager.broadcast(
                        "conversation_status",
                        {
                            "id": current.id,
                            "status": current.status.value,
                            "needs_human": True,
                        },
                    )
                return
            try:
                decision = await AIReplyService(self.db).process(conversation.id, merged)
                if decision.response_action == ResponseAction.SILENT:
                    await ws_manager.broadcast(
                        "ai_silenced",
                        {
                            "conversation_id": conversation.id,
                            "reason": decision.silence_reason,
                        },
                    )
                else:
                    await ws_manager.broadcast("ai_reply", {"conversation_id": conversation.id, "reply": decision.reply, "need_human": decision.need_human, "knowledge_gap": decision.knowledge_gap})
            finally:
                await redis_runtime.release_lock(conversation.id, token)

        if debounce:
            await redis_runtime.debounce(
                conversation.id,
                content,
                run,
                delay_ms=int(runtime_value.get("debounce_ms", get_settings().debounce_ms)),
            )
        else:
            await run(content)
        return True
