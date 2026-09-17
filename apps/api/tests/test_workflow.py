import pytest
from sqlalchemy import func, select

from app.models import ConversationStatus, Message, ProductKnowledge, SenderType
from app.services.message_processor import MessageProcessor


@pytest.mark.asyncio
async def test_takeover_resume_and_idempotency(db):
    c=db.info["conversation"]
    c.human_takeover=True;c.ai_enabled=False;c.status=ConversationStatus.ACTIVE_HUMAN;await db.commit()
    assert c.human_takeover and not c.ai_enabled
    c.human_takeover=False;c.ai_enabled=True;c.needs_human=False;c.status=ConversationStatus.ACTIVE_AI;await db.commit()
    assert c.status==ConversationStatus.ACTIVE_AI
    db.add(Message(conversation_id=c.id,external_message_id="same-id",sender_type=SenderType.customer,content="第一条"));await db.commit()
    accepted=await MessageProcessor(db).receive(c,"重复消息","same-id",debounce=False)
    assert not accepted
    count=await db.scalar(select(func.count()).select_from(Message).where(Message.external_message_id=="same-id"))
    assert count==1


@pytest.mark.asyncio
async def test_human_takeover_stores_buyer_message_without_ai_suggestion(db):
    c = db.info["conversation"]
    c.human_takeover = True
    c.ai_enabled = False
    c.status = ConversationStatus.ACTIVE_HUMAN
    await db.commit()

    accepted = await MessageProcessor(db).receive(
        c,
        "人工接管期间的新消息",
        "human-takeover-inbound",
        debounce=False,
    )

    assert accepted
    rows = (
        await db.scalars(
            select(Message).where(Message.conversation_id == c.id).order_by(Message.created_at)
        )
    ).all()
    assert [(row.sender_type, row.content) for row in rows] == [
        (SenderType.customer, "人工接管期间的新消息")
    ]


@pytest.mark.asyncio
async def test_e2e_core_human_knowledge_resume(db):
    c,p=db.info["conversation"],db.info["product_a"]
    # inbound unknown -> AI suggestion -> knowledge gap / needs human
    await MessageProcessor(db).receive(c,"购买时间是什么时候？","e2e-1",debounce=False)
    await db.refresh(c)
    assert c.needs_human
    c.human_takeover=True;c.ai_enabled=False;c.status=ConversationStatus.ACTIVE_HUMAN
    db.add(Message(conversation_id=c.id,reply_id="human-e2e",sender_type=SenderType.human,content="2025年11月购买",sent=True))
    db.add(ProductKnowledge(product_id=p.id,title="购买时间",content="2025年11月购买",source="knowledge_gap"))
    await db.commit()
    c.human_takeover=False;c.ai_enabled=True;c.needs_human=False;c.status=ConversationStatus.ACTIVE_AI;await db.commit()
    await MessageProcessor(db).receive(c,"购买时间？","e2e-2",debounce=False)
    await db.refresh(c)
    assert not c.needs_human and c.status==ConversationStatus.ACTIVE_AI


@pytest.mark.asyncio
async def test_price_negotiation_is_human_only(db):
    c=db.info["conversation"]
    await MessageProcessor(db).receive(c,"能便宜点吗，最低多少？","price-1",debounce=False)
    await db.refresh(c)
    assert c.needs_human and c.last_intent=="price_negotiation"
