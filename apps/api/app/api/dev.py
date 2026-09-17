import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Conversation, Product, SystemSetting
from app.schemas import SimulatorRequest
from app.security import current_user
from app.services.message_processor import MessageProcessor

router = APIRouter(prefix="/api/dev", tags=["dev"], dependencies=[Depends(current_user)])


@router.post("/simulator")
async def simulate(body: SimulatorRequest, db: AsyncSession = Depends(get_db)) -> dict:
    product = await db.get(Product, body.product_id)
    if not product or product.account_id != body.account_id: raise HTTPException(400, "账号与商品不匹配")
    if product.status != "ACTIVE":
        raise HTTPException(409, "该商品已下架，不能模拟买家咨询")
    external_conversation_id = f"mock-{body.account_id}-{body.product_id}-{body.buyer_id}"
    conversation = await db.scalar(select(Conversation).where(Conversation.external_conversation_id == external_conversation_id))
    if not conversation:
        conversation = Conversation(account_id=body.account_id, product_id=body.product_id, external_conversation_id=external_conversation_id, buyer_id=body.buyer_id, buyer_nickname=body.buyer_nickname)
        db.add(conversation); await db.commit(); await db.refresh(conversation)
    external_message_id = body.external_message_id or f"sim-{uuid.uuid4()}"
    accepted = await MessageProcessor(db).receive(
        conversation,
        body.content.strip(),
        external_message_id,
        debounce=True,
    )
    runtime = await db.get(SystemSetting, "runtime_settings")
    debounce_ms = int(
        (runtime.value if runtime else {}).get("debounce_ms", get_settings().debounce_ms)
    )
    return {
        "accepted": accepted,
        "conversation_id": conversation.id,
        "external_message_id": external_message_id,
        "debounce_ms": debounce_ms,
        "status": "queued" if accepted else "duplicate_or_filtered",
    }
