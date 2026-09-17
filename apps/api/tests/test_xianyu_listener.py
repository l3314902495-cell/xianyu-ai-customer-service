import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Message, SenderType
from app.services import xianyu_control, xianyu_events
from app.services.message_processor import MessageProcessor
from app.services.redis_runtime import redis_runtime
from app.services.xianyu_bus import (
    EVENT_DEAD_LETTER_STREAM,
    EVENT_RETRY_HASH,
    XianyuEventConsumer,
    stream_has_messages,
)
from app.services.xianyu_runtime import (
    XianyuRuntime,
    jittered_poll_delay,
    next_fallback_poll_delay,
)


@pytest.mark.asyncio
async def test_profile_event_updates_missing_avatar_and_broadcasts(db, monkeypatch) -> None:
    conversation = db.info["conversation"]
    account = db.info["account"]
    conversation.external_conversation_id = f"web:{account.id}:remote-cid"
    conversation.buyer_avatar = None
    await db.commit()
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    broadcasts: list[tuple[str, dict]] = []

    async def broadcast(kind: str, payload: dict) -> None:
        broadcasts.append((kind, payload))

    monkeypatch.setattr(xianyu_events, "SessionLocal", maker)
    monkeypatch.setattr(xianyu_events.ws_manager, "broadcast", broadcast)

    await xianyu_events.handle_xianyu_event(
        "conversation_profile",
        {
            "account_id": account.id,
            "cid": "remote-cid",
            "buyer_nickname": "updated-buyer",
            "buyer_avatar": "//example.com/profile.png",
        },
    )

    await db.refresh(conversation)
    assert conversation.buyer_avatar == "https://example.com/profile.png"
    assert conversation.buyer_nickname == "updated-buyer"
    assert broadcasts[-1][0] == "conversation_profile"


@pytest.mark.asyncio
async def test_listener_runtime_publishes_customer_event(monkeypatch) -> None:
    from app.services import xianyu_runtime as runtime_module

    published: list[tuple[str, dict]] = []

    async def publish(kind: str, payload: dict) -> str:
        published.append((kind, payload))
        return "1-0"

    monkeypatch.setattr(
        runtime_module,
        "get_settings",
        lambda: SimpleNamespace(xianyu_runtime_mode="listener"),
    )
    monkeypatch.setattr(runtime_module.xianyu_bus, "publish_event", publish)

    runtime = XianyuRuntime()
    await runtime._receive(
        "account-1",
        {
            "cid": "conversation-1",
            "send_user_id": "buyer-1",
            "send_user_name": "买家",
            "send_message": "还有吗",
        },
        {"messageId": "message-1"},
        "",
        external_message_id="external-1",
    )

    assert published[0][0] == "incoming_customer"
    assert published[0][1]["external_message_id"] == "external-1"
    assert published[0][1]["incoming"]["send_message"] == "还有吗"


@pytest.mark.asyncio
async def test_api_mode_sends_through_listener_command_bus(monkeypatch) -> None:
    requests: list[tuple[str, str, dict]] = []

    async def request(action: str, account_id: str, payload: dict, **_kwargs):
        requests.append((action, account_id, payload))
        return {"external_message_id": "remote-message-1"}

    monkeypatch.setattr(
        xianyu_control,
        "get_settings",
        lambda: SimpleNamespace(xianyu_runtime_mode="api"),
    )
    monkeypatch.setattr(xianyu_control.xianyu_bus, "request", request)

    result = await xianyu_control.send_text(
        "account-1",
        "conversation-1",
        "buyer-1",
        "你好",
    )

    assert result == "remote-message-1"
    assert requests == [
        (
            "send_text",
            "account-1",
            {
                "conversation_id": "conversation-1",
                "recipient_id": "buyer-1",
                "content": "你好",
            },
        )
    ]


@pytest.mark.asyncio
async def test_event_is_acknowledged_only_after_handler_succeeds() -> None:
    order: list[str] = []

    async def handler(kind: str, payload: dict) -> None:
        order.append(f"handled:{kind}:{payload['value']}")

    class FakePipeline:
        def xack(self, *_args):
            order.append("acked")
            return self

        def hdel(self, *_args):
            return self

        async def execute(self):
            return []

    class FakeRedis:
        async def hget(self, *_args):
            return None

        def pipeline(self):
            return FakePipeline()

    consumer = XianyuEventConsumer(handler)
    consumer.bus.redis = FakeRedis()  # type: ignore[assignment]
    await consumer._process("1-0", {"kind": "incoming_customer", "payload": '{"value": 7}'})

    assert order == ["handled:incoming_customer:7", "acked"]


@pytest.mark.asyncio
async def test_poison_event_is_parked_and_does_not_block_fresh_event() -> None:
    handled: list[str] = []

    async def handler(kind: str, _payload: dict) -> None:
        handled.append(kind)
        if kind == "poison":
            raise ValueError("permanent failure")

    class FakePipeline:
        def __init__(self, redis):
            self.redis = redis
            self.commands: list[tuple] = []

        def xadd(self, *args, **kwargs):
            self.commands.append(("xadd", args, kwargs))
            return self

        def xack(self, *args):
            self.commands.append(("xack", args, {}))
            return self

        def hdel(self, *args):
            self.commands.append(("hdel", args, {}))
            return self

        async def execute(self):
            for command, args, kwargs in self.commands:
                if command == "xadd":
                    self.redis.dead_letters.append((args, kwargs))
                elif command == "xack":
                    self.redis.acked.append(args[-1])
                elif command == "hdel":
                    self.redis.retry.pop(args[-1], None)
            return []

    class FakeRedis:
        def __init__(self):
            self.retry = {
                "1-0": json.dumps({"attempts": 1, "next_retry_at": 0})
            }
            self.acked: list[str] = []
            self.dead_letters: list[tuple] = []

        async def xautoclaim(self, *_args, **_kwargs):
            return (
                "0-0",
                [["1-0", {"kind": "poison", "payload": "{}"}]],
                [],
            )

        async def xreadgroup(self, *_args, **_kwargs):
            return [["xianyu:events", [["2-0", {"kind": "healthy", "payload": "{}"}]]]]

        async def hget(self, key, field):
            assert key == EVENT_RETRY_HASH
            return self.retry.get(field)

        def pipeline(self):
            return FakePipeline(self)

    consumer = XianyuEventConsumer(
        handler,
        max_attempts=2,
        retry_base_seconds=0,
        claim_idle_ms=1,
    )
    fake = FakeRedis()
    consumer.bus.redis = fake  # type: ignore[assignment]

    await consumer.run_once(block_ms=1)

    assert handled == ["poison", "healthy"]
    assert set(fake.acked) == {"1-0", "2-0"}
    assert fake.dead_letters[0][0][0] == EVENT_DEAD_LETTER_STREAM


def test_empty_redis_stream_wrapper_is_not_treated_as_pending_message() -> None:
    assert stream_has_messages([["xianyu:events", []]]) is False
    assert stream_has_messages([["xianyu:events", [["1-0", {"kind": "test"}]]]]) is True


def test_fallback_poll_accelerates_only_after_recovery() -> None:
    assert next_fallback_poll_delay(45, recovered=2) == 15
    assert next_fallback_poll_delay(15) == 45
    assert next_fallback_poll_delay(45) == 60
    assert next_fallback_poll_delay(75) == 75


def test_fallback_poll_backs_off_aggressively_on_platform_signals() -> None:
    assert next_fallback_poll_delay(15, failed=True) == 90
    assert next_fallback_poll_delay(90, failed=True) == 180
    assert next_fallback_poll_delay(15, flow_controlled=True) == 180
    assert next_fallback_poll_delay(600, flow_controlled=True) == 900


def test_fallback_poll_jitter_stays_inside_safe_window(monkeypatch) -> None:
    from app.services import xianyu_runtime as runtime_module

    monkeypatch.setattr(runtime_module.random, "uniform", lambda low, high: low)
    assert jittered_poll_delay(20) == 18
    monkeypatch.setattr(runtime_module.random, "uniform", lambda low, high: high)
    assert jittered_poll_delay(20) == pytest.approx(22)


@pytest.mark.asyncio
async def test_buyer_text_is_not_reclassified_as_system_by_keywords(db, monkeypatch) -> None:
    conversation = db.info["conversation"]

    async def hold_debounce(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(redis_runtime, "debounce", hold_debounce)

    accepted = await MessageProcessor(db).receive(
        conversation,
        "买家已经付款了，什么时候发货？",
        "buyer-order-question-1",
        debounce=True,
    )

    row = await db.scalar(
        select(Message).where(Message.external_message_id == "buyer-order-question-1")
    )
    assert accepted is True
    assert row is not None
    assert row.sender_type == SenderType.customer
