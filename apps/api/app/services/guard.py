from dataclasses import dataclass

from app.models import Conversation, ConversationStatus, Product, XianyuAccount
from app.schemas import AIReplyDecision, ResponseAction, RiskLevel
from app.services.safety_rules import RESTRICTED_HUMAN_INTENTS


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str


class AutoSendGuard:
    @staticmethod
    def check(
        *,
        global_enabled: bool,
        account: XianyuAccount,
        product: Product,
        conversation: Conversation,
        decision: AIReplyDecision,
        minimum_confidence: float = 0.45,
        forbidden_reply_phrases: list[str] | None = None,
    ) -> GuardResult:
        forbidden_reply_phrases = forbidden_reply_phrases or []
        safe_backend_reply = decision.risk_flag in {"restricted_intent", "prompt_injection"}
        blocking_risk_flag = decision.risk_flag in {
            "ai_service_error",
            "structured_output_invalid",
        }
        checks = [
            (
                decision.response_action == ResponseAction.REPLY,
                decision.silence_reason or "回复必要性判断不允许自动发送",
            ),
            (global_enabled, "全局 AI 已停止"),
            (account.ai_enabled and account.status == "CONNECTED", "账号 AI 未启用或离线"),
            (product.ai_enabled and product.status == "ACTIVE", "商品 AI 未启用"),
            (conversation.status != ConversationStatus.CLOSED, "会话已结束"),
            (conversation.ai_enabled and not conversation.human_takeover, "会话已由人工接管"),
            (
                decision.intent not in RESTRICTED_HUMAN_INTENTS
                or decision.risk_flag == "restricted_intent",
                "受限业务回复尚未经过后端安全处理",
            ),
            (decision.should_send, "模型决策不允许发送"),
            (decision.risk_level != RiskLevel.HIGH or safe_backend_reply, "高风险回复未经过安全处理"),
            (not blocking_risk_flag or safe_backend_reply, "存在未处理的严重风险标记"),
            (
                decision.confidence >= minimum_confidence or safe_backend_reply,
                "模型置信度低于自动发送阈值",
            ),
            (
                not any(phrase in decision.reply for phrase in forbidden_reply_phrases),
                "回复命中禁止发送短语",
            ),
        ]
        for passed, reason in checks:
            if not passed:
                return GuardResult(False, reason)
        if decision.need_human or decision.knowledge_gap:
            return GuardResult(True, "允许发送安全回复，同时保留人工跟进标记")
        return GuardResult(True, "所有自动发送规则通过")
