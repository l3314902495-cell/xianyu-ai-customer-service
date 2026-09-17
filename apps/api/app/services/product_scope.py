from sqlalchemy import and_, func

from app.models import Product


def is_seller_product(product: Product) -> bool:
    """Return True only for products managed/published by the connected seller."""
    details = product.details or {}
    return not bool(details.get("auto_created")) and details.get("source") != "xianyu_conversation_sync"


def seller_product_filter():
    """SQL equivalent used before pagination so hidden rows cannot create short pages."""
    return and_(
        func.coalesce(Product.details["auto_created"].as_boolean(), False).is_(False),
        func.coalesce(Product.details["source"].as_string(), "") != "xianyu_conversation_sync",
    )
