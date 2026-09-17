"""Short-lived pairing state for the local, human-assisted Edge login helper."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field


@dataclass
class BrowserLoginSession:
    token: str
    profile_key: str
    account_id: str | None = None
    created_at: float = field(default_factory=time.time)
    status: str = "waiting_helper"
    message: str = "等待本机登录助手打开专用 Edge 窗口"
    result: dict | None = None


class BrowserLoginService:
    ttl_seconds = 15 * 60

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserLoginSession] = {}
        self._lock = threading.Lock()

    def start(
        self,
        *,
        profile_key: str | None = None,
        account_id: str | None = None,
    ) -> tuple[str, str, str]:
        self.cleanup()
        session_id = secrets.token_urlsafe(24)
        token = secrets.token_urlsafe(32)
        stable_profile_key = profile_key or f"profile-{secrets.token_urlsafe(18)}"
        with self._lock:
            self._sessions[session_id] = BrowserLoginSession(
                token=token,
                profile_key=stable_profile_key,
                account_id=account_id,
            )
        return session_id, token, stable_profile_key

    def status(self, session_id: str) -> dict:
        self.cleanup()
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return {"status": "expired", "message": "登录会话不存在或已过期"}
            payload = {"status": session.status, "message": session.message}
            if session.result:
                payload.update(session.result)
            return payload

    def authorize(self, session_id: str, token: str) -> bool:
        self.cleanup()
        with self._lock:
            session = self._sessions.get(session_id)
            return bool(session and secrets.compare_digest(session.token, token))

    def context(self, session_id: str, token: str) -> dict | None:
        """Return server-owned login context only after pairing-token validation."""
        self.cleanup()
        with self._lock:
            session = self._sessions.get(session_id)
            if not session or not secrets.compare_digest(session.token, token):
                return None
            return {
                "profile_key": session.profile_key,
                "account_id": session.account_id,
            }

    def update(self, session_id: str, status: str, message: str, result: dict | None = None) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.status = status
                session.message = message
                session.result = dict(result) if result else None

    def cleanup(self) -> None:
        now = time.time()
        with self._lock:
            expired = [key for key, value in self._sessions.items() if now - value.created_at > self.ttl_seconds]
            for key in expired:
                self._sessions.pop(key, None)


browser_login_service = BrowserLoginService()
