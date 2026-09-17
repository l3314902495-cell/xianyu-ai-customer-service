"""Minimal experimental Xianyu web text protocol.

Adapted from fancyboi999/goofish-cli 0.3.0 (Apache-2.0). Only the
session/token/WebSocket text path is retained. There is deliberately no
browser-cookie extraction, Playwright, password login, or verification bypass.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import random
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests
import websockets
from websockets.asyncio.client import ClientConnection

APP_KEY = "34839810"
IM_APP_KEY = "444e9908a51d1cb236a27862abc769c9"
MTOP_HOST = "https://h5api.m.goofish.com"
WS_URL = "wss://wss-goofish.dingtalk.com/"
REFRESH_MH5TK_API = "mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get"
REFRESH_MH5TK_URL = f"{MTOP_HOST}/h5/{REFRESH_MH5TK_API}/1.0/"
UA_WEB = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)
UA_IM = UA_WEB + " DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) DingWeb/2.1.5 IMPaaS"


class XianyuFlowControlled(RuntimeError):
    """The platform temporarily rejected a read request because it was too frequent."""


@dataclass
class WebSession:
    http: requests.Session
    unb: str
    tracknick: str
    device_id: str
    im_token: str = ""
    im_token_at: float = 0

    @property
    def h5_token(self) -> str:
        value = cookie_value(self.http, "_m_h5_tk")
        return value.split("_")[0] if value else ""


def cookie_value(http: requests.Session, name: str) -> str:
    values = [cookie.value for cookie in http.cookies if cookie.name == name and cookie.value]
    return values[-1] if values else ""


def generate_device_id(user_id: str) -> str:
    return f"{uuid.uuid4()}-{user_id}"


def generate_mid() -> str:
    return f"{random.randrange(1000)}{int(time.time() * 1000)} 0"


def generate_message_uuid() -> str:
    return f"-{int(time.time() * 1000)}1"


def _headers() -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.goofish.com",
        "referer": "https://www.goofish.com/",
        "user-agent": UA_WEB,
    }


def mtop_call(session: WebSession, api: str, data: dict, version: str = "1.0") -> dict:
    if not session.h5_token:
        raise RuntimeError("登录态已失效：缺少 _m_h5_tk，请重新扫码")
    timestamp = str(int(time.time() * 1000))
    data_value = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    signature = hashlib.md5(
        f"{session.h5_token}&{timestamp}&{APP_KEY}&{data_value}".encode()
    ).hexdigest()
    params = {
        "jsv": "2.7.2", "appKey": APP_KEY, "t": timestamp, "sign": signature,
        "v": version, "type": "originaljson", "accountSite": "xianyu",
        "dataType": "json", "timeout": "20000", "api": api,
        "sessionOption": "AutoLoginOnly", "spm_cnt": "a21ybx.im.0.0",
    }
    response = session.http.post(
        f"{MTOP_HOST}/h5/{api}/{version}/",
        params=params,
        headers=_headers(),
        data={"data": data_value},
        timeout=30,
    )
    try:
        raw = response.json()
    except ValueError as exc:
        raise RuntimeError("闲鱼接口返回非 JSON 内容，可能要求人工验证") from exc
    ret = " | ".join(raw.get("ret") or [])
    if ret and "SUCCESS" not in ret:
        folded_ret = ret.casefold()
        if "flow_control" in folded_ret or "flow controlled" in folded_ret or "限流" in ret:
            raise XianyuFlowControlled("闲鱼暂时限制了同步频率，请等待约 60 秒后重试")
        if any(value in ret for value in ("RGV587", "USER_VALIDATE", "/punish", "哎哟喂")):
            raise RuntimeError(f"闲鱼风控已阻止连接：{ret}")
        if any(value in ret for value in ("SESSION_EXPIRED", "TOKEN_EXOIRED", "TOKEN_EMPTY", "ILLEGAL_ACCESS")):
            raise RuntimeError(f"闲鱼登录态失效或需要验证：{ret}")
        raise RuntimeError(f"闲鱼接口调用失败：{ret}")
    return raw


def refresh_m_h5_token(session: WebSession) -> bool:
    """Use MTOP's normal Set-Cookie renewal flow; never handles verification challenges."""
    original = session.http.cookies.get_dict()
    renewal = requests.Session()
    renewal.trust_env = False
    for name, value in original.items():
        renewal.cookies.set(name, value, domain=".goofish.com")
    old_value = cookie_value(renewal, "_m_h5_tk")
    data_value = json.dumps({"bizScene": "home"}, separators=(",", ":"))
    renewal.get(REFRESH_MH5TK_URL, headers=_headers(), timeout=15).raise_for_status()

    def post(token: str) -> requests.Response:
        timestamp = str(int(time.time() * 1000))
        signature = hashlib.md5(
            f"{token}&{timestamp}&{APP_KEY}&{data_value}".encode()
        ).hexdigest()
        body = {
            "jsv": "2.7.2", "appKey": APP_KEY, "t": timestamp, "sign": signature,
            "v": "1.0", "type": "originaljson", "dataType": "json", "timeout": "20000",
            "api": REFRESH_MH5TK_API, "data": data_value,
        }
        response = renewal.post(
            REFRESH_MH5TK_URL,
            data=urlencode(body),
            headers={**_headers(), "content-type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        response.raise_for_status()
        return response

    post("")
    new_value = cookie_value(renewal, "_m_h5_tk")
    if not new_value or new_value == old_value:
        renewal.close()
        return False
    post(new_value.split("_")[0])
    merged = {**original, **renewal.cookies.get_dict()}
    renewal.close()
    session.http.cookies.clear()
    session.http.cookies.update(merged)
    session.im_token = ""
    session.im_token_at = 0
    return True


def get_access_token(session: WebSession) -> str:
    if session.im_token and time.time() - session.im_token_at < 25 * 60:
        return session.im_token
    raw = mtop_call(
        session,
        "mtop.taobao.idlemessage.pc.login.token",
        {"appKey": IM_APP_KEY, "deviceId": session.device_id},
    )
    token = str((raw.get("data") or {}).get("accessToken") or "")
    if not token:
        raise RuntimeError("闲鱼没有返回长连接令牌，请重新扫码或稍后重试")
    session.im_token = token
    session.im_token_at = time.time()
    return token


def _cookie_header(session: WebSession) -> str:
    return "; ".join(f"{key}={value}" for key, value in session.http.cookies.get_dict().items())


@asynccontextmanager
async def connect(session: WebSession) -> AsyncIterator[ClientConnection]:
    async with websockets.connect(
        WS_URL,
        additional_headers={
            "Cookie": _cookie_header(session),
            "User-Agent": UA_WEB,
            "Origin": "https://www.goofish.com",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
        },
        # Protocol-level ping/pong detects half-open TCP connections even when
        # the application heartbeat task has silently stopped receiving data.
        ping_interval=20,
        ping_timeout=20,
        close_timeout=10,
        max_size=4 * 1024 * 1024,
    ) as websocket:
        yield websocket


async def register(websocket: ClientConnection, session: WebSession, token: str) -> None:
    await websocket.send(json.dumps({
        "lwp": "/reg",
        "headers": {
            "cache-header": "app-key token ua wv", "app-key": IM_APP_KEY,
            "token": token, "ua": UA_IM, "dt": "j", "wv": "im:3,au:3,sy:6",
            "sync": "0,0;0;0;", "did": session.device_id, "mid": generate_mid(),
        },
    }))
    now = int(time.time() * 1000)
    await websocket.send(json.dumps({
        "lwp": "/r/SyncStatus/ackDiff",
        "headers": {"mid": generate_mid()},
        "body": [{
            "pipeline": "sync", "tooLong2Tag": "PNM,1", "channel": "sync",
            "topic": "sync", "highPts": 0, "pts": now * 1000, "seq": 0, "timestamp": now,
        }],
    }))


async def heartbeat_loop(websocket: ClientConnection, interval: float = 15) -> None:
    while True:
        await websocket.send(json.dumps({"lwp": "/!", "headers": {"mid": generate_mid()}}))
        await asyncio.sleep(interval)


def build_ack(message: dict[str, Any]) -> dict[str, Any]:
    headers = message.get("headers") or {}
    ack_headers = {"mid": headers.get("mid") or generate_mid(), "sid": headers.get("sid", "")}
    for key in ("app-key", "ua", "dt"):
        if key in headers:
            ack_headers[key] = headers[key]
    return {"code": 200, "headers": ack_headers}


async def send_text(
    websocket: ClientConnection, *, myid: str, cid: str, toid: str, text: str
) -> str:
    mid = generate_mid()
    message_uuid = generate_message_uuid()
    payload = base64.b64encode(json.dumps({
        "contentType": 1, "text": {"text": text}
    }).encode()).decode()
    await websocket.send(json.dumps({
        "lwp": "/r/MessageSend/sendByReceiverScope",
        "headers": {"mid": mid},
        "body": [{
            "uuid": message_uuid, "cid": f"{cid}@goofish", "conversationType": 1,
            "content": {"contentType": 101, "custom": {"type": 1, "data": payload}},
            "redPointPolicy": 0, "extension": {"extJson": "{}"},
            "ctx": {"appVersion": "1.0", "platform": "web"}, "mtags": {},
            "msgReadStatusSetting": 1,
        }, {"actualReceivers": [f"{toid}@goofish", f"{myid}@goofish"]}],
    }))
    return message_uuid


async def send_image(
    websocket: ClientConnection, *, myid: str, cid: str, toid: str, image_url: str
) -> str:
    """Send an already-hosted public HTTPS image through the web message channel."""
    mid = generate_mid()
    message_uuid = generate_message_uuid()
    payload = base64.b64encode(json.dumps({
        "contentType": 2,
        "image": {
            "url": image_url,
            "pics": [{"height": 800, "type": 0, "url": image_url, "width": 800}],
        },
    }, ensure_ascii=False).encode()).decode()
    await websocket.send(json.dumps({
        "lwp": "/r/MessageSend/sendByReceiverScope",
        "headers": {"mid": mid},
        "body": [{
            "uuid": message_uuid, "cid": f"{cid}@goofish", "conversationType": 1,
            "content": {"contentType": 101, "custom": {"type": 1, "data": payload}},
            "redPointPolicy": 0, "extension": {"extJson": "{}"},
            "ctx": {"appVersion": "1.0", "platform": "web"}, "mtags": {},
            "msgReadStatusSetting": 1,
        }, {"actualReceivers": [f"{toid}@goofish", f"{myid}@goofish"]}],
    }))
    return message_uuid


def _decode_json_value(value: Any) -> Any:
    """Decode the JSON/base64 wrappers observed on the sync channel."""
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, (str, bytes)) or not value:
        return None
    raw = value.encode() if isinstance(value, str) else value
    for candidate in (raw,):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            pass
    try:
        return json.loads(base64.b64decode(raw))
    except Exception:
        return None


def extract_push_messages(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract message operations from both direct and wrapped sync frames.

    The web gateway has emitted several equivalent envelope layouts.  This
    walker is deliberately bounded and only returns dictionaries containing an
    operation, so response bodies cannot accidentally become buyer messages.
    """
    result: list[dict[str, Any]] = []
    seen: set[int] = set()

    def walk(value: Any, depth: int = 0) -> None:
        if depth > 7:
            return
        decoded = _decode_json_value(value)
        if decoded is not None and decoded is not value:
            walk(decoded, depth + 1)
            return
        if isinstance(value, list):
            for child in value[:100]:
                walk(child, depth + 1)
            return
        if not isinstance(value, dict) or id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value.get("operation"), dict) or extract_read_receipt(value):
            result.append(value)
            return
        for key in ("body", "syncPushPackage", "data", "payload", "message", "messages"):
            if key in value:
                walk(value[key], depth + 1)

    walk(message)
    return result


def extract_read_receipt(decoded: dict[str, Any]) -> dict[str, Any] | None:
    """Decode the flat read-receipt event emitted by Xianyu's sync channel."""
    message_ids = decoded.get("1")
    event_type = decoded.get("2")
    conversation_id = decoded.get("3")
    if (
        not isinstance(message_ids, list)
        or event_type not in {2, "2"}
        or not isinstance(conversation_id, str)
        or not conversation_id.endswith("@goofish")
    ):
        return None
    normalized_ids = [str(value).strip() for value in message_ids if str(value).strip()]
    if not normalized_ids:
        return None
    try:
        status = int(decoded.get("4"))
    except (TypeError, ValueError):
        return None
    if status not in {0, 1}:
        return None
    return {
        "cid": conversation_id.removesuffix("@goofish"),
        "message_ids": normalized_ids,
        "read": status == 1,
        "timestamp": str(decoded.get("5") or ""),
    }


def _text_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "content", "title", "message"):
            text = _text_value(value.get(key))
            if text:
                return text
    return ""


def _image_value(value: Any) -> str:
    """Normalize an image URL carried by a push without guessing a value."""
    if isinstance(value, dict):
        for key in ("url", "src", "avatar", "avatarUrl", "imageUrl"):
            image = _image_value(value.get(key))
            if image:
                return image
        return ""
    image = str(value or "").strip()
    if image.startswith("//"):
        return f"https:{image}"
    if image.startswith("http://"):
        return f"https://{image.removeprefix('http://')}"
    return image if image.startswith("https://") else ""


def extract_incoming_text(decoded: dict[str, Any]) -> dict[str, Any] | None:
    from app.services.xianyu_message_filter import is_platform_message_text

    operation = decoded.get("operation")
    if not isinstance(operation, dict):
        return None
    content = operation.get("content") or {}
    sender = operation.get("senderInfo") or {}
    reminder = content.get("reminder") or {}
    operation_extension = operation.get("extension") or {}
    session_info = operation.get("sessionInfo") or {}
    session_extension = session_info.get("extensions") or session_info.get("extension") or {}
    if isinstance(operation_extension, str):
        try:
            operation_extension = json.loads(operation_extension)
        except (TypeError, ValueError):
            operation_extension = {}
    if isinstance(session_extension, str):
        try:
            session_extension = json.loads(session_extension)
        except (TypeError, ValueError):
            session_extension = {}
    try:
        content_type = int(content.get("contentType") or 0)
    except (TypeError, ValueError):
        content_type = 0
    text = ""
    decoded_custom: dict[str, Any] = {}
    if content_type == 1:
        text = _text_value(content.get("text"))
    elif content_type == 101:
        try:
            decoded_custom = json.loads(
                base64.b64decode((content.get("custom") or {}).get("data", ""))
            )
            text = _text_value(
                decoded_custom.get("text") or decoded_custom.get("content")
            )
        except Exception:
            pass
    reminder_text = _text_value(reminder.get("reminderContent"))
    try:
        inner_content_type = int(decoded_custom.get("contentType") or 0)
    except (TypeError, ValueError):
        inner_content_type = 0
    sender_id = str(sender.get("senderUserId") or reminder.get("senderUserId") or "").strip()
    platform_sender = sender_id.casefold() in {"platform", "system", "xianyu"}
    platform_generated = bool(
        (not text and reminder_text)
        or (platform_sender and text and is_platform_message_text(text))
        or (content_type == 101 and inner_content_type not in {0, 1})
        or (
            content_type not in {1, 101}
            and reminder_text
        )
    )
    text = text or reminder_text
    if not text:
        return None
    result = {
        "event": "message", "cid": str(decoded.get("sessionId") or ""),
        "content_type": content_type,
        "send_user_id": sender_id,
        "send_user_name": str(reminder.get("reminderTitle") or ""), "send_message": text,
    }
    sender_avatar = _image_value(
        sender.get("avatar")
        or sender.get("avatarUrl")
        or sender.get("userAvatar")
        or sender.get("headUrl")
        or sender.get("logo")
        or reminder.get("senderAvatar")
        or reminder.get("avatar")
        or operation_extension.get("senderAvatar")
        or operation_extension.get("userAvatar")
        or session_extension.get("buyerAvatar")
        or session_extension.get("userAvatar")
    )
    if sender_avatar:
        result["send_user_avatar"] = sender_avatar
    if platform_generated:
        result["_platform_message"] = True
    return result


def extract_paid_order_event(decoded: dict[str, Any]) -> dict[str, str] | None:
    """Conservatively recognize a paid-order system event.

    A reminder alone is insufficient: the event must be content type 26, contain
    an explicit paid/waiting-for-shipment phrase, contain no unpaid phrase, and
    expose a stable order id plus product id. This prevents ordinary buyer text
    such as "我已付款" from triggering delivery.
    """
    operation = decoded.get("operation") or {}
    content = operation.get("content") or {}
    inner: dict[str, Any] = {}
    if content.get("contentType") == 101:
        try:
            inner = json.loads(base64.b64decode((content.get("custom") or {}).get("data", "")))
        except Exception:
            inner = {}
    effective = inner or content
    try:
        content_type = int(effective.get("contentType") or content.get("contentType") or 0)
    except (TypeError, ValueError):
        return None
    if content_type != 26:
        return None
    reminder = effective.get("reminder") or content.get("reminder") or {}
    reminder_text = str(reminder.get("reminderContent") or "")
    negative = ("待付款", "拍下待付", "等待买家付款", "未付款", "尚未付款")
    positive = ("等待你发货", "已付款", "付款成功", "支付成功", "已支付", "待发货")
    if any(word in reminder_text for word in negative) or not any(
        word in reminder_text for word in positive
    ):
        return None
    extensions = operation.get("extension") or operation.get("extensions") or {}
    if isinstance(extensions.get("extJson"), str):
        try:
            extensions = {**extensions, **json.loads(extensions["extJson"])}
        except (json.JSONDecodeError, TypeError):
            pass
    order_id = str(
        extensions.get("orderId") or extensions.get("tradeId") or operation.get("orderId") or ""
    ).strip()
    reminder_url = str(reminder.get("reminderUrl") or reminder.get("url") or "")
    if not order_id and reminder_url:
        query = parse_qs(urlparse(reminder_url).query)
        for key in ("orderId", "tradeId", "id"):
            if query.get(key):
                order_id = str(query[key][0]).strip()
                break
    session_info = operation.get("sessionInfo") or {}
    product_id = str(
        extensions.get("itemId")
        or session_info.get("itemId")
        or operation.get("itemId")
        or decoded.get("itemId")
        or ""
    ).strip()
    sender = operation.get("senderInfo") or {}
    buyer_id = str(sender.get("senderUserId") or reminder.get("senderUserId") or "").strip()
    if not order_id or not product_id or not buyer_id:
        return None
    return {
        "external_order_id": order_id,
        "external_product_id": product_id,
        "buyer_id": buyer_id,
        "conversation_id": str(decoded.get("sessionId") or ""),
        "reminder": reminder_text,
    }
