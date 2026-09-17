import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.xianyu import XianyuAdapter, adapter_for_account
from app.config import get_settings
from app.models import (
    AIProviderConfig,
    AIReplyLog,
    Conversation,
    ConversationStatus,
    KnowledgeGap,
    Message,
    Notification,
    Product,
    PromptTemplate,
    SenderType,
    SystemSetting,
    XianyuAccount,
)
from app.repositories import MessageRepository, ProductKnowledgeRepository
from app.schemas import AIReplyDecision, Intent, ResponseAction, RiskLevel
from app.secrets import decrypt_secret
from app.services.global_ai_control import global_ai_control
from app.services.guard import AutoSendGuard, GuardResult
from app.services.llm import (
    LLMProvider,
    MockLLMProvider,
    OpenAICompatibleProvider,
    ProviderResult,
    StructuredOutputError,
)
from app.services.prompt_builder import GLOBAL_SYSTEM_PROMPT, PromptBuilder
from app.services.response_policy import evaluate_silence
from app.services.safety_rules import enforce_backend_safety


class AIReplyService:
    def __init__(self, db: AsyncSession, adapter: XianyuAdapter | None = None):
        self.db = db
        self.adapter = adapter

    async def _provider(self) -> LLMProvider:
        config = await self.db.scalar(select(AIProviderConfig).where(AIProviderConfig.enabled.is_(True)))
        if not config or config.provider == "mock":
            return MockLLMProvider()
        return OpenAICompatibleProvider(
            config.base_url,
            decrypt_secret(config.api_key_encrypted),
            config.model_name,
            config.temperature,
            config.max_tokens,
            config.timeout,
            provider_name=config.provider,
        )

    async def _global_settings(self, *, fresh: bool = False) -> tuple[bool, str, str]:
        if fresh:
            switch = await self.db.scalar(
                select(SystemSetting)
                .where(SystemSetting.key == "global_ai_enabled")
                .execution_options(populate_existing=True)
            )
        else:
            switch = await self.db.get(SystemSetting, "global_ai_enabled")
        global_enabled = True if not switch else bool(switch.value.get("enabled", True))
        prompt = await self.db.scalar(select(PromptTemplate).where(PromptTemplate.type == "global", PromptTemplate.enabled.is_(True)).order_by(PromptTemplate.created_at.desc()))
        return global_enabled, prompt.content if prompt else GLOBAL_SYSTEM_PROMPT, prompt.version if prompt else "global-v1"

    async def _reply_rules(self) -> dict:
        row = await self.db.get(SystemSetting, "reply_rules")
        return {
            "minimum_confidence": 0.45,
            "shop_rules": "不得承诺退款、赔偿、改价或修改订单。",
            "price_negotiation_reply": "价格这块我帮你留给卖家本人确认哈。",
            "knowledge_gap_reply": "这个具体信息我这边暂时没有记录，我帮你转给卖家确认一下。",
            "forbidden_reply_phrases": [],
            "smart_silence_enabled": True,
            "silence_acknowledgements": True,
            "silence_thanks": True,
            "silence_emoji_only": True,
            "silence_custom_phrases": [],
            "silence_confidence_threshold": 0.85,
            "greeting_cooldown_minutes": 10,
            **(row.value if row else {}),
        }

    async def _history_limit(self) -> int:
        row = await self.db.get(SystemSetting, "runtime_settings")
        return int((row.value if row else {}).get("history_limit", get_settings().history_limit))

    async def _record_follow_up_gap(
        self,
        *,
        conversation: Conversation,
        product: Product,
        user_message: str,
        decision: AIReplyDecision,
    ) -> None:
        """Put knowledge gaps and medium-risk decisions into the operator queue.

        Medium risk is not always a literal lack of product knowledge (for example,
        price negotiation), so the model decision and AI log retain their original
        ``knowledge_gap`` value.  The queue entry explains why operator follow-up is
        required and can still be ignored or promoted to durable product knowledge.
        """
        if not decision.knowledge_gap and decision.risk_level != RiskLevel.MEDIUM:
            return

        existing = await self.db.scalar(
            select(KnowledgeGap).where(
                KnowledgeGap.conversation_id == conversation.id,
                KnowledgeGap.user_message == user_message,
                KnowledgeGap.status == "pending",
            )
        )
        if existing:
            return

        missing_knowledge = decision.missing_knowledge
        if not missing_knowledge:
            intent_label = decision.intent.value.replace("_", " ")
            missing_knowledge = f"中风险事项待人工处理（{intent_label}）：{decision.reason}"

        self.db.add(
            KnowledgeGap(
                product_id=product.id,
                conversation_id=conversation.id,
                user_message=user_message,
                missing_knowledge=missing_knowledge,
                ai_reply=decision.reply,
            )
        )

    async def analyze(self, conversation: Conversation, user_message: str) -> tuple[ProviderResult, dict]:
        product = await self.db.get(Product, conversation.product_id)
        if not product:
            raise RuntimeError("会话商品不存在")
        repo = ProductKnowledgeRepository(self.db)
        knowledge = await repo.enabled_for_product(product.id)
        faqs = await repo.faqs_for_product(product.id)
        history = await MessageRepository(self.db).recent(conversation.id, await self._history_limit())
        _, global_prompt, version = await self._global_settings()
        rules = await self._reply_rules()
        silence_match = evaluate_silence(user_message, history, rules)
        if silence_match:
            decision = AIReplyDecision(
                reply="好的，后续有需要随时问我。",
                should_send=False,
                need_human=False,
                knowledge_gap=False,
                intent=silence_match.intent,
                risk_level=RiskLevel.LOW,
                confidence=0.99,
                reason=silence_match.reason,
                response_action=ResponseAction.SILENT,
                silence_reason=silence_match.reason,
            )
            return ProviderResult(decision, decision.model_dump(mode="json")), {
                "prompt_version": version,
                "provider": "response-policy",
                "model": "deterministic-v1",
                "knowledge": [],
                "faqs": [],
                "product_prompt": product.ai_prompt,
            }
        product_rules = product.details or {}
        shop_rules = "\n".join(
            part
            for part in [
                rules["shop_rules"],
                product_rules.get("special_rules", ""),
                product_rules.get("forbidden_rules", ""),
            ]
            if part
        )
        built = PromptBuilder.build(global_prompt=global_prompt, shop_rules=shop_rules, product=product, knowledge=knowledge, faqs=faqs, history=history, user_message=user_message, version=version)
        provider = await self._provider()
        result = await provider.generate_reply(built)
        return result, {"prompt_version": version, "provider": provider.name, "model": provider.model, "knowledge": built.used_knowledge, "faqs": built.used_faqs, "product_prompt": product.ai_prompt}

    async def process(self, conversation_id: str, user_message: str) -> AIReplyDecision:
        started = time.perf_counter()
        conversation = await self.db.get(Conversation, conversation_id)
        if not conversation:
            raise RuntimeError("会话不存在")
        # A debounced reply job may start after an operator has taken over. Always
        # reload the control state before deciding whether a model call is allowed.
        await self.db.refresh(conversation)
        product = await self.db.get(Product, conversation.product_id)
        account = await self.db.get(XianyuAccount, conversation.account_id)
        assert product and account
        error: str | None = None
        meta = {"prompt_version": "global-v1", "provider": "unknown", "model": "unknown", "knowledge": [], "faqs": [], "product_prompt": product.ai_prompt}
        global_enabled_at_start, _, prompt_version = await self._global_settings(fresh=True)
        manually_paused_at_start = (
            conversation.human_takeover
            or not conversation.ai_enabled
            or conversation.status == ConversationStatus.CLOSED
        )
        stopped_before_analysis = (
            manually_paused_at_start
            or not global_enabled_at_start
            or global_ai_control.stopped
        )
        if stopped_before_analysis:
            stop_reason = (
                "会话已由人工接管，本条买家消息仅保存，不调用模型也不生成回复"
                if manually_paused_at_start
                else "全局 AI 已停止，本条买家消息仅保存，不调用模型也不生成回复"
            )
            decision = AIReplyDecision(
                reply=stop_reason,
                should_send=False,
                need_human=False,
                need_clarification=False,
                knowledge_gap=False,
                missing_knowledge=None,
                intent=Intent.unknown,
                risk_level=RiskLevel.LOW,
                risk_flag=None,
                confidence=1,
                reason=stop_reason,
                response_action=ResponseAction.SILENT,
                silence_reason=stop_reason,
            )
            result = ProviderResult(decision, decision.model_dump(mode="json"))
            meta.update(
                prompt_version=prompt_version,
                provider="manual-control" if manually_paused_at_start else "global-control",
                model="disabled",
            )
        else:
            try:
                result, meta = await self.analyze(conversation, user_message)
            except StructuredOutputError as exc:
                error = str(exc)
                meta["provider"] = exc.provider
                meta["model"] = exc.model
                decision = AIReplyDecision(
                    reply=exc.partial_reply or "我帮你转给卖家确认一下。",
                    should_send=False,
                    need_human=True,
                    knowledge_gap=False,
                    intent=Intent.unknown,
                    risk_level=RiskLevel.HIGH,
                    risk_flag="structured_output_invalid",
                    confidence=0,
                    reason="模型没有返回完整决策字段，后端已禁止自动发送",
                    response_action=ResponseAction.ANALYZE_ONLY,
                    silence_reason="模型结构化输出不完整",
                )
                result = ProviderResult(
                    decision,
                    {"invalid_provider_output": exc.raw_text[:4000]},
                )
                self.db.add(
                    Notification(
                        type="AI_SERVICE_ERROR",
                        title="AI 结构化输出无效",
                        content=error,
                    )
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                decision = AIReplyDecision(reply="我帮你转给卖家确认一下。", should_send=False, need_human=True, knowledge_gap=False, intent=Intent.unknown, risk_level=RiskLevel.HIGH, risk_flag="ai_service_error", confidence=0, reason="AI 服务异常，禁止自动发送", response_action=ResponseAction.ANALYZE_ONLY, silence_reason="AI 服务异常")
                result = ProviderResult(decision, decision.model_dump(mode="json"))
                self.db.add(Notification(type="AI_SERVICE_ERROR", title="AI 服务异常", content=error))
        await self.db.refresh(conversation)
        await self.db.refresh(product)
        await self.db.refresh(account)
        decision = enforce_backend_safety(result.decision, user_message)
        global_enabled_after_analysis, _, _ = await self._global_settings(fresh=True)
        manually_paused_during_processing = (
            conversation.human_takeover
            or not conversation.ai_enabled
            or conversation.status == ConversationStatus.CLOSED
        )
        stopped_during_processing = (
            stopped_before_analysis
            or manually_paused_during_processing
            or not global_enabled_after_analysis
            or global_ai_control.stopped
        )
        reply_rules = await self._reply_rules()
        if stopped_during_processing:
            stop_reason = (
                "会话已由人工接管，本次 AI 结果已丢弃"
                if manually_paused_during_processing
                else "全局 AI 已停止，本次处理保持静默"
            )
            decision.reply = stop_reason
            decision.should_send = False
            decision.need_human = False
            decision.need_clarification = False
            decision.knowledge_gap = False
            decision.missing_knowledge = None
            decision.risk_level = RiskLevel.LOW
            decision.risk_flag = None
            decision.response_action = ResponseAction.SILENT
            decision.silence_reason = stop_reason
            decision.reason = stop_reason
        elif decision.response_action == ResponseAction.SILENT:
            silence_enabled = bool(reply_rules["smart_silence_enabled"])
            silence_threshold = float(reply_rules["silence_confidence_threshold"])
            if not silence_enabled or decision.confidence < silence_threshold:
                decision.response_action = ResponseAction.REPLY
                decision.should_send = True
                decision.silence_reason = None
                decision.reason = f"{decision.reason}；静默置信度不足，按正常回复处理"
            else:
                decision.should_send = False
        elif decision.response_action == ResponseAction.ANALYZE_ONLY:
            decision.should_send = False
        if not stopped_during_processing and decision.intent == Intent.price_negotiation:
            decision.reply = reply_rules["price_negotiation_reply"]
        if not stopped_during_processing:
            if decision.need_human or decision.knowledge_gap or decision.risk_level != RiskLevel.LOW:
                conversation.needs_human = True
                conversation.status = ConversationStatus.NEEDS_HUMAN if not conversation.human_takeover else ConversationStatus.ACTIVE_HUMAN
            elif not conversation.human_takeover:
                # A previous knowledge gap must not keep a later safe answer stuck in
                # "needs human". Explicit human takeover is still only cleared by the operator.
                conversation.needs_human = False
                conversation.status = ConversationStatus.ACTIVE_AI
            conversation.last_intent = decision.intent.value
            conversation.last_confidence = decision.confidence
            conversation.risk_level = decision.risk_level.value
        global_enabled, _, _ = await self._global_settings(fresh=True)
        global_enabled = global_enabled and not global_ai_control.stopped
        guard = AutoSendGuard.check(
            global_enabled=global_enabled,
            account=account,
            product=product,
            conversation=conversation,
            decision=decision,
            minimum_confidence=float(reply_rules["minimum_confidence"]),
            forbidden_reply_phrases=reply_rules["forbidden_reply_phrases"],
        )
        reply_id = f"reply-{uuid.uuid4()}"
        sent = False
        send_result = None
        sender = SenderType.ai
        if guard.allowed:
            enabled_at_send, _, _ = await self._global_settings(fresh=True)
            if not enabled_at_send or global_ai_control.stopped:
                guard = GuardResult(False, "全局 AI 已紧急停止（发送前最终检查）")
                decision.should_send = False
                decision.need_human = False
                decision.need_clarification = False
                decision.knowledge_gap = False
                decision.missing_knowledge = None
                decision.response_action = ResponseAction.SILENT
                decision.silence_reason = guard.reason
        if guard.allowed:
            try:
                adapter = self.adapter or adapter_for_account(account)
                send_result = await adapter.send_message(
                    conversation.external_conversation_id,
                    decision.reply,
                    reply_id,
                    conversation.buyer_id,
                )
                sent = send_result.success
                if not sent:
                    error = send_result.error or "消息发送失败"
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            if not sent:
                conversation.needs_human = True
                conversation.status = ConversationStatus.NEEDS_HUMAN
                self.db.add(
                    Notification(
                        type="XIANYU_SEND_ERROR",
                        title=f"消息发送失败：{account.nickname}",
                        content=error or "Adapter 未返回成功状态",
                    )
                )
        if decision.response_action != ResponseAction.SILENT:
            self.db.add(Message(
                conversation_id=conversation.id,
                external_message_id=(send_result.external_message_id if sent and send_result else None),
                reply_id=reply_id,
                sender_type=sender,
                content=decision.reply,
                sent=sent,
                platform_read_status=(
                    False if sent and account.adapter_type == "experimental-web" else None
                ),
            ))
        await self._record_follow_up_gap(
            conversation=conversation,
            product=product,
            user_message=user_message,
            decision=decision,
        )
        latency = int((time.perf_counter() - started) * 1000)
        self.db.add(AIReplyLog(conversation_id=conversation.id, product_id=product.id, user_message=user_message, prompt_version=meta["prompt_version"], provider=meta["provider"], model=meta["model"], intent=decision.intent.value, confidence=decision.confidence, risk_level=decision.risk_level.value, risk_flag=decision.risk_flag, knowledge_gap=decision.knowledge_gap, missing_knowledge=decision.missing_knowledge, need_human=decision.need_human, should_send=sent, reply=decision.reply, latency_ms=latency, input_tokens=result.input_tokens, output_tokens=result.output_tokens, error=error, raw_json={**result.raw, "response_action": decision.response_action.value, "silence_reason": decision.silence_reason, "guard": guard.reason, "used": meta}))
        await self.db.commit()
        return decision
