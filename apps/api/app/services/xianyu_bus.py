from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from app.config import get_settings

logger = logging.getLogger(__name__)

EVENT_STREAM = "xianyu:events"
EVENT_GROUP = "xianyu-api"
EVENT_DEAD_LETTER_STREAM = "xianyu:events:dead"
EVENT_RETRY_HASH = "xianyu:events:retry"
COMMAND_STREAM = "xianyu:commands"
COMMAND_GROUP = "xianyu-listener"
LISTENER_HEARTBEAT_KEY = "xianyu:listener:last_seen"
ACCOUNT_HEALTH_PREFIX = "xianyu:health:"


def stream_has_messages(entries: list) -> bool:
    """Redis may return [(stream, [])], which must not block reading new entries."""
    return any(messages for _, messages in entries or [])


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class XianyuBus:
    """Durable boundary between the platform listener and the API process."""

    def __init__(self, redis: Redis | None = None) -> None:
        self.redis = redis or Redis.from_url(get_settings().redis_url, decode_responses=True)

    async def ensure_groups(self) -> None:
        for stream, group in (
            (EVENT_STREAM, EVENT_GROUP),
            (COMMAND_STREAM, COMMAND_GROUP),
        ):
            try:
                await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def publish_event(self, kind: str, payload: dict[str, Any]) -> str:
        return str(
            await self.redis.xadd(
                EVENT_STREAM,
                {"kind": kind, "payload": json.dumps(payload, ensure_ascii=False)},
                maxlen=20_000,
                approximate=True,
            )
        )

    async def request(
        self,
        action: str,
        account_id: str,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        request_id = uuid.uuid4().hex
        reply_key = f"xianyu:reply:{request_id}"
        await self.redis.xadd(
            COMMAND_STREAM,
            {
                "request_id": request_id,
                "action": action,
                "account_id": account_id,
                "payload": json.dumps(payload or {}, ensure_ascii=False),
            },
            maxlen=5_000,
            approximate=True,
        )
        wait_seconds = timeout or get_settings().xianyu_command_timeout_seconds
        response = await self.redis.blpop(reply_key, timeout=max(1, int(wait_seconds)))
        if not response:
            raise TimeoutError("闲鱼监听服务响应超时，请稍后重试")
        decoded = json.loads(response[1])
        if not decoded.get("ok"):
            raise RuntimeError(decoded.get("error") or "闲鱼监听服务执行失败")
        return decoded.get("result")

    async def reply(self, request_id: str, *, result: Any = None, error: str | None = None) -> None:
        key = f"xianyu:reply:{request_id}"
        body = json.dumps(
            {"ok": error is None, "result": result, "error": error},
            ensure_ascii=False,
        )
        pipe = self.redis.pipeline()
        pipe.rpush(key, body)
        pipe.expire(key, 60)
        await pipe.execute()

    async def mark_listener_alive(self) -> None:
        await self.redis.set(LISTENER_HEARTBEAT_KEY, utc_now_iso(), ex=45)

    async def listener_alive(self) -> bool:
        try:
            return bool(await self.redis.exists(LISTENER_HEARTBEAT_KEY))
        except RedisError:
            return False

    async def update_account_health(self, account_id: str, **values: Any) -> None:
        mapping = {
            key: json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            for key, value in values.items()
            if value is not None
        }
        mapping["updated_at"] = utc_now_iso()
        key = f"{ACCOUNT_HEALTH_PREFIX}{account_id}"
        pipe = self.redis.pipeline()
        pipe.hset(key, mapping=mapping)
        pipe.expire(key, 24 * 60 * 60)
        await pipe.execute()

    async def account_health(self, account_id: str) -> dict[str, Any]:
        try:
            raw = await self.redis.hgetall(f"{ACCOUNT_HEALTH_PREFIX}{account_id}")
            alive = await self.listener_alive()
        except RedisError:
            return {"listener_alive": False, "connected": False, "state": "redis_unavailable"}
        result: dict[str, Any] = {"listener_alive": alive}
        for key, value in raw.items():
            if value in {"true", "false", "null"} or value[:1] in {"{", "[", '"'}:
                try:
                    result[key] = json.loads(value)
                    continue
                except json.JSONDecodeError:
                    pass
            result[key] = value
        result["connected"] = bool(alive and result.get("connected") is True)
        return result


class XianyuEventConsumer:
    def __init__(
        self,
        handler: Callable[[str, dict[str, Any]], Awaitable[None]],
        *,
        max_attempts: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        claim_idle_ms: int | None = None,
    ) -> None:
        settings = get_settings()
        self.bus = XianyuBus()
        self.handler = handler
        # Stable name lets a restarted API reclaim its own unacknowledged entries.
        self.consumer_name = "api-primary"
        self.max_attempts = max(1, max_attempts or settings.xianyu_event_max_attempts)
        self.retry_base_seconds = max(
            0.0,
            retry_base_seconds
            if retry_base_seconds is not None
            else settings.xianyu_event_retry_base_seconds,
        )
        self.retry_max_seconds = max(
            self.retry_base_seconds,
            retry_max_seconds
            if retry_max_seconds is not None
            else settings.xianyu_event_retry_max_seconds,
        )
        self.claim_idle_ms = max(
            1,
            claim_idle_ms if claim_idle_ms is not None else settings.xianyu_event_claim_idle_ms,
        )

    async def run(self) -> None:
        while True:
            try:
                await self.bus.ensure_groups()
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except RedisError:
                logger.exception("Xianyu event consumer lost Redis; retrying")
                await asyncio.sleep(2)

    async def run_once(self, *, block_ms: int = 5_000) -> None:
        """Process retryable pending work and fresh work without starving either queue."""
        claimed = await self._claim_stale()
        fresh = await self.bus.redis.xreadgroup(
            EVENT_GROUP,
            self.consumer_name,
            {EVENT_STREAM: ">"},
            count=20,
            # When retry work exists, do not wait before checking fresh events.
            block=1 if claimed else block_ms,
        )
        messages: list[tuple[str, dict[str, str]]] = []
        seen: set[str] = set()
        for entries in (claimed, fresh):
            for _, batch in entries or []:
                for message_id, fields in batch:
                    if message_id not in seen:
                        seen.add(message_id)
                        messages.append((message_id, fields))
        if messages:
            # Independent conversations continue even while a poison event is
            # waiting for its next retry window.
            await asyncio.gather(
                *(self._process(message_id, fields) for message_id, fields in messages)
            )

    async def _claim_stale(self) -> list:
        result = await self.bus.redis.xautoclaim(
            EVENT_STREAM,
            EVENT_GROUP,
            self.consumer_name,
            min_idle_time=self.claim_idle_ms,
            start_id="0-0",
            count=20,
        )
        # redis-py returns (next_id, messages[, deleted_ids]). Normalize it to
        # the same wrapper shape as XREADGROUP.
        messages = result[1] if result and len(result) > 1 else []
        return [(EVENT_STREAM, messages)] if messages else []

    async def _process(self, message_id: str, fields: dict[str, str]) -> None:
        retry_state = await self._retry_state(message_id)
        now = time.time()
        if retry_state.get("next_retry_at", 0) > now:
            return
        try:
            await self.handler(
                fields.get("kind", ""),
                json.loads(fields.get("payload") or "{}"),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            attempts = int(retry_state.get("attempts", 0)) + 1
            logger.exception(
                "Xianyu event processing failed id=%s attempt=%s/%s",
                message_id,
                attempts,
                self.max_attempts,
            )
            if attempts >= self.max_attempts:
                await self._park_dead_letter(message_id, fields, attempts, exc)
            else:
                delay = min(
                    self.retry_max_seconds,
                    self.retry_base_seconds * (2 ** (attempts - 1)),
                )
                await self.bus.redis.hset(
                    EVENT_RETRY_HASH,
                    message_id,
                    json.dumps(
                        {
                            "attempts": attempts,
                            "next_retry_at": now + delay,
                            "last_error": str(exc)[:1000],
                        },
                        ensure_ascii=False,
                    ),
                )
            return
        pipe = self.bus.redis.pipeline()
        pipe.xack(EVENT_STREAM, EVENT_GROUP, message_id)
        pipe.hdel(EVENT_RETRY_HASH, message_id)
        await pipe.execute()

    async def _retry_state(self, message_id: str) -> dict[str, Any]:
        raw = await self.bus.redis.hget(EVENT_RETRY_HASH, message_id)
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    async def _park_dead_letter(
        self,
        message_id: str,
        fields: dict[str, str],
        attempts: int,
        exc: Exception,
    ) -> None:
        pipe = self.bus.redis.pipeline()
        pipe.xadd(
            EVENT_DEAD_LETTER_STREAM,
            {
                "original_message_id": message_id,
                "kind": fields.get("kind", ""),
                "payload": fields.get("payload") or "{}",
                "attempts": str(attempts),
                "error": str(exc)[:2000],
                "failed_at": utc_now_iso(),
            },
            maxlen=20_000,
            approximate=True,
        )
        # Parking and acknowledging are issued in one Redis transaction so a
        # poison message is never dropped between the two operations.
        pipe.xack(EVENT_STREAM, EVENT_GROUP, message_id)
        pipe.hdel(EVENT_RETRY_HASH, message_id)
        await pipe.execute()


class XianyuCommandConsumer:
    def __init__(
        self,
        handler: Callable[[str, str, dict[str, Any]], Awaitable[Any]],
    ) -> None:
        self.bus = XianyuBus()
        self.handler = handler
        self.consumer_name = "listener-primary"

    async def run(self) -> None:
        while True:
            try:
                await self.bus.ensure_groups()
                pending = await self.bus.redis.xreadgroup(
                    COMMAND_GROUP,
                    self.consumer_name,
                    {COMMAND_STREAM: "0"},
                    count=10,
                    block=1,
                )
                entries = (
                    pending
                    if stream_has_messages(pending)
                    else await self.bus.redis.xreadgroup(
                        COMMAND_GROUP,
                        self.consumer_name,
                        {COMMAND_STREAM: ">"},
                        count=10,
                        block=5_000,
                    )
                )
                for _, messages in entries:
                    for message_id, fields in messages:
                        request_id = fields.get("request_id", "")
                        try:
                            result = await self.handler(
                                fields.get("action", ""),
                                fields.get("account_id", ""),
                                json.loads(fields.get("payload") or "{}"),
                            )
                            await self.bus.reply(request_id, result=result)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            logger.exception("Xianyu command failed action=%s", fields.get("action"))
                            await self.bus.reply(request_id, error=str(exc))
                        await self.bus.redis.xack(COMMAND_STREAM, COMMAND_GROUP, message_id)
            except asyncio.CancelledError:
                raise
            except RedisError:
                logger.exception("Xianyu command consumer lost Redis; retrying")
                await asyncio.sleep(2)


xianyu_bus = XianyuBus()
