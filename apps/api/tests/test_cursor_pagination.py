from datetime import UTC, datetime

from app.models import Product


async def test_product_cursor_is_stable_when_timestamps_match(api_client, db):
    account = db.info["account"]
    timestamp = datetime(2026, 9, 17, 1, 2, 3, tzinfo=UTC).replace(tzinfo=None)
    rows = [
        Product(
            id=f"cursor-product-{index}",
            account_id=account.id,
            external_product_id=f"CURSOR-{index}",
            name=f"游标商品 {index}",
            price=index,
            updated_at=timestamp,
        )
        for index in range(3)
    ]
    db.add_all(rows)
    await db.commit()

    seen: list[str] = []
    cursor = ""
    while True:
        suffix = f"&cursor={cursor}" if cursor else ""
        response = await api_client.get(f"/api/products?limit=1{suffix}")
        assert response.status_code == 200
        page = response.json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break

    for row in rows:
        assert seen.count(row.id) == 1
    assert (await api_client.get("/api/products?cursor=not-a-cursor")).status_code == 422
