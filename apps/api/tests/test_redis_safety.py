import pytest
from redis.exceptions import RedisError
from sqlalchemy import select

from app.models import ConversationStatus, Message, Notification, SenderType
from app.services.message_processor import MessageProcessor
from app.services.redis_runtime import MIN_LOCK_TTL_SECONDS, RedisRuntime, redis_runtime


class SequencedRedis:
    def __init__(self, results: list[bool]) -> None:
        self.results = iter(results)
        self.calls: list[dict] = []

    async def set(self, _key: str, _token: str, **kwargs) -> bool:
        self.calls.append(kwargs)
        return next(self.results)


class UnavailableRedis:
    async def set(self, _key: str, _token: str, **_kwargs) -> bool:
        raise RedisError("unavailable")


@pytest.mark.asyncio
async def test_lock_retries_and_enforces_safe_ttl() -> None:
    runtime = RedisRuntime()
    fake = SequencedRedis([False, False, True])
    runtime.redis = fake  # type: ignore[assignment]

    token = await runtime.acquire_lock(
        "conversation",
        ttl=1,
        wait_timeout=1,
        retry_interval=0,
    )

    assert token
    assert len(fake.calls) == 3
    assert all(call["ex"] >= MIN_LOCK_TTL_SECONDS for call in fake.calls)


@pytest.mark.asyncio
async def test_lock_fails_closed_when_redis_is_unavailable() -> None:
    runtime = RedisRuntime()
    runtime.redis = UnavailableRedis()  # type: ignore[assignment]

    assert await runtime.acquire_lock("conversation") is None


@pytest.mark.asyncio
async def test_unavailable_lock_routes_message_to_human(db, monkeypatch) -> None:
    conversation = db.info["conversation"]

    async def no_lock(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(redis_runtime, "acquire_lock", no_lock)
    accepted = await MessageProcessor(db).receive(
        conversation,
        "锁故障时不能自动发送",
        "lock-failure-message",
        debounce=False,
    )
    await db.refresh(conversation)

    assert accepted
    assert conversation.needs_human
    assert conversation.status == ConversationStatus.NEEDS_HUMAN
    ai_message = await db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.sender_type == SenderType.ai,
        )
    )
    notification = await db.scalar(
        select(Notification).where(Notification.type == "AI_REPLY_LOCK_UNAVAILABLE")
    )
    assert ai_message is None
    assert notification is not None
