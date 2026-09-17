"""User-initiated Xianyu web QR login for the experimental adapter.

This module never reads browser state and contains no CAPTCHA/slider automation.
If upstream requests additional verification, it stops and reports that state.
Adapted from dameng2026/xianyu-pilot (Apache-2.0), heavily simplified.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import random
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

import qrcode
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

APP_KEY = "34839810"
H5_API = "https://h5api.m.goofish.com/h5/mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get/1.0/"
LOGIN_PAGE = "https://passport.goofish.com/mini_login.htm"
QR_GENERATE = "https://passport.goofish.com/newlogin/qrcode/generate.do"
QR_QUERY = "https://passport.goofish.com/newlogin/qrcode/query.do"
TIMEOUT_SECONDS = 300
VERIFICATION_TIMEOUT_SECONDS = 900
MAX_SESSIONS = 32
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://passport.goofish.com/",
    "Origin": "https://passport.goofish.com",
}


@dataclass
class QRLoginSession:
    http: requests.Session
    login_form: dict[str, str]
    created_at: float = field(default_factory=time.time)
    status: str = "new"
    cookies: dict[str, str] | None = None
    verification_url: str | None = None
    verification_started_at: float | None = None
    credentials_claimed: bool = False
    persistence_result: dict | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class QRLoginService:
    def __init__(self) -> None:
        self._sessions: dict[str, QRLoginSession] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _http_session() -> requests.Session:
        http = requests.Session()
        http.trust_env = False
        retry = Retry(
            total=4,
            connect=4,
            read=0,
            status=0,
            backoff_factor=0.25,
            allowed_methods=frozenset({"GET", "POST"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        http.mount("https://", adapter)
        return http

    @staticmethod
    def _json(response: requests.Response, stage: str) -> dict:
        if response.status_code >= 400:
            raise RuntimeError(f"{stage}失败（HTTP {response.status_code}）")
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"{stage}返回了非 JSON 内容，可能触发平台验证") from exc

    @staticmethod
    def _prime(http: requests.Session) -> None:
        http.get(H5_API, headers=HEADERS, timeout=20)
        data = '{"bizScene":"home"}'
        now = str(int(time.time() * 1000))
        sign = hashlib.md5(f"&{now}&{APP_KEY}&{data}".encode()).hexdigest()
        form = {
            "jsv": "2.7.2", "appKey": APP_KEY, "t": now, "sign": sign,
            "v": "1.0", "type": "originaljson", "dataType": "json",
            "api": "mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get", "data": data,
        }
        http.post(H5_API, headers=HEADERS, data=form, timeout=20)
        token_cookie = http.cookies.get("_m_h5_tk")
        if not token_cookie:
            raise RuntimeError("闲鱼未下发登录令牌，可能需要稍后重试")
        token = token_cookie.split("_")[0]
        now = str(int(time.time() * 1000))
        form["t"] = now
        form["sign"] = hashlib.md5(f"{token}&{now}&{APP_KEY}&{data}".encode()).hexdigest()
        http.post(H5_API, headers=HEADERS, data=form, timeout=20)

    @staticmethod
    def _login_form(http: requests.Session) -> dict[str, str]:
        params = {
            "lang": "zh_cn", "appName": "xianyu", "appEntrance": "web",
            "styleType": "vertical", "bizParams": "", "notLoadSsoView": "false",
            "notKeepLogin": "false", "isMobile": "false", "qrCodeFirst": "false",
            "stie": "77", "rnd": str(random.random()),
        }
        response = http.get(LOGIN_PAGE, headers=HEADERS, params=params, timeout=20)
        match = re.search(r"(?:window\.viewData|var\s+viewData)\s*=\s*(\{.*?\});", response.text, re.DOTALL)
        if not match:
            raise RuntimeError("无法读取闲鱼扫码登录参数，可能触发平台验证")
        form = json.loads(match.group(1))["loginFormData"]
        form["umidTag"] = "SERVER"
        return form

    def start(self) -> dict[str, str | int]:
        self.cleanup()
        with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                raise RuntimeError("扫码登录会话已达上限，请稍后重试")
        http = self._http_session()
        try:
            self._prime(http)
            form = self._login_form(http)
            result = self._json(http.get(QR_GENERATE, headers=HEADERS, params=form, timeout=20), "生成二维码")
            data = result.get("content", {}).get("data") or {}
            content = data.get("codeContent")
            if not content:
                raise RuntimeError("闲鱼未返回二维码内容")
            form.update({"t": data.get("t", ""), "ck": data.get("ck", "")})
            image = qrcode.make(content)
            output = io.BytesIO()
            image.save(output, format="PNG")
            session_id = secrets.token_urlsafe(24)
            with self._lock:
                self._sessions[session_id] = QRLoginSession(http=http, login_form=form)
            return {
                "session_id": session_id,
                "qr_image": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode(),
                "expires_in": TIMEOUT_SECONDS,
            }
        except Exception:
            http.close()
            raise

    def poll(self, session_id: str) -> dict[str, str]:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return {"status": "expired"}
        now = time.time()
        deadline_start = session.verification_started_at or session.created_at
        deadline_seconds = (
            VERIFICATION_TIMEOUT_SECONDS
            if session.verification_started_at is not None
            else TIMEOUT_SECONDS
        )
        if now - deadline_start > deadline_seconds:
            return {"status": "expired"}
        with session.lock:
            if session.status == "confirmed":
                return {"status": "confirmed"}
            # Verification is completed on a separate platform page. That page
            # often has no callback URL and stays blank after success, so this
            # server-side QR session must keep querying instead of treating
            # verification_required as terminal.
            response = session.http.post(QR_QUERY, headers=HEADERS, data=session.login_form, timeout=20)
            data = self._json(response, "查询扫码状态").get("content", {}).get("data") or {}
            status = str(data.get("qrCodeStatus") or "").upper()
            if status == "CONFIRMED":
                if data.get("iframeRedirect"):
                    session.status = "verification_required"
                    redirect_url = str(data.get("iframeRedirectUrl") or "")
                    if session.verification_started_at is None:
                        session.verification_started_at = time.time()
                    if redirect_url:
                        # This URL can contain a one-time verification token.
                        # Never prefetch it from the API server: doing so may
                        # consume or bind the token before the operator opens
                        # it in the browser and completes face verification.
                        session.verification_url = redirect_url
                else:
                    session.status = "confirmed"
                    session.cookies = requests.utils.dict_from_cookiejar(session.http.cookies)
            elif status == "SCANED":
                session.status = "scanned"
            elif status in {"EXPIRED", "CANCELED", "CANCELLED"}:
                # Once the QR has handed the user off to face verification,
                # Passport may report the one-time QR itself as consumed/
                # expired.  That does not mean the verification token has
                # expired. Keep polling the same server-side session until it
                # is confirmed or our own five-minute deadline is reached.
                if session.status != "verification_required":
                    session.status = "expired"
            else:
                # Some responses return NEW again while secondary verification
                # is being finalized. Preserve the verification state so the UI
                # keeps showing useful instructions while polling continues.
                if session.status != "verification_required":
                    session.status = "new"
            result = {"status": session.status}
            if session.verification_url:
                result["verification_url"] = session.verification_url
            return result

    def consume_credentials(self, session_id: str) -> dict[str, str] | None:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session or session.status != "confirmed" or not session.cookies:
            return None
        with session.lock:
            if session.credentials_claimed:
                return None
            session.credentials_claimed = True
            return dict(session.cookies)

    def persistence_result(self, session_id: str) -> dict | None:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return None
        with session.lock:
            return dict(session.persistence_result) if session.persistence_result else None

    def finish_persistence(self, session_id: str, result: dict) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
        if session:
            with session.lock:
                session.persistence_result = dict(result)

    def cleanup(self) -> None:
        now = time.time()
        with self._lock:
            expired = [
                key
                for key, value in self._sessions.items()
                if now - (value.verification_started_at or value.created_at)
                > (
                    VERIFICATION_TIMEOUT_SECONDS
                    if value.verification_started_at is not None
                    else TIMEOUT_SECONDS
                )
            ]
            sessions = [self._sessions.pop(key) for key in expired]
        for session in sessions:
            session.http.close()


qr_login_service = QRLoginService()
