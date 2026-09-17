from fastapi import HTTPException

from app.api import accounts
from app.services.browser_login import BrowserLoginService, browser_login_service


def test_browser_login_pairing_token_is_required() -> None:
    service = BrowserLoginService()
    session_id, token, _ = service.start()

    assert service.authorize(session_id, token) is True
    assert service.authorize(session_id, "wrong-token") is False
    assert service.authorize("wrong-session", token) is False


def test_browser_login_status_does_not_expose_pairing_token() -> None:
    service = BrowserLoginService()
    session_id, token, profile_key = service.start()

    status = service.status(session_id)

    assert token not in str(status)
    assert profile_key not in str(status)
    assert status["status"] == "waiting_helper"


def test_browser_login_can_record_confirmation() -> None:
    service = BrowserLoginService()
    session_id, _, _ = service.start()
    service.update(session_id, "confirmed", "ok", {"account_id": "account-1"})

    assert service.status(session_id) == {
        "status": "confirmed",
        "message": "ok",
        "account_id": "account-1",
    }


def test_browser_login_reuses_server_selected_profile() -> None:
    service = BrowserLoginService()
    session_id, token, profile_key = service.start(
        profile_key="account-stable-profile",
        account_id="account-1",
    )

    assert profile_key == "account-stable-profile"
    assert service.context(session_id, token) == {
        "profile_key": "account-stable-profile",
        "account_id": "account-1",
    }
    assert service.context(session_id, "wrong-token") is None


async def test_expired_cookie_keeps_browser_login_session_open(api_client, monkeypatch) -> None:
    session_id, token, _ = browser_login_service.start(
        profile_key="account-stable-profile",
        account_id="account-1",
    )

    async def reject_expired_cookie(*_args, **_kwargs):
        raise HTTPException(422, "闲鱼登录 Cookie 校验失败：Session过期")

    monkeypatch.setattr(accounts, "_persist_experimental_account", reject_expired_cookie)
    response = await api_client.post(
        "/api/xianyu/browser-login/complete",
        json={
            "session_id": session_id,
            "pairing_token": token,
            "cookie_text": "unb=1; cookie2=stale; _m_h5_tk=stale",
        },
    )

    assert response.status_code == 422
    assert browser_login_service.status(session_id) == {
        "status": "browser_opened",
        "message": "正在刷新专用 Edge 中的登录态；若页面仍显示已登录，请稍候，只有平台要求时才需扫码",
    }
