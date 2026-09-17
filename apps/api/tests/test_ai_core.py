import json

import httpx
import pytest
from sqlalchemy import select

from app.adapters.xianyu import MockXianyuAdapter, RealXianyuAdapter, adapter_for_account
from app.models import AIReplyLog, KnowledgeGap, Message, Product, ProductKnowledge, SenderType, XianyuAccount
from app.repositories import ProductKnowledgeRepository
from app.schemas import AIReplyDecision, Intent, ResponseAction, RiskLevel
from app.services.ai_reply import AIReplyService
from app.services.global_ai_control import global_ai_control
from app.services.guard import AutoSendGuard
from app.services.llm import (
    MockLLMProvider,
    OpenAICompatibleProvider,
    ProviderResult,
    parse_decision,
    recover_partial_decision,
)
from app.services.prompt_builder import GLOBAL_SYSTEM_PROMPT, BuiltPrompt, PromptBuilder


@pytest.mark.asyncio
async def test_product_knowledge_isolation(db):
    a, b = db.info["product_a"], db.info["product_b"]
    db.add_all([ProductKnowledge(product_id=a.id,title="电池",content="电池98%"),ProductKnowledge(product_id=b.id,title="电池",content="电池85%")]); await db.commit()
    rows = await ProductKnowledgeRepository(db).enabled_for_product(a.id)
    text = " ".join(r.content for r in rows)
    assert "98%" in text
    assert "85%" not in text


@pytest.mark.asyncio
async def test_prompt_builder_contains_only_given_product(db):
    a = db.info["product_a"]
    k = ProductKnowledge(product_id=a.id,title="电池",content="电池98%")
    prompt = PromptBuilder.build(global_prompt="全局",shop_rules="规则",product=a,knowledge=[k],faqs=[],history=[],user_message="电池如何")
    assert "电池98%" in prompt.user and "商品A" in prompt.user
    assert "不可信输入" in prompt.user
    assert a.ai_prompt in prompt.system
    assert GLOBAL_SYSTEM_PROMPT in prompt.system
    assert "<global_ai_prompt>" in prompt.system
    assert "体验判断" in prompt.system
    assert "不要因为资料没逐字写" in prompt.system
    assert "按原顺序都回答" in prompt.system
    assert "不要主动岔开" in prompt.system


@pytest.mark.asyncio
async def test_low_risk_experience_inference_does_not_create_gap():
    prompt = BuiltPrompt(
        GLOBAL_SYSTEM_PROMPT,
        "<buyer_message>冬天穿舒服吗</buyer_message>",
        "v2",
        [{"title": "面料", "content": "90%羊毛，10%羊绒", "category": "parameter"}],
        [],
    )
    result = await MockLLMProvider().generate_reply(prompt)
    assert result.decision.should_send
    assert not result.decision.knowledge_gap
    assert not result.decision.need_human
    assert "保暖" in result.decision.reply


def test_ai_json_parse_and_repair():
    payload={"reply":"在的","should_send":True,"need_human":False,"need_clarification":False,"knowledge_gap":False,"missing_knowledge":None,"intent":"inventory","risk_level":"LOW","risk_flag":None,"confidence":.9,"reason":"有库存"}
    assert parse_decision(f"```json\n{json.dumps(payload)}\n```").intent == Intent.inventory
    with pytest.raises(ValueError): parse_decision("not json")


def test_partial_reply_is_recovered_as_non_sending_suggestion():
    decision = recover_partial_decision('{"reply":"主要支持日本和马来西亚，可以把文件发来看看。"}')
    assert not decision.should_send
    assert not decision.need_human
    assert decision.risk_level == RiskLevel.LOW
    assert decision.confidence >= 0.7
    assert decision.response_action == ResponseAction.SILENT


@pytest.mark.asyncio
async def test_provider_retries_partial_json_with_explicit_schema(monkeypatch):
    provider = OpenAICompatibleProvider("https://example.test/v1", "test-key", "test-model", 0.2, 800, 30)
    calls = []
    complete = {
        "reply": "还在的，可以直接拍。",
        "should_send": True,
        "need_human": False,
        "need_clarification": False,
        "knowledge_gap": False,
        "missing_knowledge": None,
        "intent": "inventory",
        "risk_level": "LOW",
        "risk_flag": None,
        "confidence": 0.95,
        "reason": "商品库存信息明确",
    }

    async def fake_request(prompt, repair_output=None, json_mode=True):
        calls.append((repair_output, json_mode))
        if len(calls) == 1:
            message = {"content": '{"reply":"这个库存我帮你确认一下。"}'}
        else:
            message = {
                "content": None,
                "tool_calls": [
                    {
                        "function": {
                            "name": "submit_customer_service_decision",
                            "arguments": json.dumps(complete, ensure_ascii=False),
                        }
                    }
                ],
            }
        return {"choices": [{"message": message}], "usage": {}}

    monkeypatch.setattr(provider, "_request", fake_request)
    prompt = BuiltPrompt("system", "user", "v1", [], [])
    result = await provider.generate_reply(prompt)

    assert result.decision.intent == Intent.inventory
    assert calls[0] == (None, True)
    assert calls[1][0] == '{"reply":"这个库存我帮你确认一下。"}'
    assert calls[1][1] is False


@pytest.mark.asyncio
async def test_provider_keeps_partial_reply_but_does_not_auto_send(monkeypatch):
    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "test-key", "test-model", 0.2, 800, 30
    )

    async def fake_request(prompt, repair_output=None, json_mode=True):
        return {
            "choices": [{"message": {"content": '{"reply":"可以，把文件发来看看。"}'}}],
            "usage": {},
        }

    monkeypatch.setattr(provider, "_request", fake_request)
    result = await provider.generate_reply(BuiltPrompt("system", "user", "v1", [], []))
    assert not result.decision.should_send
    assert result.decision.response_action == ResponseAction.SILENT
    assert result.raw["structured_output_recovered"] is True


@pytest.mark.asyncio
async def test_provider_does_not_retry_network_timeout(monkeypatch):
    provider = OpenAICompatibleProvider(
        "https://example.test/v1", "test-key", "test-model", 0.2, 300, 2
    )
    calls = 0

    async def timeout_request(prompt, repair_output=None, json_mode=True):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("upstream timeout")

    monkeypatch.setattr(provider, "_request", timeout_request)
    with pytest.raises(RuntimeError, match="模型请求超时"):
        await provider.generate_reply(BuiltPrompt("system", "user", "v1", [], []))
    assert calls == 1


def test_auto_send_guard_and_takeover(db):
    c,p,a=db.info["conversation"],db.info["product_a"],db.info["account"]
    decision=AIReplyDecision(reply="在的",should_send=True,need_human=False,knowledge_gap=False,intent=Intent.inventory,risk_level=RiskLevel.LOW,confidence=.9,reason="ok")
    assert AutoSendGuard.check(global_enabled=True,account=a,product=p,conversation=c,decision=decision).allowed
    c.human_takeover=True
    assert not AutoSendGuard.check(global_enabled=True,account=a,product=p,conversation=c,decision=decision).allowed
    c.human_takeover=False
    decision.risk_level=RiskLevel.HIGH
    assert not AutoSendGuard.check(global_enabled=True,account=a,product=p,conversation=c,decision=decision).allowed


@pytest.mark.asyncio
async def test_knowledge_gap_creates_record_and_needs_human(db):
    c=db.info["conversation"]
    decision=await AIReplyService(db).process(c.id,"是不是 IPX7 防水？")
    await db.refresh(c)
    assert decision.knowledge_gap and c.needs_human
    assert await db.scalar(select(KnowledgeGap).where(KnowledgeGap.conversation_id==c.id))


@pytest.mark.asyncio
async def test_takeover_during_analysis_discards_generated_reply(db, monkeypatch):
    c = db.info["conversation"]
    decision = AIReplyDecision(
        reply="这条生成结果不应出现在聊天中",
        should_send=True,
        need_human=False,
        knowledge_gap=False,
        intent=Intent.inventory,
        risk_level=RiskLevel.LOW,
        confidence=0.99,
        reason="测试并发接管",
    )

    async def analyze(_conversation, _user_message):
        c.human_takeover = True
        c.ai_enabled = False
        await db.commit()
        return ProviderResult(decision, decision.model_dump(mode="json")), {
            "prompt_version": "test-v1",
            "provider": "mock",
            "model": "mock-v1",
            "knowledge": [],
            "faqs": [],
            "product_prompt": "",
        }

    service = AIReplyService(db)
    monkeypatch.setattr(service, "analyze", analyze)
    result = await service.process(c.id, "还有吗？")

    assert result.response_action == ResponseAction.SILENT
    ai_messages = (
        await db.scalars(
            select(Message).where(
                Message.conversation_id == c.id,
                Message.sender_type == SenderType.ai,
            )
        )
    ).all()
    assert ai_messages == []


@pytest.mark.asyncio
async def test_medium_risk_is_added_to_knowledge_gap_queue_without_changing_decision(db, monkeypatch):
    c = db.info["conversation"]
    decision = AIReplyDecision(
        reply="价格需要卖家确认。",
        should_send=True,
        need_human=True,
        knowledge_gap=False,
        intent=Intent.price_negotiation,
        risk_level=RiskLevel.MEDIUM,
        risk_flag="restricted_intent",
        confidence=0.99,
        reason="议价由卖家处理",
    )

    async def analyze(_conversation, _user_message):
        return ProviderResult(decision, decision.model_dump(mode="json")), {
            "prompt_version": "test-v1",
            "provider": "mock",
            "model": "mock-v1",
            "knowledge": [],
            "faqs": [],
            "product_prompt": "",
        }

    service = AIReplyService(db)
    monkeypatch.setattr(service, "analyze", analyze)
    result = await service.process(c.id, "300 可以吗？")

    gaps = (
        await db.scalars(
            select(KnowledgeGap).where(
                KnowledgeGap.conversation_id == c.id,
                KnowledgeGap.user_message == "300 可以吗？",
            )
        )
    ).all()
    assert result.risk_level == RiskLevel.MEDIUM
    assert not result.knowledge_gap
    assert len(gaps) == 1
    assert "中风险事项待人工处理" in (gaps[0].missing_knowledge or "")

    await service.process(c.id, "300 可以吗？")
    duplicate_check = (
        await db.scalars(
            select(KnowledgeGap).where(
                KnowledgeGap.conversation_id == c.id,
                KnowledgeGap.user_message == "300 可以吗？",
                KnowledgeGap.status == "pending",
            )
        )
    ).all()
    assert len(duplicate_check) == 1


@pytest.mark.asyncio
async def test_known_answer_auto_sends(db):
    c,p=db.info["conversation"],db.info["product_a"]
    db.add(ProductKnowledge(product_id=p.id,title="电池",content="电池98%"));await db.commit()
    decision=await AIReplyService(db).process(c.id,"电池情况？")
    message=await db.scalar(select(Message).where(Message.conversation_id==c.id,Message.sender_type==SenderType.ai))
    assert not decision.need_human and "98%" in decision.reply
    assert message and message.sent


@pytest.mark.asyncio
async def test_emergency_barrier_prevents_adapter_send_even_for_safe_reply(db, monkeypatch):
    conversation = db.info["conversation"]
    product = db.info["product_a"]
    account = db.info["account"]
    db.add(ProductKnowledge(product_id=product.id, title="电池", content="电池98%"))
    await db.commit()
    adapter = MockXianyuAdapter(account)

    async def forbidden_send(*_args, **_kwargs):
        raise AssertionError("紧急停止后不应调用 Adapter")

    service = AIReplyService(db, adapter=adapter)

    async def forbidden_analyze(*_args, **_kwargs):
        raise AssertionError("紧急停止后不应调用大模型")

    monkeypatch.setattr(adapter, "send_message", forbidden_send)
    monkeypatch.setattr(service, "analyze", forbidden_analyze)
    global_ai_control.stop()
    try:
        decision = await service.process(conversation.id, "电池情况？")
    finally:
        global_ai_control.resume()

    message = await db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.sender_type == SenderType.ai,
        )
    )
    log = await db.scalar(
        select(AIReplyLog).where(AIReplyLog.conversation_id == conversation.id)
    )
    assert not decision.should_send
    assert decision.response_action == ResponseAction.SILENT
    assert message is None
    assert log is not None
    assert log.provider == "global-control"
    assert log.input_tokens == 0
    assert log.output_tokens == 0


@pytest.mark.asyncio
async def test_emergency_stop_discards_an_in_flight_reply(db, monkeypatch):
    conversation = db.info["conversation"]
    account = db.info["account"]
    adapter = MockXianyuAdapter(account)
    service = AIReplyService(db, adapter=adapter)

    async def analyze_then_stop(*_args, **_kwargs):
        global_ai_control.stop()
        decision = AIReplyDecision(
            reply="这条内容不应发送或显示",
            should_send=True,
            need_human=False,
            knowledge_gap=False,
            intent=Intent.product_information,
            risk_level=RiskLevel.LOW,
            confidence=0.99,
            reason="测试处理中停止",
            response_action=ResponseAction.REPLY,
        )
        return ProviderResult(decision, decision.model_dump(mode="json")), {
            "prompt_version": "test-v1",
            "provider": "test",
            "model": "test-model",
            "knowledge": [],
            "faqs": [],
            "product_prompt": "",
        }

    async def forbidden_send(*_args, **_kwargs):
        raise AssertionError("处理中紧急停止后不应调用 Adapter")

    monkeypatch.setattr(service, "analyze", analyze_then_stop)
    monkeypatch.setattr(adapter, "send_message", forbidden_send)
    global_ai_control.resume()
    try:
        decision = await service.process(conversation.id, "处理中停止")
    finally:
        global_ai_control.resume()

    message = await db.scalar(
        select(Message).where(
            Message.conversation_id == conversation.id,
            Message.sender_type == SenderType.ai,
        )
    )
    assert not decision.should_send
    assert decision.response_action == ResponseAction.SILENT
    assert message is None


@pytest.mark.asyncio
async def test_multiple_accounts_are_isolated_and_select_their_adapter(db):
    first = db.info["account"]
    second = XianyuAccount(
        nickname="第二账号",
        external_account_id="test-account-2",
        status="CONNECTED",
        adapter_type="mock",
    )
    db.add(second)
    await db.flush()
    # The same external product id is valid under another account.
    product = Product(
        account_id=second.id,
        external_product_id="A",
        name="第二账号的商品A",
        ai_prompt="使用轻松但准确的语气",
    )
    db.add(product)
    await db.commit()

    first_adapter = adapter_for_account(first)
    second_adapter = adapter_for_account(second)
    assert isinstance(first_adapter, MockXianyuAdapter)
    assert isinstance(second_adapter, MockXianyuAdapter)
    first_send = await first_adapter.send_message("conversation", "回复", "same-reply")
    second_send = await second_adapter.send_message("conversation", "回复", "same-reply")
    assert first_send.external_message_id != second_send.external_message_id


@pytest.mark.asyncio
async def test_real_adapter_refuses_invented_login(db):
    account = XianyuAccount(
        nickname="等待合规接入",
        external_account_id="real-pending",
        status="DISCONNECTED",
        adapter_type="real",
    )
    adapter = RealXianyuAdapter(account)
    with pytest.raises(RuntimeError, match="合规"):
        await adapter.connect()
