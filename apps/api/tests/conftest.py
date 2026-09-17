from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models import AIProviderConfig, Base, Conversation, Product, XianyuAccount
from app.security import current_user
from app.services.redis_runtime import redis_runtime


@pytest.fixture(autouse=True)
def isolate_redis_lock(monkeypatch):
    """Unit tests must not share an asyncio Redis connection across test loops."""

    async def acquire_lock(*_args, **_kwargs) -> str:
        return "unit-test-lock"

    async def release_lock(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(redis_runtime, "acquire_lock", acquire_lock)
    monkeypatch.setattr(redis_runtime, "release_lock", release_lock)


@pytest.fixture
async def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        account = XianyuAccount(nickname="测试账号", external_account_id="test-account", status="CONNECTED", ai_enabled=True)
        session.add(account); await session.flush()
        a = Product(account_id=account.id, external_product_id="A", name="商品A", price=100, ai_prompt="只说已知事实")
        b = Product(account_id=account.id, external_product_id="B", name="商品B", price=200, ai_prompt="只说已知事实")
        session.add_all([a,b]); await session.flush()
        c = Conversation(account_id=account.id, product_id=a.id, external_conversation_id="conv-a", buyer_id="buyer", buyer_nickname="买家")
        session.add_all([c, AIProviderConfig(provider="mock", model_name="mock-v1", enabled=True)])
        await session.commit()
        session.info.update({"account":account,"product_a":a,"product_b":b,"conversation":c})
        yield session
    await engine.dispose()


@pytest.fixture
async def api_client(db):
    async def override_db():
        yield db

    async def override_user():
        return SimpleNamespace(id="test-admin", role="admin")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = override_user
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value
    app.dependency_overrides.clear()
