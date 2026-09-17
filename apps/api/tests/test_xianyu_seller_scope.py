from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Conversation, Product, ProductKnowledge
from app.services import xianyu_sync


def conversation_item(cid: str, seller_id: str, peer_id: str, product_id: str, peer_name: str) -> dict:
    return {
        "singleChatUserConversation": {
            "redPoint": 1,
            "singleChatConversation": {
                "cid": cid,
                "pairFirst": seller_id,
                "pairSecond": peer_id,
                "extension": {"itemId": product_id},
            },
            "lastMessage": {
                "message": {
                    "extension": {
                        "senderUserId": peer_id,
                        "reminderTitle": peer_name,
                    }
                }
            },
        }
    }


def test_conversation_parser_reads_peer_name_from_last_message():
    parsed = xianyu_sync.parse_conversation(
        conversation_item("cid-name", "seller", "buyer", "A", "真实昵称"),
        "seller",
    )
    assert parsed and parsed["buyer_id"] == "buyer"
    assert parsed["buyer_nickname"] == "真实昵称"


def test_conversation_parser_reads_peer_avatar_from_extension():
    item = conversation_item("cid-avatar", "seller", "buyer", "A", "buyer")
    item["singleChatUserConversation"]["singleChatConversation"]["extension"][
        "buyerAvatar"
    ] = "//example.com/avatar.png"

    parsed = xianyu_sync.parse_conversation(item, "seller")

    assert parsed and parsed["buyer_avatar"] == "https://example.com/avatar.png"


def test_conversation_signature_changes_with_latest_message():
    first = conversation_item("cid-signature", "seller", "buyer", "A", "buyer")
    same = conversation_item("cid-signature", "seller", "buyer", "A", "buyer")
    changed = conversation_item("cid-signature", "seller", "buyer", "A", "buyer")
    changed["singleChatUserConversation"]["lastMessage"]["message"]["messageId"] = "new-message"
    parsed_first = xianyu_sync.parse_conversation(first, "seller")
    parsed_same = xianyu_sync.parse_conversation(same, "seller")
    parsed_changed = xianyu_sync.parse_conversation(changed, "seller")
    assert parsed_first and parsed_same and parsed_changed
    assert parsed_first["last_message_signature"] == parsed_same["last_message_signature"]
    assert parsed_first["last_message_signature"] != parsed_changed["last_message_signature"]


def test_product_card_extracts_only_available_platform_facts():
    parsed = xianyu_sync.parse_product_card(
        {
            "cardData": {
                "id": "ITEM-1",
                "title": "地址文件翻译",
                "description": "支持日本和马来西亚地区文件",
                "categoryName": "虚拟服务",
                "location": "线上交付",
                "priceInfo": {"price": "29.00"},
                "itemStatus": 0,
            }
        }
    )
    assert parsed
    assert parsed["description"] == "支持日本和马来西亚地区文件"
    assert parsed["category"] == "虚拟服务"
    assert parsed["shipping_origin"] == "线上交付"


async def test_synced_product_facts_are_isolated_and_idempotent(db):
    product = db.info["product_a"]
    other = db.info["product_b"]
    parsed = {
        "name": "商品 A 新标题",
        "price": 29,
        "status": "ACTIVE",
        "description": "仅支持当前商品的真实平台描述",
        "shipping_origin": "上海",
    }
    created, updated = await xianyu_sync.upsert_synced_product_knowledge(db, product, parsed)
    await db.commit()
    assert created == 5
    assert updated == 0

    created_again, updated_again = await xianyu_sync.upsert_synced_product_knowledge(
        db, product, parsed
    )
    await db.commit()
    assert created_again == 0
    assert updated_again == 0
    current_rows = (
        await db.scalars(
            select(ProductKnowledge).where(ProductKnowledge.product_id == product.id)
        )
    ).all()
    other_rows = (
        await db.scalars(
            select(ProductKnowledge).where(ProductKnowledge.product_id == other.id)
        )
    ).all()
    assert any("真实平台描述" in row.content for row in current_rows)
    assert not other_rows


async def test_complete_product_snapshot_disables_missing_synced_product(db):
    account = db.info["account"]
    present = db.info["product_a"]
    missing = db.info["product_b"]
    present.details = {"source": "xianyu_sync"}
    missing.details = {"source": "xianyu_sync", "description": "preserved"}
    missing.ai_enabled = True
    await db.commit()

    disabled, _ = await xianyu_sync.reconcile_missing_synced_products(
        db, account.id, {present.external_product_id}
    )
    await db.commit()

    assert disabled == 1
    assert present.status == "ACTIVE"
    assert missing.status == "DISABLED"
    assert not missing.ai_enabled
    assert missing.details["remote_missing"] is True
    assert missing.details["description"] == "preserved"


async def test_product_reconciliation_ignores_manual_products_and_is_idempotent(db):
    account = db.info["account"]
    synced = db.info["product_a"]
    manual = db.info["product_b"]
    synced.details = {"source": "xianyu_sync"}
    manual.details = {"source": "manual"}
    await db.commit()

    first, _ = await xianyu_sync.reconcile_missing_synced_products(db, account.id, set())
    second, _ = await xianyu_sync.reconcile_missing_synced_products(db, account.id, set())
    await db.commit()

    assert first == 1
    assert second == 0
    assert synced.status == "DISABLED"
    assert manual.status == "ACTIVE"


async def test_product_list_can_filter_unlisted_products(api_client, db):
    disabled = db.info["product_b"]
    disabled.status = "DISABLED"
    await db.commit()

    active_rows = (await api_client.get("/api/products?status=ACTIVE")).json()["items"]
    disabled_rows = (await api_client.get("/api/products?status=DISABLED")).json()["items"]

    assert all(row["status"] == "ACTIVE" for row in active_rows)
    assert [row["id"] for row in disabled_rows] == [disabled.id]


async def test_purchase_side_conversation_is_not_persisted(db, monkeypatch):
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    monkeypatch.setattr(xianyu_sync, "SessionLocal", maker)
    account = db.info["account"]
    own = db.info["product_a"]
    purchase = Product(
        account_id=account.id,
        external_product_id="PURCHASED-ITEM",
        name="我购买的商品",
        details={"source": "xianyu_conversation_sync", "auto_created": True},
    )
    db.add(purchase)
    await db.commit()

    result = await xianyu_sync.persist_conversations(
        account.id,
        "seller",
        [
            conversation_item("seller-cid", "seller", "buyer-1", own.external_product_id, "小明"),
            conversation_item("purchase-cid", "seller", "merchant-1", purchase.external_product_id, "卖家老王"),
        ],
        {},
        {"seller-cid": {"nickname": "小明", "avatar": "https://example.com/a.png"}},
    )

    assert result["conversations_created"] == 1
    assert result["purchase_conversations_skipped"] == 1
    seller = await db.scalar(
        select(Conversation).where(Conversation.external_conversation_id.endswith("seller-cid"))
    )
    purchase_side = await db.scalar(
        select(Conversation).where(Conversation.external_conversation_id.endswith("purchase-cid"))
    )
    assert seller and seller.buyer_nickname == "小明"
    assert seller.buyer_avatar == "https://example.com/a.png"
    assert seller.ai_enabled
    assert seller.status.value == "ACTIVE_AI"
    assert purchase_side is None
