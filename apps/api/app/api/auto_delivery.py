from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AutoDeliveryConfig,
    Conversation,
    DeliveryInventory,
    DeliveryRecord,
    Product,
    TradeOrder,
    XianyuAccount,
)
from app.schemas_delivery import (
    CardInventoryCreate,
    DeliveryConfigUpdate,
    DeliveryResolutionRequest,
    MockPaidOrderRequest,
)
from app.secrets import encrypt_secret
from app.security import current_user
from app.services.auto_delivery import AutoDeliveryService, make_mock_order_id
from app.services.product_scope import is_seller_product
from app.time_utils import utc_iso

router = APIRouter(
    prefix="/api/auto-delivery",
    tags=["auto-delivery"],
    dependencies=[Depends(current_user)],
)


def mask_secret(value: str) -> str:
    value = value.strip()
    if len(value) <= 6:
        return "*" * max(len(value) - 2, 2) + value[-2:]
    return f"{value[:2]}{'*' * min(len(value) - 6, 12)}{value[-4:]}"


async def config_payload(db: AsyncSession, product: Product) -> dict:
    config = await db.scalar(
        select(AutoDeliveryConfig).where(AutoDeliveryConfig.product_id == product.id)
    )
    available = delivered = 0
    if config:
        available = int(await db.scalar(
            select(func.count()).select_from(DeliveryInventory).where(
                DeliveryInventory.config_id == config.id,
                DeliveryInventory.status == "AVAILABLE",
            )
        ) or 0)
        delivered = int(await db.scalar(
            select(func.count()).select_from(DeliveryInventory).where(
                DeliveryInventory.config_id == config.id,
                DeliveryInventory.status == "DELIVERED",
            )
        ) or 0)
    return {
        "product_id": product.id,
        "product_name": product.name,
        "external_product_id": product.external_product_id,
        "account_id": product.account_id,
        "configured": bool(config),
        "enabled": config.enabled if config else False,
        "delivery_type": config.delivery_type if config else "card",
        "message_template": config.message_template if config else "感谢购买，您的卡密是：{content}",
        "image_url": config.image_url if config else None,
        "available_count": available,
        "delivered_count": delivered,
    }


@router.get("/products")
async def list_product_configs(db: AsyncSession = Depends(get_db)) -> list[dict]:
    products = (await db.scalars(
        select(Product)
        .where(Product.status == "ACTIVE")
        .order_by(Product.updated_at.desc())
    )).all()
    return [await config_payload(db, product) for product in products if is_seller_product(product)]


@router.get("/products/{product_id}")
async def get_config(product_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "商品不存在")
    return await config_payload(db, product)


@router.put("/products/{product_id}")
async def update_config(
    product_id: str,
    body: DeliveryConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "商品不存在")
    config = await db.scalar(
        select(AutoDeliveryConfig).where(AutoDeliveryConfig.product_id == product_id)
    )
    if not config:
        config = AutoDeliveryConfig(product_id=product_id)
        db.add(config)
    if body.delivery_type == "card" and "{content}" not in body.message_template:
        raise HTTPException(422, "卡密发货话术必须包含 {content} 占位符")
    if body.delivery_type == "image" and (
        not body.image_url or not body.image_url.startswith("https://")
    ):
        raise HTTPException(422, "图片发货必须填写公网 HTTPS 图片地址")
    for key, value in body.model_dump().items():
        setattr(config, key, value)
    await db.commit()
    return await config_payload(db, product)


@router.get("/products/{product_id}/inventory")
async def list_inventory(product_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    config = await db.scalar(
        select(AutoDeliveryConfig).where(AutoDeliveryConfig.product_id == product_id)
    )
    if not config:
        return []
    rows = (await db.scalars(
        select(DeliveryInventory)
        .where(DeliveryInventory.config_id == config.id)
        .order_by(DeliveryInventory.created_at.desc())
        .limit(500)
    )).all()
    return [{
        "id": row.id,
        "content_mask": row.content_mask,
        "status": row.status,
        "delivered_at": utc_iso(row.delivered_at),
        "created_at": utc_iso(row.created_at),
    } for row in rows]


@router.post("/products/{product_id}/inventory/cards")
async def add_cards(
    product_id: str,
    body: CardInventoryCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "商品不存在")
    config = await db.scalar(
        select(AutoDeliveryConfig).where(AutoDeliveryConfig.product_id == product_id)
    )
    if not config:
        config = AutoDeliveryConfig(product_id=product_id, delivery_type="card", enabled=False)
        db.add(config)
        await db.flush()
    values = list(dict.fromkeys(value.strip() for value in body.contents if value.strip()))
    if not values:
        raise HTTPException(422, "没有可导入的卡密")
    for value in values:
        db.add(DeliveryInventory(
            config_id=config.id,
            encrypted_content=encrypt_secret(value),
            content_mask=mask_secret(value),
        ))
    await db.commit()
    return {"added": len(values), "enabled": config.enabled}


@router.delete("/products/{product_id}/inventory/{inventory_id}")
async def remove_inventory(
    product_id: str,
    inventory_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    config = await db.scalar(
        select(AutoDeliveryConfig).where(AutoDeliveryConfig.product_id == product_id)
    )
    row = await db.get(DeliveryInventory, inventory_id)
    if not config or not row or row.config_id != config.id:
        raise HTTPException(404, "卡密不存在")
    if row.status != "AVAILABLE":
        raise HTTPException(409, "已预留或已发出的卡密不能删除")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.get("/records")
async def list_records(limit: int = 100, db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(
        select(DeliveryRecord, TradeOrder, Product)
        .join(TradeOrder, TradeOrder.id == DeliveryRecord.order_id)
        .join(Product, Product.id == TradeOrder.product_id)
        .order_by(DeliveryRecord.created_at.desc())
        .limit(min(max(limit, 1), 500))
    )).all()
    return [{
        "id": record.id,
        "product_id": product.id,
        "product_name": product.name,
        "external_order_id": order.external_order_id,
        "delivery_type": record.delivery_type,
        "content_mask": record.content_mask,
        "status": record.status,
        "reply_id": record.reply_id,
        "external_message_id": record.external_message_id,
        "error": record.error,
        "attempts": record.attempts,
        "lease_expires_at": utc_iso(record.lease_expires_at),
        "delivered_at": utc_iso(record.delivered_at),
        "resolved_at": utc_iso(record.resolved_at),
        "created_at": utc_iso(record.created_at),
    } for record, order, product in rows]


@router.post("/records/{record_id}/resolve")
async def resolve_delivery(
    record_id: str,
    body: DeliveryResolutionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await AutoDeliveryService(db).resolve_unknown(
        record_id,
        sent=body.action == "mark_sent",
        external_message_id=body.external_message_id,
    )
    if result["status"] == "record_not_found":
        raise HTTPException(404, "发货记录不存在")
    if result["status"] == "not_unknown":
        raise HTTPException(409, "只有结果待确认的发货记录可以人工处理")
    return result


@router.post("/simulate-paid")
async def simulate_paid(
    body: MockPaidOrderRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    product = await db.get(Product, body.product_id)
    if not product:
        raise HTTPException(404, "商品不存在")
    account = await db.get(XianyuAccount, product.account_id)
    if not account or account.adapter_type != "mock":
        raise HTTPException(400, "付款模拟器只允许 Mock 闲鱼账号，防止误触真实商品")
    conversation_id = body.conversation_id
    if not conversation_id:
        conversation = await db.scalar(
            select(Conversation)
            .where(
                Conversation.product_id == product.id,
                Conversation.buyer_id == body.buyer_id,
            )
            .order_by(Conversation.updated_at.desc())
        )
        if not conversation:
            conversation = Conversation(
                account_id=product.account_id,
                product_id=product.id,
                external_conversation_id=f"mock-delivery-{product.id}-{body.buyer_id}",
                buyer_id=body.buyer_id,
                buyer_nickname="自动发货测试买家",
            )
            db.add(conversation)
            await db.commit()
            await db.refresh(conversation)
        conversation_id = conversation.id
    return await AutoDeliveryService(db).handle_paid_order(
        account_id=product.account_id,
        product_id=product.id,
        external_order_id=body.external_order_id or make_mock_order_id(),
        buyer_id=body.buyer_id,
        conversation_id=conversation_id,
        source="mock",
        raw_payload={"simulated": True},
    )
