import asyncio
import os
import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.xianyu_bus import (
    EVENT_DEAD_LETTER_STREAM,
    EVENT_GROUP,
    EVENT_RETRY_HASH,
    EVENT_STREAM,
    XianyuEventConsumer,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INFRA_TESTS") != "1",
    reason="requires real PostgreSQL and Redis",
)


@pytest.mark.asyncio
async def test_redis_stream_reclaims_poison_and_keeps_processing_new_events():
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    await redis.delete(EVENT_STREAM, EVENT_DEAD_LETTER_STREAM, EVENT_RETRY_HASH)
    try:
        await redis.xgroup_create(EVENT_STREAM, EVENT_GROUP, id="0", mkstream=True)
        poison_id = await redis.xadd(EVENT_STREAM, {"kind": "poison", "payload": "{}"})
        await redis.xreadgroup(EVENT_GROUP, "dead-consumer", {EVENT_STREAM: ">"}, count=1)
        await asyncio.sleep(0.02)
        healthy_id = await redis.xadd(EVENT_STREAM, {"kind": "healthy", "payload": "{}"})
        handled: list[str] = []

        async def handler(kind: str, _payload: dict) -> None:
            handled.append(kind)
            if kind == "poison":
                raise RuntimeError("permanent integration failure")

        consumer = XianyuEventConsumer(handler, max_attempts=1, claim_idle_ms=1)
        consumer.bus.redis = redis
        await consumer.run_once(block_ms=10)

        assert set(handled) == {"poison", "healthy"}
        pending = await redis.xpending(EVENT_STREAM, EVENT_GROUP)
        assert pending["pending"] == 0
        dead = await redis.xrange(EVENT_DEAD_LETTER_STREAM)
        assert dead and dead[0][1]["original_message_id"] == poison_id
        assert await redis.xrange(EVENT_STREAM, min=healthy_id, max=healthy_id)
    finally:
        await redis.delete(EVENT_STREAM, EVENT_DEAD_LETTER_STREAM, EVENT_RETRY_HASH)
        await redis.aclose()


@pytest.mark.asyncio
async def test_postgres_account_row_lock_serializes_publish_gate():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    account_id = str(uuid.uuid4())
    external_id = f"lock-test-{uuid.uuid4()}"
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO xianyu_accounts "
                "(id, nickname, external_account_id, status, adapter_type, ai_enabled, created_at, updated_at) "
                "VALUES (:id, 'lock-test', :external_id, 'CONNECTED', 'mock', true, now(), now())"
            ),
            {"id": account_id, "external_id": external_id},
        )
    try:
        async with engine.connect() as first, engine.connect() as second:
            first_transaction = await first.begin()
            await first.execute(
                text("SELECT id FROM xianyu_accounts WHERE id = :id FOR UPDATE"),
                {"id": account_id},
            )
            second_transaction = await second.begin()
            await second.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(DBAPIError):
                await second.execute(
                    text("SELECT id FROM xianyu_accounts WHERE id = :id FOR UPDATE"),
                    {"id": account_id},
                )
            await second_transaction.rollback()
            await first_transaction.rollback()
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM xianyu_accounts WHERE id = :id"), {"id": account_id}
            )
        await engine.dispose()
