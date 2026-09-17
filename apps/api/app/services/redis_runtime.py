import asyncio
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings

MIN_LOCK_TTL_SECONDS = 180


class RedisRuntime:
    def __init__(self) -> None:
        self.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)

    async def ping(self) -> bool:
        try:
            return bool(await self.redis.ping())
        except RedisError:
            return False

    async def acquire_lock(
        self,
        conversation_id: str,
        ttl: int = MIN_LOCK_TTL_SECONDS,
        wait_timeout: float = 15,
        retry_interval: float = 0.25,
    ) -> str | None:
        token = __import__("uuid").uuid4().hex
        lock_ttl = max(ttl, MIN_LOCK_TTL_SECONDS)
        deadline = asyncio.get_running_loop().time() + max(wait_timeout, 0)
        while True:
            try:
                ok = await self.redis.set(
                    f"ai_reply_lock:{conversation_id}",
                    token,
                    nx=True,
                    ex=lock_ttl,
                )
            except RedisError:
                return None
            if ok:
                return token
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(max(retry_interval, 0))

    async def release_lock(self, conversation_id: str, token: str) -> None:
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        try:
            await self.redis.eval(script, 1, f"ai_reply_lock:{conversation_id}", token)
        except RedisError:
            pass

    async def debounce(
        self,
        conversation_id: str,
        content: str,
        callback: Callable[[str], Awaitable[None]],
        delay_ms: int | None = None,
    ) -> None:
        delay_ms = delay_ms or get_settings().debounce_ms
        key = f"message_debounce:{conversation_id}"
        marker = __import__("uuid").uuid4().hex
        try:
            pipe = self.redis.pipeline()
            pipe.rpush(key, content)
            pipe.expire(key, 10)
            pipe.set(f"{key}:marker", marker, ex=10)
            await pipe.execute()
            await asyncio.sleep(delay_ms / 1000)
            if await self.redis.get(f"{key}:marker") != marker:
                return
            values = await self.redis.lrange(key, 0, -1)
            await self.redis.delete(key, f"{key}:marker")
            await callback("\n".join(values))
        except RedisError:
            await callback(content)


redis_runtime = RedisRuntime()
