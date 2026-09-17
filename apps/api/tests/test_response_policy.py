from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import AIReplyLog, Message, SenderType
from app.schemas import Intent, ResponseAction
from app.services.ai_reply import AIReplyService
from app.services.response_policy import evaluate_silence


def settings(**overrides):
    return {
        "smart_silence_enabled": True,
        "silence_acknowledgements": True,
        "silence_thanks": True,
        "silence_emoji_only": True,
        "silence_custom_phrases": [],
        "greeting_cooldown_minutes": 10,
        **overrides,
    }


def test_exact_acknowledgement_is_silent_but_question_is_not() -> None:
    match = evaluate_silence("好的", [], settings())
    assert match is not None
    assert match.intent == Intent.small_talk
    assert evaluate_silence("好的，这个支持苹果吗？", [], settings()) is None


def test_thanks_emoji_and_custom_phrase_are_silent() -> None:
    assert evaluate_silence("谢谢！", [], settings()).intent == Intent.thanks
    assert evaluate_silence("👍😊", [], settings()) is not None
    assert evaluate_silence("先这样", [], settings(silence_custom_phrases=["先这样"])) is not None


def test_smart_silence_can_be_disabled() -> None:
    assert evaluate_silence("好的", [], settings(smart_silence_enabled=False)) is None


def test_repeated_greeting_is_silent_after_recent_operator_reply() -> None:
    now = datetime.now(UTC)
    history = [
        Message(
            conversation_id="conversation",
            sender_type=SenderType.ai,
            content="在的，请问想了解什么？",
            created_at=now - timedelta(minutes=2),
        )
    ]
    assert evaluate_silence("在吗", history, settings(), now=now) is not None
    assert evaluate_silence("在吗", [], settings(), now=now) is None


@pytest.mark.asyncio
async def test_silent_decision_creates_log_without_ai_message(db) -> None:
    conversation = db.info["conversation"]
    before = await db.scalar(
        select(func.count()).select_from(Message).where(Message.sender_type == SenderType.ai)
    )

    decision = await AIReplyService(db).process(conversation.id, "好的")

    after = await db.scalar(
        select(func.count()).select_from(Message).where(Message.sender_type == SenderType.ai)
    )
    log = await db.scalar(
        select(AIReplyLog).where(AIReplyLog.conversation_id == conversation.id)
    )
    assert decision.response_action == ResponseAction.SILENT
    assert not decision.should_send
    assert after == before
    assert log is not None
    assert not log.should_send
    assert log.provider == "response-policy"
    assert log.raw_json["response_action"] == "SILENT"
