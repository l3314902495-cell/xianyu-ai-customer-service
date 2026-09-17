import pytest
from sqlalchemy import select

from app.models import Message, SenderType
from app.services.redis_runtime import redis_runtime


@pytest.mark.asyncio
async def test_send_ai_suggestion_is_atomic_and_leaves_one_visible_reply(api_client, db):
    conversation = db.info["conversation"]
    suggestion = Message(
        conversation_id=conversation.id,
        sender_type=SenderType.ai,
        content="可以直接拍下。",
        message_type="ai_suggestion",
        sent=False,
    )
    db.add(suggestion)
    await db.commit()

    response = await api_client.post(
        f"/api/conversations/{conversation.id}/reply",
        json={"content": suggestion.content, "suggestion_id": suggestion.id},
    )

    assert response.status_code == 200
    await db.refresh(suggestion)
    assert suggestion.message_type == "ai_suggestion_sent"
    visible = (
        await db.scalars(
            select(Message).where(
                Message.conversation_id == conversation.id,
                Message.message_type.not_in(["ai_suggestion_sent", "ai_suggestion_ignored"]),
                Message.content == suggestion.content,
            )
        )
    ).all()
    assert len(visible) == 1
    assert visible[0].sender_type == SenderType.human


@pytest.mark.asyncio
async def test_takeover_hides_all_pending_ai_suggestions(api_client, db):
    conversation = db.info["conversation"]
    suggestions = [
        Message(
            conversation_id=conversation.id,
            sender_type=SenderType.ai,
            content=f"AI 建议 {index}",
            message_type="ai_suggestion",
            sent=False,
        )
        for index in range(2)
    ]
    db.add_all(suggestions)
    await db.commit()

    response = await api_client.post(f"/api/conversations/{conversation.id}/takeover")

    assert response.status_code == 200
    for suggestion in suggestions:
        await db.refresh(suggestion)
        assert suggestion.message_type == "ai_suggestion_ignored"


@pytest.mark.asyncio
async def test_simulator_rejects_disabled_product(api_client, db):
    account = db.info["account"]
    product = db.info["product_a"]
    product.status = "DISABLED"
    await db.commit()

    response = await api_client.post(
        "/api/dev/simulator",
        json={
            "account_id": account.id,
            "product_id": product.id,
            "buyer_id": "disabled-product-buyer",
            "buyer_nickname": "下架商品测试买家",
            "content": "这个还有吗？",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "该商品已下架，不能模拟买家咨询"


@pytest.mark.asyncio
async def test_full_mock_customer_service_http_workflow(api_client, db, monkeypatch):
    async def immediate_debounce(conversation_id, content, callback, delay_ms=None):
        await callback(content)

    async def acquire_lock(conversation_id, ttl=180):
        return f"test-lock-{conversation_id}"

    async def release_lock(conversation_id, token):
        return None

    monkeypatch.setattr(redis_runtime, "debounce", immediate_debounce)
    monkeypatch.setattr(redis_runtime, "acquire_lock", acquire_lock)
    monkeypatch.setattr(redis_runtime, "release_lock", release_lock)

    account = db.info["account"]
    create = await api_client.post(
        "/api/products",
        json={
            "account_id": account.id,
            "external_product_id": "HTTP-E2E-PRODUCT",
            "name": "HTTP E2E 测试商品",
            "price": 499,
            "ai_prompt": "语气自然简洁，只回答已知事实。",
            "details": {"special_rules": "不得猜测未记录参数"},
        },
    )
    assert create.status_code == 200
    product = create.json()

    knowledge = await api_client.post(
        f"/api/products/{product['id']}/knowledge",
        json={
            "title": "电池情况",
            "content": "电池健康度 98%",
            "category": "parameter",
            "priority": 10,
            "enabled": True,
            "source": "manual",
        },
    )
    assert knowledge.status_code == 200

    known_payload = {
        "account_id": account.id,
        "product_id": product["id"],
        "buyer_id": "http-e2e-buyer",
        "buyer_nickname": "流程测试买家",
        "content": "电池情况怎么样？",
        "external_message_id": "http-e2e-known-1",
    }
    first = await api_client.post("/api/dev/simulator", json=known_payload)
    assert first.status_code == 200 and first.json()["accepted"]
    conversation_id = first.json()["conversation_id"]
    messages = (await api_client.get(f"/api/conversations/{conversation_id}/messages")).json()["items"]
    assert any(item["sender_type"] == "ai" and item["sent"] and "98%" in item["content"] for item in messages)

    duplicate = await api_client.post("/api/dev/simulator", json=known_payload)
    assert duplicate.status_code == 200 and not duplicate.json()["accepted"]

    unknown = await api_client.post(
        "/api/dev/simulator",
        json={**known_payload, "content": "是哪年哪月买的？", "external_message_id": "http-e2e-gap-1"},
    )
    assert unknown.status_code == 200 and unknown.json()["accepted"]
    conversation = (await api_client.get(f"/api/conversations/{conversation_id}")).json()
    assert conversation["needs_human"] and conversation["status"] == "NEEDS_HUMAN"

    gaps = (await api_client.get("/api/knowledge-gaps?status=pending")).json()
    gap = next(item for item in gaps if item["conversation_id"] == conversation_id)
    assert (await api_client.post(f"/api/conversations/{conversation_id}/takeover")).status_code == 200
    human = await api_client.post(
        f"/api/conversations/{conversation_id}/reply",
        json={"content": "这件商品是 2025 年 11 月购买的。"},
    )
    assert human.status_code == 200 and human.json()["ok"]

    saved = await api_client.post(
        f"/api/knowledge-gaps/{gap['id']}/save-knowledge",
        json={"title": "购买时间", "content": "2025 年 11 月购买", "category": "parameter"},
    )
    assert saved.status_code == 200
    resumed = await api_client.post(f"/api/conversations/{conversation_id}/resume-ai")
    assert resumed.status_code == 200 and resumed.json()["status"] == "ACTIVE_AI"

    final = await api_client.post(
        "/api/dev/simulator",
        json={**known_payload, "content": "购买时间是什么时候？", "external_message_id": "http-e2e-known-2"},
    )
    assert final.status_code == 200 and final.json()["accepted"]
    messages = (await api_client.get(f"/api/conversations/{conversation_id}/messages")).json()["items"]
    assert any(item["sender_type"] == "ai" and item["sent"] and "2025" in item["content"] for item in messages)
