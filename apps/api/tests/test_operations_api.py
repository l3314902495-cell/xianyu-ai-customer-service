import pytest

from app.models import ConversationStatus, KnowledgeGap
from app.services.global_ai_control import global_ai_control


@pytest.mark.asyncio
async def test_reply_rules_and_runtime_settings_are_persisted(api_client):
    rules = {
        "minimum_confidence": 0.82,
        "shop_rules": "只允许回答已知事实",
        "price_negotiation_reply": "价格由卖家确认。",
        "knowledge_gap_reply": "这项信息需要卖家确认。",
        "forbidden_reply_phrases": ["保证退款", "保证退款", " 绝对正品 "],
    }
    response = await api_client.put("/api/ai/reply-rules", json=rules)
    assert response.status_code == 200
    assert response.json()["minimum_confidence"] == 0.82
    assert response.json()["forbidden_reply_phrases"] == ["保证退款", "绝对正品"]
    assert (await api_client.get("/api/ai/reply-rules")).json()["shop_rules"] == "只允许回答已知事实"

    runtime = {
        "debounce_ms": 2300,
        "history_limit": 12,
        "ignored_message_prefixes": ["系统通知：", "系统通知："],
    }
    response = await api_client.put("/api/system/settings", json=runtime)
    assert response.status_code == 200
    assert response.json() == {
        "debounce_ms": 2300,
        "history_limit": 12,
        "ignored_message_prefixes": ["系统通知："],
    }


@pytest.mark.asyncio
async def test_emergency_stop_updates_database_and_immediate_barrier(api_client):
    try:
        await api_client.put("/api/system/ai-switch", json={"enabled": True})
        response = await api_client.post("/api/system/emergency-stop")
        assert response.status_code == 200
        assert response.json()["emergency"] is True
        assert global_ai_control.stopped
        assert (await api_client.get("/api/system/ai-switch")).json() == {"enabled": False}
    finally:
        await api_client.put("/api/system/ai-switch", json={"enabled": True})
        assert not global_ai_control.stopped


@pytest.mark.asyncio
async def test_all_conversations_can_switch_between_human_and_ai(api_client, db):
    conversation = db.info["conversation"]
    try:
        response = await api_client.post("/api/system/all-human-takeover")
        assert response.status_code == 200
        assert response.json()["updated"] == 1
        assert response.json()["mode"] == "human"
        await db.refresh(conversation)
        assert conversation.human_takeover
        assert not conversation.ai_enabled
        assert conversation.status == ConversationStatus.ACTIVE_HUMAN
        assert global_ai_control.stopped

        response = await api_client.post("/api/system/all-ai-takeover")
        assert response.status_code == 200
        assert response.json()["updated"] == 1
        assert response.json()["mode"] == "ai"
        await db.refresh(conversation)
        assert not conversation.human_takeover
        assert conversation.ai_enabled
        assert conversation.status == ConversationStatus.ACTIVE_AI
        assert not global_ai_control.stopped
    finally:
        await api_client.put("/api/system/ai-switch", json={"enabled": True})


@pytest.mark.asyncio
async def test_conversation_read_close_and_reopen(api_client, db):
    conversation = db.info["conversation"]
    conversation.unread_count = 3
    await db.commit()

    response = await api_client.post(f"/api/conversations/{conversation.id}/read")
    assert response.status_code == 200
    assert response.json()["unread_count"] == 0

    response = await api_client.post(f"/api/conversations/{conversation.id}/close")
    assert response.status_code == 200
    assert response.json()["status"] == "CLOSED"
    assert not response.json()["ai_enabled"]
    active = await api_client.get("/api/conversations")
    assert all(item["id"] != conversation.id for item in active.json()["items"])

    response = await api_client.post(f"/api/conversations/{conversation.id}/reopen")
    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE_AI"
    assert response.json()["ai_enabled"]
    await db.refresh(conversation)
    assert conversation.status == ConversationStatus.ACTIVE_AI


@pytest.mark.asyncio
async def test_knowledge_gap_can_only_be_resolved_once_or_ignored(api_client, db):
    conversation = db.info["conversation"]
    product = db.info["product_a"]
    first = KnowledgeGap(
        product_id=product.id,
        conversation_id=conversation.id,
        user_message="什么时候买的？",
        missing_knowledge="购买时间",
        ai_reply="需要卖家确认",
    )
    second = KnowledgeGap(
        product_id=product.id,
        conversation_id=conversation.id,
        user_message="是否有发票？",
        missing_knowledge="发票情况",
        ai_reply="需要卖家确认",
    )
    db.add_all([first, second])
    await db.commit()

    payload = {"title": "购买时间", "content": "2025 年 11 月购买", "category": "parameter"}
    response = await api_client.post(f"/api/knowledge-gaps/{first.id}/save-knowledge", json=payload)
    assert response.status_code == 200
    assert response.json()["knowledge_id"]
    assert (await api_client.post(f"/api/knowledge-gaps/{first.id}/save-knowledge", json=payload)).status_code == 409

    response = await api_client.post(f"/api/knowledge-gaps/{second.id}/ignore")
    assert response.status_code == 200
    assert (await api_client.post(f"/api/knowledge-gaps/{second.id}/ignore")).status_code == 409


@pytest.mark.asyncio
async def test_product_with_history_cannot_be_deleted(api_client, db):
    product = db.info["product_a"]
    response = await api_client.delete(f"/api/products/{product.id}")
    assert response.status_code == 409
    assert "停用商品" in response.json()["detail"]


@pytest.mark.asyncio
async def test_all_seller_products_can_switch_ai_takeover(api_client, db):
    product_a = db.info["product_a"]
    product_b = db.info["product_b"]

    response = await api_client.put("/api/products/ai-switch-all", json={"enabled": False})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "enabled": False, "updated": 2}
    await db.refresh(product_a)
    await db.refresh(product_b)
    assert not product_a.ai_enabled
    assert not product_b.ai_enabled

    response = await api_client.put("/api/products/ai-switch-all", json={"enabled": True})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "enabled": True, "updated": 2}
    await db.refresh(product_a)
    await db.refresh(product_b)
    assert product_a.ai_enabled
    assert product_b.ai_enabled
