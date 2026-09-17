import pytest
from sqlalchemy import func, select

from app.adapters.xianyu import SendResult
from app.models import AutoDeliveryConfig, DeliveryInventory, DeliveryRecord
from app.secrets import encrypt_secret
from app.services import auto_delivery as auto_delivery_module
from app.services.auto_delivery import (
    AutoDeliveryService,
    DeliveryState,
    transition_delivery,
)
from app.services.xianyu_protocol import extract_paid_order_event


def test_delivery_state_machine_rejects_reopening_terminal_record():
    record = DeliveryRecord(status=DeliveryState.SENT)

    with pytest.raises(RuntimeError, match="invalid delivery transition"):
        transition_delivery(record, DeliveryState.SENDING)


async def test_auto_delivery_is_product_scoped_and_idempotent(db):
    account = db.info["account"]
    product_a = db.info["product_a"]
    product_b = db.info["product_b"]
    conversation = db.info["conversation"]
    config = AutoDeliveryConfig(
        product_id=product_a.id,
        enabled=True,
        delivery_type="card",
        message_template="您的卡密：{content}",
    )
    db.add(config)
    await db.flush()
    db.add(DeliveryInventory(
        config_id=config.id,
        encrypted_content=encrypt_secret("SECRET-CODE-001"),
        content_mask="SE*********0001",
    ))
    await db.commit()

    service = AutoDeliveryService(db)
    sent = await service.handle_paid_order(
        account_id=account.id,
        product_id=product_a.id,
        external_order_id="order-one",
        buyer_id=conversation.buyer_id,
        conversation_id=conversation.id,
        source="mock",
    )
    duplicate = await service.handle_paid_order(
        account_id=account.id,
        product_id=product_a.id,
        external_order_id="order-one",
        buyer_id=conversation.buyer_id,
        conversation_id=conversation.id,
        source="mock",
    )
    disabled = await service.handle_paid_order(
        account_id=account.id,
        product_id=product_b.id,
        external_order_id="order-two",
        buyer_id=conversation.buyer_id,
        conversation_id=None,
        source="mock",
    )

    assert sent["status"] == "sent"
    assert duplicate["status"] == "duplicate"
    assert disabled["status"] == "disabled_for_product"
    assert await db.scalar(select(func.count()).select_from(DeliveryRecord)) == 1
    inventory = await db.scalar(select(DeliveryInventory))
    assert inventory.status == "DELIVERED"


async def test_auto_delivery_product_list_excludes_disabled_products(api_client, db):
    product_a = db.info["product_a"]
    product_b = db.info["product_b"]
    product_b.status = "DISABLED"
    await db.commit()

    response = await api_client.get("/api/auto-delivery/products")

    assert response.status_code == 200
    product_ids = {item["product_id"] for item in response.json()}
    assert product_a.id in product_ids
    assert product_b.id not in product_ids


async def test_auto_delivery_never_sends_for_disabled_product(db):
    account = db.info["account"]
    product = db.info["product_a"]
    conversation = db.info["conversation"]
    product.status = "DISABLED"
    config = AutoDeliveryConfig(
        product_id=product.id,
        enabled=True,
        delivery_type="card",
        message_template="您的卡密是：{content}",
    )
    db.add(config)
    await db.flush()
    db.add(DeliveryInventory(
        config_id=config.id,
        encrypted_content=encrypt_secret("DISABLED-PRODUCT-CODE"),
        content_mask="DI***************CODE",
    ))
    await db.commit()

    result = await AutoDeliveryService(db).handle_paid_order(
        account_id=account.id,
        product_id=product.id,
        external_order_id="disabled-product-order",
        buyer_id=conversation.buyer_id,
        conversation_id=conversation.id,
        source="mock",
    )

    assert result == {"status": "product_inactive", "sent": False}
    assert await db.scalar(select(func.count()).select_from(DeliveryRecord)) == 0
    inventory = await db.scalar(select(DeliveryInventory))
    assert inventory.status == "AVAILABLE"


async def test_unknown_delivery_keeps_inventory_reserved_until_manual_resolution(db, monkeypatch):
    account = db.info["account"]
    product = db.info["product_a"]
    conversation = db.info["conversation"]
    config = AutoDeliveryConfig(
        product_id=product.id,
        enabled=True,
        delivery_type="card",
        message_template="您的卡密是：{content}",
    )
    db.add(config)
    await db.flush()
    inventory = DeliveryInventory(
        config_id=config.id,
        encrypted_content=encrypt_secret("UNCERTAIN-CODE"),
        content_mask="UN********CODE",
    )
    db.add(inventory)
    await db.commit()

    class UnknownAdapter:
        async def send_message(self, *_args, **_kwargs):
            return SendResult(False, error="listener timeout", outcome_unknown=True)

    monkeypatch.setattr(auto_delivery_module, "adapter_for_account", lambda _account: UnknownAdapter())
    service = AutoDeliveryService(db)
    result = await service.handle_paid_order(
        account_id=account.id,
        product_id=product.id,
        external_order_id="uncertain-order",
        buyer_id=conversation.buyer_id,
        conversation_id=conversation.id,
        source="mock",
    )

    assert result["status"] == "unknown"
    await db.refresh(inventory)
    assert inventory.status == "RESERVED"

    resolved = await service.resolve_unknown(result["record_id"], sent=False)
    assert resolved["status"] == "failed"
    await db.refresh(inventory)
    assert inventory.status == "AVAILABLE"


def test_paid_event_requires_system_type_positive_status_and_ids():
    paid = {
        "sessionId": "cid-1",
        "operation": {
            "content": {
                "contentType": 26,
                "reminder": {
                    "reminderContent": "买家已付款，等待你发货",
                    "reminderUrl": "https://www.goofish.com/order?orderId=trade-1",
                    "senderUserId": "buyer-1",
                },
            },
            "extension": {"itemId": "item-1"},
            "senderInfo": {"senderUserId": "buyer-1"},
        },
    }
    event = extract_paid_order_event(paid)
    assert event and event["external_order_id"] == "trade-1"

    unpaid = {**paid, "operation": {**paid["operation"], "content": {
        "contentType": 26,
        "reminder": {"reminderContent": "买家已拍下，待付款"},
    }}}
    ordinary_text = {**paid, "operation": {**paid["operation"], "content": {
        "contentType": 1,
        "reminder": {"reminderContent": "我已付款"},
    }}}
    assert extract_paid_order_event(unpaid) is None
    assert extract_paid_order_event(ordinary_text) is None
