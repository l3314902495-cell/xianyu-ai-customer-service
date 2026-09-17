import re

from app.schemas import AIReplyDecision, Intent, ResponseAction, RiskLevel

RESTRICTED_HUMAN_INTENTS = frozenset(
    {
        Intent.price_negotiation,
        Intent.refund,
        Intent.complaint,
        Intent.order,
        Intent.after_sales,
    }
)

SAFE_ESCALATION_REPLIES = {
    Intent.price_negotiation: "价格这块我先帮你问下卖家本人，确认后马上回复你哈。",
    Intent.refund: "退款情况我先帮你记录并转给卖家确认，具体处理结果稍后回复你哈。",
    Intent.complaint: "收到你的情况了，我先帮你完整记录下来，并通知卖家尽快跟进处理。",
    Intent.order: "订单相关情况我先帮你核实一下，涉及实际修改会由卖家确认后处理。",
    Intent.after_sales: "售后情况我先帮你记录并转给卖家确认，确认清楚后尽快回复你。",
}

_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"忽略.{0,12}(前面|以上|之前|所有).{0,12}(规则|指令|提示|内容)", re.IGNORECASE),
    re.compile(r"(显示|泄露|输出|告诉我|发给我|给我).{0,16}(系统提示词|系统指令|开发者消息)", re.IGNORECASE),
    re.compile(r"(修改|覆盖|绕过).{0,12}(系统规则|安全规则|商品知识|后台权限)", re.IGNORECASE),
    re.compile(r"(扮演|假装).{0,12}(系统|开发者|管理员)", re.IGNORECASE),
    re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)",
        re.IGNORECASE,
    ),
    re.compile(r"(show|reveal|leak|print).{0,24}(system\s+prompt|developer\s+message)", re.IGNORECASE),
)

_RESTRICTED_MESSAGE_TERMS: tuple[tuple[Intent, tuple[str, ...]], ...] = (
    (Intent.refund, ("退款", "退货", "退钱", "申请退")),
    (Intent.complaint, ("投诉", "举报", "欺诈", "骗子", "律师")),
    (Intent.order, ("修改订单", "改地址", "修改地址", "取消订单")),
    (Intent.after_sales, ("赔偿", "售后", "坏了", "无法使用")),
    (
        Intent.price_negotiation,
        ("最低多少", "少点", "便宜点", "能便宜", "刀吗", "包邮吗"),
    ),
)


def restricted_intent_from_message(user_message: str) -> Intent | None:
    normalized = " ".join(user_message.split()).lower()
    for intent, terms in _RESTRICTED_MESSAGE_TERMS:
        if any(term in normalized for term in terms):
            return intent
    return None


def detect_prompt_injection(user_message: str) -> bool:
    """Conservative deterministic screen for common instruction-override attempts."""

    normalized = " ".join(user_message.split())
    return any(pattern.search(normalized) for pattern in _PROMPT_INJECTION_PATTERNS)


def enforce_backend_safety(decision: AIReplyDecision, user_message: str) -> AIReplyDecision:
    """Apply non-model safety policy before the final auto-send guard."""

    if detect_prompt_injection(user_message):
        decision.reply = "这个请求无法处理。商品相关问题我可以继续帮你确认。"
        decision.should_send = True
        decision.response_action = ResponseAction.REPLY
        decision.silence_reason = None
        decision.need_human = False
        decision.risk_level = RiskLevel.HIGH
        decision.risk_flag = "prompt_injection"
        decision.reason = "后端规则检测到提示词注入，发送安全拒绝回复"
        return decision

    restricted_intent = restricted_intent_from_message(user_message)
    if restricted_intent:
        decision.intent = restricted_intent

    if decision.intent in RESTRICTED_HUMAN_INTENTS:
        decision.reply = SAFE_ESCALATION_REPLIES[decision.intent]
        decision.should_send = True
        decision.response_action = ResponseAction.REPLY
        decision.silence_reason = None
        decision.need_human = True
        decision.risk_level = (
            RiskLevel.MEDIUM
            if decision.intent == Intent.price_negotiation
            else RiskLevel.HIGH
        )
        decision.risk_flag = decision.risk_flag or "restricted_intent"
        decision.reason = "先发送安全说明，再由人工完成实际业务处理"
        return decision

    # The backend may downgrade a reply to silence, but must never turn a
    # model/policy SILENT decision back into an automatic send.
    if decision.response_action != ResponseAction.REPLY:
        decision.should_send = False
    return decision
