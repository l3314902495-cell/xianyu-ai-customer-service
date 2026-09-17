from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, ProductFAQ, ProductKnowledge


class ProductKnowledgeRepository:
    """Every lookup requires a product_id; cross-product reads are impossible by API design."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def enabled_for_product(self, product_id: str) -> Sequence[ProductKnowledge]:
        result = await self.db.scalars(
            select(ProductKnowledge)
            .where(ProductKnowledge.product_id == product_id, ProductKnowledge.enabled.is_(True))
            .order_by(ProductKnowledge.priority.desc(), ProductKnowledge.created_at)
        )
        return result.all()

    async def faqs_for_product(self, product_id: str) -> Sequence[ProductFAQ]:
        result = await self.db.scalars(
            select(ProductFAQ)
            .where(ProductFAQ.product_id == product_id, ProductFAQ.enabled.is_(True))
            .order_by(ProductFAQ.priority.desc(), ProductFAQ.created_at)
        )
        return result.all()


class MessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def recent(self, conversation_id: str, limit: int) -> list[Message]:
        rows = await self.db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(reversed(rows.all()))
