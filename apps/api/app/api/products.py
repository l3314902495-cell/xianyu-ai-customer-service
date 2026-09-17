from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cursor_pagination import before_cursor, cursor_page, decode_cursor
from app.database import get_db
from app.models import (
    AIReplyLog,
    Conversation,
    KnowledgeGap,
    Product,
    ProductFAQ,
    ProductKnowledge,
    ProductPublishAttempt,
    XianyuAccount,
    XianyuAccountCredential,
)
from app.realtime import ws_manager
from app.schemas import FAQCreate, KnowledgeCreate, ProductCreate, ProductUpdate, SystemSwitch
from app.security import current_user
from app.services.product_scope import is_seller_product, seller_product_filter
from app.services.xianyu_publish import (
    PublishImage,
    PublishOutcomeUnknown,
    publish_product,
    session_from_credential,
)
from app.services.xianyu_sync import upsert_synced_product_knowledge
from app.time_utils import utc_iso

router = APIRouter(prefix="/api/products", tags=["products"], dependencies=[Depends(current_user)])

PUBLISH_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
PUBLISH_IMAGE_LIMIT = 10 * 1024 * 1024
PUBLISH_DELIVERY_TYPES = {"包邮", "按距离计费", "一口价", "无需邮寄"}


def _matches_image_signature(content_type: str, content: bytes) -> bool:
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


def product_dict(p: Product, knowledge_count: int = 0, faq_count: int = 0) -> dict:
    return {"id": p.id, "account_id": p.account_id, "external_product_id": p.external_product_id, "name": p.name, "category": p.category, "image_url": p.image_url, "price": float(p.price), "status": p.status, "ai_enabled": p.ai_enabled, "ai_prompt": p.ai_prompt, "details": p.details, "knowledge_count": knowledge_count, "faq_count": faq_count, "updated_at": utc_iso(p.updated_at)}


@router.get("")
async def list_products(
    q: str = "",
    account_id: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    kc = select(ProductKnowledge.product_id, func.count().label("count")).group_by(ProductKnowledge.product_id).subquery()
    fc = select(ProductFAQ.product_id, func.count().label("count")).group_by(ProductFAQ.product_id).subquery()
    stmt = select(Product, func.coalesce(kc.c.count, 0), func.coalesce(fc.c.count, 0)).outerjoin(kc, kc.c.product_id == Product.id).outerjoin(fc, fc.c.product_id == Product.id)
    stmt = stmt.where(seller_product_filter())
    if q:
        stmt = stmt.where(or_(Product.name.ilike(f"%{q}%"), Product.external_product_id.ilike(f"%{q}%")))
    if account_id:
        stmt = stmt.where(Product.account_id == account_id)
    if status in {"ACTIVE", "DISABLED"}:
        stmt = stmt.where(Product.status == status)
    stmt = before_cursor(stmt, Product.updated_at, Product.id, decode_cursor(cursor))
    stmt = stmt.order_by(Product.updated_at.desc(), Product.id.desc()).limit(limit + 1)
    rows = [
        product_dict(p, k, f)
        for p, k, f in (await db.execute(stmt)).all()
    ]
    return cursor_page(
        rows,
        limit,
        timestamp=lambda item: datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00")),
        row_id=lambda item: item["id"],
    )


@router.post("")
async def create_product(body: ProductCreate, db: AsyncSession = Depends(get_db)) -> dict:
    if not await db.get(XianyuAccount, body.account_id):
        raise HTTPException(404, "闲鱼账号不存在")
    p = Product(**body.model_dump())
    db.add(p)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "该账号下的商品 ID 已存在") from None
    await db.refresh(p)
    return product_dict(p)


@router.post("/publish", status_code=201)
async def publish_real_product(
    account_id: str = Form(...),
    idempotency_key: str = Form(..., min_length=16, max_length=80),
    title: str = Form(..., min_length=5, max_length=60),
    description: str = Form(..., min_length=10, max_length=5000),
    price: float = Form(..., gt=0, le=9999999),
    original_price: float | None = Form(default=None, gt=0, le=9999999),
    delivery: str = Form(default="无需邮寄"),
    post_price: float = Form(default=0, ge=0, le=99999),
    can_self_pickup: bool = Form(default=True),
    images: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Publish once to a user-owned experimental web account; never auto-retry."""
    account = await db.get(XianyuAccount, account_id)
    if not account:
        raise HTTPException(404, "闲鱼账号不存在")
    if account.adapter_type != "experimental-web":
        raise HTTPException(409, "真实发布仅支持已扫码连接的闲鱼网页版账号")
    if account.status != "CONNECTED":
        raise HTTPException(409, "闲鱼账号当前未连接，请先恢复登录")
    credential = await db.scalar(
        select(XianyuAccountCredential).where(XianyuAccountCredential.account_id == account_id)
    )
    if not credential:
        raise HTTPException(409, "账号缺少扫码登录凭据，请先恢复登录")
    if delivery not in PUBLISH_DELIVERY_TYPES:
        raise HTTPException(422, "不支持的发货方式")
    if delivery == "一口价" and post_price <= 0:
        raise HTTPException(422, "选择一口价运费时必须填写运费")
    if not 1 <= len(images) <= 9:
        raise HTTPException(422, "请选择 1–9 张商品图片")

    prepared_images: list[PublishImage] = []
    for image in images:
        content_type = str(image.content_type or "").lower()
        if content_type not in PUBLISH_IMAGE_TYPES:
            raise HTTPException(422, f"{image.filename or '图片'}：仅支持 JPG、PNG 或 WebP")
        content = await image.read(PUBLISH_IMAGE_LIMIT + 1)
        if not content:
            raise HTTPException(422, f"{image.filename or '图片'}：文件为空")
        if len(content) > PUBLISH_IMAGE_LIMIT:
            raise HTTPException(413, f"{image.filename or '图片'}：不能超过 10 MB")
        if not _matches_image_signature(content_type, content):
            raise HTTPException(422, f"{image.filename or '图片'}：文件内容不是有效的图片格式")
        prepared_images.append(
            PublishImage(image.filename or "product-image", content_type, content)
        )

    # Serialize the check-and-register section per account. On PostgreSQL this
    # row lock makes different idempotency keys obey the same one-minute gate.
    await db.scalar(
        select(XianyuAccount).where(XianyuAccount.id == account_id).with_for_update()
    )
    existing_attempt = await db.scalar(
        select(ProductPublishAttempt).where(
            ProductPublishAttempt.idempotency_key == idempotency_key
        )
    )
    if existing_attempt:
        if existing_attempt.status == "PUBLISHED" and existing_attempt.product_id:
            product = await db.get(Product, existing_attempt.product_id)
            if product:
                return {"status": "PUBLISHED", "product": product_dict(product)}
        raise HTTPException(
            409,
            "这次发布已提交或结果待确认。为避免重复商品，请先同步商品列表。",
        )

    now = datetime.now(UTC)
    blocking_attempt = await db.scalar(
        select(ProductPublishAttempt)
        .where(
            ProductPublishAttempt.account_id == account_id,
            or_(
                ProductPublishAttempt.status == "UNKNOWN",
                (
                    ProductPublishAttempt.status.in_(["PENDING", "PUBLISHED"])
                    & (ProductPublishAttempt.created_at >= now - timedelta(seconds=60))
                ),
            ),
        )
        .order_by(ProductPublishAttempt.created_at.desc())
        .limit(1)
    )
    if blocking_attempt:
        if blocking_attempt.status == "UNKNOWN":
            raise HTTPException(409, "存在结果待确认的发布，请先同步商品列表，确认后再发布")
        raise HTTPException(429, "每个账号每分钟最多发布 1 件商品，请稍后再试")

    attempt = ProductPublishAttempt(
        account_id=account_id,
        idempotency_key=idempotency_key,
        title=title.strip(),
        status="PENDING",
        request_summary={
            "price": price,
            "original_price": original_price,
            "delivery": delivery,
            "post_price": post_price,
            "can_self_pickup": can_self_pickup,
            "image_count": len(prepared_images),
        },
    )
    db.add(attempt)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "这次发布已经提交，请勿重复操作") from None
    await db.refresh(attempt)

    try:
        result = await publish_product(
            session=session_from_credential(account, credential),
            title=title.strip(),
            description=description.strip(),
            images=prepared_images,
            price=price,
            original_price=original_price,
            delivery=delivery,
            post_price=post_price,
            can_self_pickup=can_self_pickup,
        )
    except PublishOutcomeUnknown as exc:
        attempt.status = "UNKNOWN"
        attempt.error = str(exc)
        await db.commit()
        raise HTTPException(409, str(exc)) from None
    except Exception as exc:
        attempt.status = "FAILED"
        attempt.error = str(exc)[:2000]
        await db.commit()
        raise HTTPException(502, f"发布失败：{exc}") from None

    external_id = result["external_product_id"]
    product = await db.scalar(
        select(Product).where(
            Product.account_id == account_id,
            Product.external_product_id == external_id,
        )
    )
    if not product:
        product = Product(
            account_id=account_id,
            external_product_id=external_id,
            name=title.strip(),
            category=result["category"] or None,
            image_url=result["image_url"],
            price=price,
            status="ACTIVE",
            ai_enabled=account.ai_enabled,
            ai_prompt="",
            details={
                "source": "xianyu_publish",
                "description": description.strip(),
                "delivery": delivery,
                "post_price": post_price,
                "can_self_pickup": can_self_pickup,
                "published_at": datetime.now(UTC).isoformat(),
            },
        )
        db.add(product)
        await db.flush()
        await upsert_synced_product_knowledge(
            db,
            product,
            {
                "name": product.name,
                "price": product.price,
                "status": product.status,
                "description": description.strip(),
                "shipping_origin": "",
            },
        )
    attempt.status = "PUBLISHED"
    attempt.external_product_id = external_id
    attempt.product_id = product.id
    attempt.error = None
    await db.commit()
    await db.refresh(product)
    await ws_manager.broadcast("product_published", {"product_id": product.id, "account_id": account_id})
    return {"status": "PUBLISHED", "product": product_dict(product)}


@router.put("/ai-switch-all")
async def set_all_products_ai(body: SystemSwitch, db: AsyncSession = Depends(get_db)) -> dict:
    """Change AI takeover for every seller product, including products without conversations."""
    products = (await db.scalars(select(Product))).all()
    seller_products = [product for product in products if is_seller_product(product)]
    for product in seller_products:
        product.ai_enabled = body.enabled
    await db.commit()
    await ws_manager.broadcast(
        "products_ai_switch",
        {"enabled": body.enabled, "updated": len(seller_products)},
    )
    return {"ok": True, "enabled": body.enabled, "updated": len(seller_products)}


@router.get("/{product_id}")
async def get_product(product_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    p = await db.get(Product, product_id)
    if not p: raise HTTPException(404, "商品不存在")
    return product_dict(p)


@router.patch("/{product_id}")
async def update_product(product_id: str, body: ProductUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    p = await db.get(Product, product_id)
    if not p: raise HTTPException(404, "商品不存在")
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(p, key, value)
    await db.commit(); await db.refresh(p)
    return product_dict(p)


@router.delete("/{product_id}")
async def delete_product(product_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    p = await db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "商品不存在")
    has_history = False
    for model in (Conversation, AIReplyLog, KnowledgeGap):
        if await db.scalar(select(model.id).where(model.product_id == product_id).limit(1)):
            has_history = True
            break
    if has_history:
        raise HTTPException(409, "商品已有会话或 AI 历史，请停用商品以保留审计记录")
    await db.delete(p)
    await db.commit()
    return {"ok": True}


@router.get("/{product_id}/knowledge")
async def list_knowledge(product_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    if not await db.get(Product, product_id):
        raise HTTPException(404, "商品不存在")
    rows = (await db.scalars(select(ProductKnowledge).where(ProductKnowledge.product_id == product_id).order_by(ProductKnowledge.priority.desc()))).all()
    return [{"id": r.id, "product_id": r.product_id, "title": r.title, "content": r.content, "category": r.category, "priority": r.priority, "enabled": r.enabled, "source": r.source} for r in rows]


@router.post("/{product_id}/knowledge")
async def add_knowledge(product_id: str, body: KnowledgeCreate, db: AsyncSession = Depends(get_db)) -> dict:
    if not await db.get(Product, product_id): raise HTTPException(404, "商品不存在")
    row = ProductKnowledge(product_id=product_id, **body.model_dump()); db.add(row); await db.commit(); await db.refresh(row)
    return {"id": row.id, **body.model_dump()}


@router.patch("/{product_id}/knowledge/{knowledge_id}")
async def edit_knowledge(product_id: str, knowledge_id: str, body: KnowledgeCreate, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.scalar(select(ProductKnowledge).where(ProductKnowledge.id == knowledge_id, ProductKnowledge.product_id == product_id))
    if not row: raise HTTPException(404, "知识不存在")
    for k, v in body.model_dump().items(): setattr(row, k, v)
    await db.commit(); return {"ok": True}


@router.delete("/{product_id}/knowledge/{knowledge_id}")
async def remove_knowledge(product_id: str, knowledge_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.scalar(select(ProductKnowledge).where(ProductKnowledge.id == knowledge_id, ProductKnowledge.product_id == product_id))
    if not row: raise HTTPException(404, "知识不存在")
    await db.delete(row); await db.commit(); return {"ok": True}


@router.get("/{product_id}/faqs")
async def list_faqs(product_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    if not await db.get(Product, product_id):
        raise HTTPException(404, "商品不存在")
    rows = (await db.scalars(select(ProductFAQ).where(ProductFAQ.product_id == product_id).order_by(ProductFAQ.priority.desc()))).all()
    return [{"id": r.id, "question": r.question, "answer": r.answer, "keywords": r.keywords, "enabled": r.enabled, "priority": r.priority} for r in rows]


@router.post("/{product_id}/faqs")
async def add_faq(product_id: str, body: FAQCreate, db: AsyncSession = Depends(get_db)) -> dict:
    if not await db.get(Product, product_id): raise HTTPException(404, "商品不存在")
    row = ProductFAQ(product_id=product_id, **body.model_dump()); db.add(row); await db.commit(); await db.refresh(row)
    return {"id": row.id, **body.model_dump()}


@router.patch("/{product_id}/faqs/{faq_id}")
async def edit_faq(product_id: str, faq_id: str, body: FAQCreate, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.scalar(select(ProductFAQ).where(ProductFAQ.id == faq_id, ProductFAQ.product_id == product_id))
    if not row: raise HTTPException(404, "FAQ 不存在")
    for k, v in body.model_dump().items(): setattr(row, k, v)
    await db.commit(); return {"ok": True}


@router.delete("/{product_id}/faqs/{faq_id}")
async def remove_faq(product_id: str, faq_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.scalar(select(ProductFAQ).where(ProductFAQ.id == faq_id, ProductFAQ.product_id == product_id))
    if not row: raise HTTPException(404, "FAQ 不存在")
    await db.delete(row); await db.commit(); return {"ok": True}
