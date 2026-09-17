import asyncio
import json
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from urllib.parse import unquote

import requests
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.xianyu import adapter_for_account
from app.database import get_db
from app.models import (
    Conversation,
    Notification,
    Product,
    ProductPublishAttempt,
    User,
    XianyuAccount,
    XianyuAccountCredential,
)
from app.schemas import XianyuAccountCreate, XianyuAccountUpdate, XianyuCookieImport
from app.secrets import decrypt_secret, encrypt_secret
from app.security import current_user
from app.services.browser_login import browser_login_service
from app.services.xianyu_control import connect_account as connect_runtime_account
from app.services.xianyu_control import runtime_health
from app.services.xianyu_control import sync_account as sync_runtime_account
from app.services.xianyu_protocol import (
    WebSession,
    XianyuFlowControlled,
    generate_device_id,
    get_access_token,
)
from app.services.xianyu_qr import qr_login_service
from app.services.xianyu_runtime import XianyuPollFlowControlled
from app.time_utils import utc_iso

router = APIRouter(
    prefix="/api/xianyu/accounts",
    tags=["xianyu-accounts"],
    dependencies=[Depends(current_user)],
)
browser_router = APIRouter(prefix="/api/xianyu/browser-login", tags=["xianyu-browser-login"])


def _parse_cookie_text(value: str) -> dict[str, str]:
    raw = value.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()
    parsed = SimpleCookie()
    try:
        parsed.load(raw)
    except Exception:
        parsed = SimpleCookie()
    cookies = {key: morsel.value for key, morsel in parsed.items() if morsel.value}
    if not cookies:
        for part in raw.split(";"):
            key, separator, item = part.strip().partition("=")
            if separator and key and item:
                cookies[key] = item
    return cookies


async def _persist_experimental_account(
    cookies: dict[str, str],
    db: AsyncSession,
    *,
    profile_key: str | None = None,
    expected_account_id: str | None = None,
) -> XianyuAccount:
    unb = str(cookies.get("unb") or "").strip()
    required = [key for key in ("unb", "cookie2", "_m_h5_tk") if not cookies.get(key)]
    if required:
        raise HTTPException(422, f"Cookie 缺少必要字段：{', '.join(required)}")

    device_id = generate_device_id(unb)
    http = requests.Session()
    http.trust_env = False
    http.cookies.update(cookies)
    try:
        await asyncio.to_thread(
            get_access_token,
            WebSession(
                http=http,
                unb=unb,
                tracknick=unquote(str(cookies.get("tracknick") or "")),
                device_id=device_id,
            ),
        )
    except Exception as exc:
        raise HTTPException(422, f"闲鱼登录 Cookie 校验失败：{exc}") from None
    finally:
        http.close()

    account = await db.scalar(
        select(XianyuAccount).where(XianyuAccount.external_account_id == unb)
    )
    if expected_account_id and (not account or account.id != expected_account_id):
        raise HTTPException(409, "专用 Edge Profile 与当前闲鱼账号不匹配，请选择正确账号重试")
    nickname = unquote(str(cookies.get("tracknick") or "")).strip() or f"闲鱼账号 {unb[-4:]}"
    if not account:
        account = XianyuAccount(
            nickname=nickname,
            external_account_id=unb,
            adapter_type="experimental-web",
            status="CONNECTING",
            ai_enabled=True,
        )
        db.add(account)
        await db.flush()
    else:
        account.nickname = nickname
        account.adapter_type = "experimental-web"
        account.status = "CONNECTING"
        account.last_error = None

    credential = await db.scalar(
        select(XianyuAccountCredential).where(
            XianyuAccountCredential.account_id == account.id
        )
    )
    existing_payload: dict = {}
    if credential:
        try:
            existing_payload = json.loads(decrypt_secret(credential.encrypted_payload))
        except Exception:
            existing_payload = {}
    stable_profile_key = (
        profile_key
        or str(existing_payload.get("profile_key") or "").strip()
        or f"account-{account.id}"
    )
    payload = json.dumps(
        {
            "cookies": cookies,
            "device_id": str(existing_payload.get("device_id") or device_id),
            "profile_key": stable_profile_key,
        },
        ensure_ascii=False,
    )
    if credential:
        credential.encrypted_payload = encrypt_secret(payload)
        credential.last_verified_at = datetime.now(UTC)
    else:
        db.add(
            XianyuAccountCredential(
                account_id=account.id,
                encrypted_payload=encrypt_secret(payload),
                last_verified_at=datetime.now(UTC),
            )
        )
    await db.commit()
    await db.refresh(account)
    return account


async def account_dict(account: XianyuAccount, db: AsyncSession) -> dict:
    product_count = await db.scalar(
        select(func.count()).select_from(Product).where(Product.account_id == account.id)
    )
    conversation_count = await db.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.account_id == account.id)
    )
    has_credential = bool(
        await db.scalar(
            select(XianyuAccountCredential.id).where(
                XianyuAccountCredential.account_id == account.id
            )
        )
    )
    health = (
        await runtime_health(account.id)
        if account.adapter_type == "experimental-web"
        else {}
    )
    return {
        "id": account.id,
        "nickname": account.nickname,
        "external_account_id": account.external_account_id,
        "status": account.status,
        "adapter_type": account.adapter_type,
        "adapter_available": account.adapter_type in {"mock", "experimental-web"},
        "credential_configured": has_credential,
        "runtime_connected": bool(health.get("connected")),
        "listener_alive": bool(
            health.get("listener_alive", account.adapter_type == "mock")
        ),
        "connection_state": health.get("state"),
        "connection_health": health,
        "ai_enabled": account.ai_enabled,
        "last_connected_at": utc_iso(account.last_connected_at),
        "last_error": account.last_error,
        "product_count": product_count or 0,
        "conversation_count": conversation_count or 0,
        "created_at": utc_iso(account.created_at),
        "updated_at": utc_iso(account.updated_at),
    }


@router.get("")
async def list_accounts(db: AsyncSession = Depends(get_db)) -> list[dict]:
    accounts = (
        await db.scalars(select(XianyuAccount).order_by(XianyuAccount.created_at.asc()))
    ).all()
    return [await account_dict(account, db) for account in accounts]


@router.post("/experimental/browser-login/start")
async def start_browser_login(
    payload: dict | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    account_id = str((payload or {}).get("account_id") or "").strip() or None
    profile_key = None
    if account_id:
        account = await db.get(XianyuAccount, account_id)
        if not account:
            raise HTTPException(404, "闲鱼账号不存在")
        if account.adapter_type != "experimental-web":
            raise HTTPException(409, "只有专用 Edge 接入的真实账号可以恢复浏览器登录态")
        credential = await db.scalar(
            select(XianyuAccountCredential).where(
                XianyuAccountCredential.account_id == account.id
            )
        )
        if credential:
            try:
                credential_payload = json.loads(decrypt_secret(credential.encrypted_payload))
                profile_key = str(credential_payload.get("profile_key") or "").strip() or None
            except Exception:
                profile_key = None
        profile_key = profile_key or f"account-{account.id}"
    session_id, pairing_token, profile_key = browser_login_service.start(
        profile_key=profile_key,
        account_id=account_id,
    )
    return {
        "session_id": session_id,
        "pairing_token": pairing_token,
        "profile_key": profile_key,
        "helper_url": "http://127.0.0.1:8765/sessions",
        "expires_in": browser_login_service.ttl_seconds,
    }


@router.get("/experimental/browser-login/{session_id}")
async def browser_login_status(session_id: str) -> dict:
    return browser_login_service.status(session_id)


@browser_router.post("/complete")
async def complete_browser_login(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    session_id = str(payload.get("session_id") or "")
    token = str(payload.get("pairing_token") or "")
    login_context = browser_login_service.context(session_id, token)
    if not login_context:
        raise HTTPException(401, "登录配对凭据无效或已过期")
    cookies = _parse_cookie_text(str(payload.get("cookie_text") or ""))
    try:
        account = await _persist_experimental_account(
            cookies,
            db,
            profile_key=str(login_context["profile_key"]),
            expected_account_id=login_context.get("account_id"),
        )
        connected = await connect_runtime_account(account.id)
        result = {"connected": connected, "account_id": account.id}
        browser_login_service.update(session_id, "confirmed", "账号登录成功并已安全保存", result)
        return {"ok": True}
    except HTTPException as exc:
        if exc.status_code == 422:
            browser_login_service.update(
                session_id,
                "browser_opened",
                "正在刷新专用 Edge 中的登录态；若页面仍显示已登录，请稍候，只有平台要求时才需扫码",
            )
        else:
            browser_login_service.update(session_id, "failed", f"登录态校验失败：{exc.detail}")
        raise
    except Exception as exc:
        browser_login_service.update(session_id, "failed", f"登录态校验失败：{exc}")
        raise


@router.post("/experimental/qr/start")
async def start_experimental_qr() -> dict:
    try:
        return await asyncio.to_thread(qr_login_service.start)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from None


@router.post("/experimental/cookie", status_code=201)
async def import_experimental_cookie(
    body: XianyuCookieImport,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    cookies = _parse_cookie_text(body.cookie_text)
    account = await _persist_experimental_account(cookies, db)
    try:
        connected = await connect_runtime_account(account.id)
    except Exception as exc:
        connected = False
        account.status = "ERROR"
        account.last_error = str(exc)
        await db.commit()
    response = {
        "status": "confirmed",
        "connected": connected,
        "account": await account_dict(account, db),
        "operator": user.username,
    }
    return response


@router.get("/experimental/qr/{session_id}")
async def poll_experimental_qr(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        result = await asyncio.to_thread(qr_login_service.poll, session_id)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from None
    if result.get("status") != "confirmed":
        return result
    persisted = qr_login_service.persistence_result(session_id)
    if persisted:
        return persisted
    cookies = qr_login_service.consume_credentials(session_id)
    if not cookies:
        return {"status": "processing"}
    unb = str(cookies.get("unb") or "").strip()
    if not unb or not cookies.get("_m_h5_tk"):
        raise HTTPException(409, "登录凭据缺少必要字段，请重新扫码")
    account = await db.scalar(
        select(XianyuAccount).where(XianyuAccount.external_account_id == unb)
    )
    nickname = unquote(str(cookies.get("tracknick") or "")).strip() or f"闲鱼账号 {unb[-4:]}"
    if not account:
        account = XianyuAccount(
            nickname=nickname,
            external_account_id=unb,
            adapter_type="experimental-web",
            status="CONNECTING",
            ai_enabled=True,
        )
        db.add(account)
        await db.flush()
    else:
        account.nickname = nickname
        account.adapter_type = "experimental-web"
        account.status = "CONNECTING"
        account.last_error = None
    credential = await db.scalar(
        select(XianyuAccountCredential).where(
            XianyuAccountCredential.account_id == account.id
        )
    )
    existing_payload: dict = {}
    if credential:
        try:
            existing_payload = json.loads(decrypt_secret(credential.encrypted_payload))
        except Exception:
            existing_payload = {}
    payload = json.dumps(
        {
            "cookies": cookies,
            "device_id": str(existing_payload.get("device_id") or generate_device_id(unb)),
            "profile_key": str(existing_payload.get("profile_key") or f"account-{account.id}"),
        },
        ensure_ascii=False,
    )
    if credential:
        credential.encrypted_payload = encrypt_secret(payload)
        credential.last_verified_at = datetime.now(UTC)
    else:
        db.add(
            XianyuAccountCredential(
                account_id=account.id,
                encrypted_payload=encrypt_secret(payload),
                last_verified_at=datetime.now(UTC),
            )
        )
    await db.commit()
    await db.refresh(account)
    try:
        connected = await connect_runtime_account(account.id)
    except Exception as exc:
        connected = False
        account.status = "ERROR"
        account.last_error = str(exc)
        await db.commit()
    response = {
        "status": "confirmed",
        "connected": connected,
        "account": await account_dict(account, db),
        "operator": user.username,
    }
    qr_login_service.finish_persistence(session_id, response)
    return response


@router.post("", status_code=201)
async def create_account(body: XianyuAccountCreate, db: AsyncSession = Depends(get_db)) -> dict:
    account = XianyuAccount(
        nickname=body.nickname.strip(),
        external_account_id=body.external_account_id.strip(),
        adapter_type=body.adapter_type,
        status="DISCONNECTED",
        ai_enabled=body.ai_enabled,
    )
    db.add(account)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "该外部账号 ID 已存在") from None
    await db.refresh(account)
    return await account_dict(account, db)


@router.patch("/{account_id}")
async def update_account(
    account_id: str,
    body: XianyuAccountUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    account = await db.get(XianyuAccount, account_id)
    if not account:
        raise HTTPException(404, "闲鱼账号不存在")
    for key, value in body.model_dump(exclude_unset=True).items():
        if isinstance(value, str):
            value = value.strip()
        setattr(account, key, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "该外部账号 ID 已存在") from None
    await db.refresh(account)
    return await account_dict(account, db)


@router.post("/{account_id}/connect")
async def connect_account(account_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    account = await db.get(XianyuAccount, account_id)
    if not account:
        raise HTTPException(404, "闲鱼账号不存在")
    account.status = "CONNECTING"
    account.last_error = None
    await db.commit()
    try:
        connected = await adapter_for_account(account).connect()
        if not connected:
            raise RuntimeError("Adapter 未确认连接成功")
    except Exception as exc:
        account.status = "ERROR"
        account.last_error = str(exc)
        db.add(
            Notification(
                type="XIANYU_CONNECTION_ERROR",
                title=f"闲鱼账号连接失败：{account.nickname}",
                content=str(exc),
            )
        )
        await db.commit()
        raise HTTPException(409, str(exc)) from None
    account.status = "CONNECTED"
    account.last_connected_at = datetime.now(UTC)
    account.last_error = None
    await db.commit()
    await db.refresh(account)
    return await account_dict(account, db)


@router.post("/{account_id}/sync")
async def sync_account(account_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    account = await db.get(XianyuAccount, account_id)
    if not account:
        raise HTTPException(404, "闲鱼账号不存在")
    if account.adapter_type != "experimental-web":
        raise HTTPException(409, "只有真实网页版账号需要同步")
    try:
        result = await sync_runtime_account(account_id)
    except (XianyuFlowControlled, XianyuPollFlowControlled) as exc:
        account.last_error = "闲鱼临时限制了同步频率。现有商品和会话不会丢失，请等待约 60 秒后再同步。"
        await db.commit()
        raise HTTPException(
            429,
            account.last_error,
            headers={"Retry-After": "60"},
        ) from exc
    except Exception as exc:
        account.last_error = str(exc)
        await db.commit()
        raise HTTPException(502, f"同步失败：{exc}") from None
    account.last_error = None
    resolved_attempts = 0
    unknown_attempts = (
        await db.scalars(
            select(ProductPublishAttempt).where(
                ProductPublishAttempt.account_id == account_id,
                ProductPublishAttempt.status == "UNKNOWN",
            )
        )
    ).all()
    for attempt in unknown_attempts:
        candidates = (
            await db.scalars(
                select(Product).where(
                    Product.account_id == account_id,
                    Product.name == attempt.title,
                    Product.created_at >= attempt.created_at,
                )
            )
        ).all()
        if len(candidates) == 1:
            attempt.status = "PUBLISHED"
            attempt.product_id = candidates[0].id
            attempt.external_product_id = candidates[0].external_product_id
            attempt.error = None
            resolved_attempts += 1
    await db.commit()
    return {"ok": True, **result, "publish_attempts_resolved": resolved_attempts}


@router.post("/{account_id}/disconnect")
async def disconnect_account(account_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    account = await db.get(XianyuAccount, account_id)
    if not account:
        raise HTTPException(404, "闲鱼账号不存在")
    adapter = adapter_for_account(account)
    if adapter.available:
        await adapter.disconnect()
    account.status = "DISCONNECTED"
    account.last_error = None
    await db.commit()
    await db.refresh(account)
    return await account_dict(account, db)


@router.delete("/{account_id}")
async def delete_account(account_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    account = await db.get(XianyuAccount, account_id)
    if not account:
        raise HTTPException(404, "闲鱼账号不存在")
    dependent_count = await db.scalar(
        select(func.count()).select_from(Product).where(Product.account_id == account.id)
    )
    if dependent_count:
        raise HTTPException(409, "账号下仍有商品，请先迁移或删除商品")
    await db.delete(account)
    await db.commit()
    return {"ok": True}


@router.get("/integration/capabilities")
async def integration_capabilities() -> dict:
    return {
        "mock": {"available": True, "supports_multiple_accounts": True},
        "experimental-web": {
            "available": True,
            "supports_multiple_accounts": True,
            "scope": "用户主动扫码；仅文本消息收发；遇验证或风控立即停止",
            "official": False,
        },
        "real": {
            "available": False,
            "supports_multiple_accounts": True,
            "reason": "需要提供官方或已获授权的闲鱼接口资料后实现，系统不会编造私有协议。",
        },
    }
