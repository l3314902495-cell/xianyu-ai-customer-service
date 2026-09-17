import pytest
from sqlalchemy import select

from app.api import products as products_api
from app.models import Product, ProductPublishAttempt, XianyuAccountCredential
from app.services.xianyu_publish import PublishOutcomeUnknown


@pytest.mark.asyncio
async def test_real_publish_creates_local_product_and_is_idempotent(api_client, db, monkeypatch):
    account = db.info["account"]
    account.adapter_type = "experimental-web"
    account.status = "CONNECTED"
    db.add(
        XianyuAccountCredential(
            account_id=account.id,
            encrypted_payload="test-only-encrypted-payload",
        )
    )
    await db.commit()

    sentinel_session = object()

    def fake_session_from_credential(*_args):
        return sentinel_session

    async def fake_publish_product(**kwargs):
        assert kwargs["session"] is sentinel_session
        assert kwargs["title"] == "测试相机机身"
        assert len(kwargs["images"]) == 1
        return {
            "external_product_id": "REAL-ITEM-1001",
            "category": "数码相机",
            "image_url": "https://img.example/item.png",
        }

    monkeypatch.setattr(products_api, "session_from_credential", fake_session_from_credential)
    monkeypatch.setattr(products_api, "publish_product", fake_publish_product)
    form = {
        "account_id": account.id,
        "idempotency_key": "publish-request-00000001",
        "title": "测试相机机身",
        "description": "自用相机机身，功能正常，成色见图片。",
        "price": "1299",
        "delivery": "包邮",
        "can_self_pickup": "true",
    }
    files = {"images": ("camera.png", b"\x89PNG\r\n\x1a\n-test-image", "image/png")}

    response = await api_client.post("/api/products/publish", data=form, files=files)

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "PUBLISHED"
    assert payload["product"]["external_product_id"] == "REAL-ITEM-1001"
    product = await db.scalar(
        select(Product).where(Product.external_product_id == "REAL-ITEM-1001")
    )
    assert product is not None
    assert product.details["source"] == "xianyu_publish"
    attempt = await db.scalar(
        select(ProductPublishAttempt).where(
            ProductPublishAttempt.idempotency_key == form["idempotency_key"]
        )
    )
    assert attempt is not None and attempt.status == "PUBLISHED"

    duplicate = await api_client.post("/api/products/publish", data=form, files=files)
    assert duplicate.status_code == 201
    assert duplicate.json()["product"]["id"] == product.id


@pytest.mark.asyncio
async def test_real_publish_rejects_disguised_image(api_client, db):
    account = db.info["account"]
    account.adapter_type = "experimental-web"
    account.status = "CONNECTED"
    db.add(
        XianyuAccountCredential(
            account_id=account.id,
            encrypted_payload="test-only-encrypted-payload",
        )
    )
    await db.commit()
    response = await api_client.post(
        "/api/products/publish",
        data={
            "account_id": account.id,
            "idempotency_key": "publish-request-00000002",
            "title": "测试商品标题",
            "description": "这是至少十个字符的真实商品描述。",
            "price": "10",
        },
        files={"images": ("fake.png", b"not-an-image", "image/png")},
    )

    assert response.status_code == 422
    assert "文件内容不是有效的图片格式" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_publish_result_blocks_a_second_submission(
    api_client, db, monkeypatch
):
    account = db.info["account"]
    account.adapter_type = "experimental-web"
    account.status = "CONNECTED"
    db.add(
        XianyuAccountCredential(
            account_id=account.id,
            encrypted_payload="test-only-encrypted-payload",
        )
    )
    await db.commit()

    monkeypatch.setattr(products_api, "session_from_credential", lambda *_args: object())

    async def unknown_publish(**_kwargs):
        raise PublishOutcomeUnknown("发布结果需要人工确认")

    monkeypatch.setattr(products_api, "publish_product", unknown_publish)
    form = {
        "account_id": account.id,
        "idempotency_key": "publish-request-unknown-01",
        "title": "待确认测试商品",
        "description": "这是用于验证未知发布结果保护的商品描述。",
        "price": "20",
    }
    files = {"images": ("item.png", b"\x89PNG\r\n\x1a\n-test-image", "image/png")}

    first = await api_client.post("/api/products/publish", data=form, files=files)
    assert first.status_code == 409
    attempt = await db.scalar(
        select(ProductPublishAttempt).where(
            ProductPublishAttempt.idempotency_key == form["idempotency_key"]
        )
    )
    assert attempt is not None and attempt.status == "UNKNOWN"

    form["idempotency_key"] = "publish-request-unknown-02"
    second = await api_client.post("/api/products/publish", data=form, files=files)
    assert second.status_code == 409
    assert "结果待确认" in second.json()["detail"]
