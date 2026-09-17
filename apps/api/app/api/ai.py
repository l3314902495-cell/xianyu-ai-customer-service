import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AIProviderConfig, Conversation, Product, PromptTemplate, XianyuAccount
from app.schemas import AITestRequest, GlobalPromptUpdate, ProviderUpdate
from app.secrets import decrypt_secret, encrypt_secret
from app.security import current_user
from app.services.ai_reply import AIReplyService
from app.services.llm import MockLLMProvider, OpenAICompatibleProvider
from app.services.prompt_builder import GLOBAL_SYSTEM_PROMPT

router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[Depends(current_user)])


def config_dict(c: AIProviderConfig) -> dict:
    secret = decrypt_secret(c.api_key_encrypted)
    masked = "" if not secret else f"{secret[:3]}***{secret[-3:]}"
    return {"id": c.id, "provider": c.provider, "base_url": c.base_url, "api_key_masked": masked, "model_name": c.model_name, "temperature": c.temperature, "max_tokens": c.max_tokens, "timeout": c.timeout, "enabled": c.enabled}


def validate_provider(body: ProviderUpdate, existing_key: str = "") -> tuple[str, str]:
    provider_name = body.provider.strip().lower()
    if provider_name not in {"mock", "openai", "deepseek", "openai-compatible"}:
        raise HTTPException(422, "Provider 仅支持 Mock、OpenAI、DeepSeek 或 OpenAI Compatible")
    base_url = body.base_url.strip().rstrip("/")
    if provider_name != "mock":
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise HTTPException(422, "Base URL 必须是有效的 HTTP(S) 地址，且不能包含账号密码")
        if not body.model_name.strip():
            raise HTTPException(422, "真实模型必须填写 Model Name")
        effective_key = "" if body.clear_api_key else body.api_key.strip() or existing_key
        if not effective_key:
            raise HTTPException(422, "真实模型必须填写 API Key")
    return provider_name, base_url


def provider_for(body: ProviderUpdate, existing_key: str = "") -> MockLLMProvider | OpenAICompatibleProvider:
    provider_name, base_url = validate_provider(body, existing_key)
    if provider_name == "mock":
        return MockLLMProvider()
    api_key = "" if body.clear_api_key else body.api_key.strip() or existing_key
    return OpenAICompatibleProvider(
        base_url,
        api_key,
        body.model_name.strip(),
        body.temperature,
        body.max_tokens,
        body.timeout,
        provider_name=provider_name,
    )


@router.get("/config")
async def get_config(db: AsyncSession = Depends(get_db)) -> dict:
    c = await db.scalar(select(AIProviderConfig).where(AIProviderConfig.enabled.is_(True)))
    if not c: raise HTTPException(404, "尚未配置模型")
    return config_dict(c)


@router.put("/config")
async def update_config(body: ProviderUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    c = await db.scalar(select(AIProviderConfig).where(AIProviderConfig.enabled.is_(True)))
    if not c: c = AIProviderConfig(); db.add(c)
    existing_key = decrypt_secret(c.api_key_encrypted)
    provider_name, base_url = validate_provider(body, existing_key)
    c.provider = provider_name; c.base_url = base_url; c.model_name = body.model_name.strip(); c.temperature = body.temperature; c.max_tokens = body.max_tokens; c.timeout = body.timeout
    if body.clear_api_key:
        c.api_key_encrypted = ""
    elif body.api_key.strip():
        c.api_key_encrypted = encrypt_secret(body.api_key.strip())
    await db.commit(); await db.refresh(c); return config_dict(c)


@router.post("/test-connection")
async def test_connection(body: ProviderUpdate | None = None, db: AsyncSession = Depends(get_db)) -> dict:
    c = await db.scalar(select(AIProviderConfig).where(AIProviderConfig.enabled.is_(True)))
    existing_key = decrypt_secret(c.api_key_encrypted) if c else ""
    if body:
        provider = provider_for(body, existing_key)
    elif not c or c.provider == "mock":
        provider = MockLLMProvider()
    else:
        provider = OpenAICompatibleProvider(c.base_url, existing_key, c.model_name, c.temperature, c.max_tokens, c.timeout, provider_name=c.provider)
    ok, message = await provider.test_connection()
    return {"success": ok, "message": message, "provider": provider.name, "model": provider.model}


@router.get("/global-prompt")
async def get_global_prompt(db: AsyncSession = Depends(get_db)) -> dict:
    prompt = await db.scalar(
        select(PromptTemplate)
        .where(PromptTemplate.type == "global", PromptTemplate.enabled.is_(True))
        .order_by(PromptTemplate.created_at.desc())
    )
    return {
        "content": prompt.content if prompt else GLOBAL_SYSTEM_PROMPT,
        "version": prompt.version if prompt else "global-v1",
        "is_default": prompt is None,
    }


@router.put("/global-prompt")
async def update_global_prompt(body: GlobalPromptUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    active = (
        await db.scalars(
            select(PromptTemplate).where(
                PromptTemplate.type == "global",
                PromptTemplate.enabled.is_(True),
            )
        )
    ).all()
    for item in active:
        item.enabled = False
    total = await db.scalar(
        select(func.count()).select_from(PromptTemplate).where(PromptTemplate.type == "global")
    )
    prompt = PromptTemplate(
        name="全局客服 Prompt",
        type="global",
        content=body.content.strip(),
        version=f"global-v{(total or 0) + 1}",
        enabled=True,
    )
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)
    return {"content": prompt.content, "version": prompt.version, "is_default": False}


@router.post("/test")
async def test_ai(body: AITestRequest, db: AsyncSession = Depends(get_db)) -> dict:
    product = await db.get(Product, body.product_id)
    if not product: raise HTTPException(404, "商品不存在")
    account = await db.get(XianyuAccount, product.account_id)
    if not account:
        raise HTTPException(409, "商品所属账号不存在")
    temp = Conversation(account_id=account.id, product_id=product.id, external_conversation_id=f"test-{uuid.uuid4()}", buyer_id="test", buyer_nickname="AI测试台")
    db.add(temp); await db.flush()
    try:
        try:
            result, meta = await AIReplyService(db).analyze(temp, body.message)
        except RuntimeError as exc:
            status = 504 if "超时" in str(exc) else 502
            raise HTTPException(status, f"AI 测试失败：{exc}") from None
        return {"decision": result.decision.model_dump(mode="json"), "raw_json": result.raw, "used": meta}
    finally:
        await db.rollback()
