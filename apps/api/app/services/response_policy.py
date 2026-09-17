import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models import Message, SenderType
from app.schemas import Intent

ACKNOWLEDGEMENTS = frozenset(
    {"好", "好的", "好嘞", "嗯", "嗯嗯", "行", "可以", "知道了", "明白", "明白了", "收到", "ok", "okay"}
)
THANKS = frozenset({"谢谢", "谢了", "感谢", "多谢", "谢谢你", "麻烦了", "辛苦了"})
GREETINGS = frozenset({"在吗", "有人吗", "你好", "您好", "hello", "hi"})


@dataclass(frozen=True)
class SilenceMatch:
    reason: str
    intent: Intent


def normalize_message(content: str) -> str:
    return re.sub(r"[\s，。！？!?、,.~～]+", "", content).lower()


def emoji_or_punctuation_only(content: str) -> bool:
    compact = "".join(content.split())
    return bool(compact) and len(compact) <= 16 and not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", compact)


def evaluate_silence(
    content: str,
    history: list[Message],
    settings: dict,
    now: datetime | None = None,
) -> SilenceMatch | None:
    if not settings.get("smart_silence_enabled", True):
        return None
    normalized = normalize_message(content)
    if not normalized or "?" in content or "？" in content:
        return None
    custom = {
        normalize_message(value)
        for value in settings.get("silence_custom_phrases", [])
        if value.strip()
    }
    if normalized in custom:
        return SilenceMatch("命中管理员配置的静默短语", Intent.small_talk)
    if settings.get("silence_acknowledgements", True) and normalized in ACKNOWLEDGEMENTS:
        return SilenceMatch("买家只是确认收到，没有提出新问题", Intent.small_talk)
    if settings.get("silence_thanks", True) and normalized in THANKS:
        return SilenceMatch("买家只是致谢，没有提出新问题", Intent.thanks)
    if settings.get("silence_emoji_only", True) and emoji_or_punctuation_only(content):
        return SilenceMatch("消息只包含表情或标点，没有可回答内容", Intent.small_talk)
    if normalized in GREETINGS:
        cutoff = (now or datetime.now(UTC)) - timedelta(
            minutes=int(settings.get("greeting_cooldown_minutes", 10))
        )
        previous = [row for row in history if row.created_at >= cutoff and row.content != content]
        if any(row.sender_type in {SenderType.ai, SenderType.human} for row in previous):
            return SilenceMatch("短时间内已回应过问候，本次不重复打扰", Intent.greeting)
    return None
