from __future__ import annotations

import time

import requests

from app.services.xianyu_qr import QRLoginService, QRLoginSession


class FakeResponse:
    status_code = 200

    def __init__(self, data: dict, url: str = "") -> None:
        self._data = data
        self.url = url

    def json(self) -> dict:
        return {"content": {"data": self._data}}

    def raise_for_status(self) -> None:
        return None


class FakeHTTPSession:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = iter(responses)
        self.cookies = requests.cookies.RequestsCookieJar()
        self.verification_gets: list[str] = []

    def post(self, *_args, **_kwargs) -> FakeResponse:
        return FakeResponse(next(self.responses))

    def get(self, url: str, *_args, **_kwargs) -> FakeResponse:
        self.verification_gets.append(url)
        return FakeResponse({}, url=url + "/completed")


def make_service(responses: list[dict]) -> tuple[QRLoginService, str]:
    service = QRLoginService()
    session_id = "test-session"
    service._sessions[session_id] = QRLoginSession(  # noqa: SLF001
        http=FakeHTTPSession(responses),  # type: ignore[arg-type]
        login_form={"t": "t", "ck": "ck"},
    )
    return service, session_id


def test_consumed_qr_does_not_cancel_pending_face_verification() -> None:
    service, session_id = make_service(
        [
            {
                "qrCodeStatus": "CONFIRMED",
                "iframeRedirect": True,
                "iframeRedirectUrl": "https://passport.goofish.com/verify",
            },
            {"qrCodeStatus": "EXPIRED"},
            {"qrCodeStatus": "CONFIRMED", "iframeRedirect": False},
        ]
    )

    first = service.poll(session_id)
    assert first["status"] == "verification_required"
    assert first["verification_url"] == "https://passport.goofish.com/verify"
    assert service.poll(session_id)["status"] == "verification_required"
    assert service.poll(session_id)["status"] == "confirmed"
    http = service._sessions[session_id].http  # noqa: SLF001
    assert http.verification_gets == []  # type: ignore[attr-defined]


def test_unscanned_expired_qr_is_still_expired() -> None:
    service, session_id = make_service([{"qrCodeStatus": "EXPIRED"}])

    assert service.poll(session_id)["status"] == "expired"


def test_local_deadline_expires_verification_session() -> None:
    service, session_id = make_service([])
    session = service._sessions[session_id]  # noqa: SLF001
    session.status = "verification_required"
    session.verification_started_at = time.time() - 901

    assert service.poll(session_id)["status"] == "expired"


def test_face_verification_gets_its_own_extended_deadline() -> None:
    service, session_id = make_service([{"qrCodeStatus": "EXPIRED"}])
    session = service._sessions[session_id]  # noqa: SLF001
    session.status = "verification_required"
    session.created_at = time.time() - 600
    session.verification_started_at = time.time() - 60

    assert service.poll(session_id)["status"] == "verification_required"
