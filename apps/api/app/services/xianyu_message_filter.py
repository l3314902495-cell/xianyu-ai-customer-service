from __future__ import annotations

import re


def normalize_platform_text(content: str) -> str:
    return re.sub(r"[\s\[\]【】～~，,。！!：:]+", "", content).casefold()


def is_platform_message_text(content: str) -> bool:
    """Recognize platform-generated cards/reminders that must never invoke AI.

    Structural protocol classification remains the primary signal. These
    phrases are a final fail-safe for history records where the platform does
    not expose a reliable sender type.
    """

    value = normalize_platform_text(content)
    if not value:
        return False
    exact = {
        "我完成了评价",
        "你完成了评价",
        "对方完成了评价",
        "对方已完成评价",
        "双方已完成评价",
        "快给ta一个评价吧",
        "开通留资卡功能建联更安全",
        "评价后可见",
        "交易已关闭",
        "订单已关闭",
        "订单已取消",
        "交易成功",
        "已付款待发货",
        "我已付款等待你发货",
        "提醒不要直接转账",
    }
    if value in exact:
        return True
    platform_phrase_pairs = (
        ("留资卡", "建联"),
        ("评价", "评价后可见"),
        ("买家已付款", "发货"),
        ("付款成功", "发货"),
        ("拍下宝贝", "付款"),
        ("退款申请", "处理"),
        ("物流", "更新"),
    )
    return any(first in value and second in value for first, second in platform_phrase_pairs)
