from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

import requests
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Conversation,
    Message,
    Notification,
    Product,
    SenderType,
    XianyuAccount,
    XianyuAccountCredential,
)
from app.realtime import ws_manager
from app.secrets import decrypt_secret, encrypt_secret
from app.services.xianyu_bus import utc_now_iso, xianyu_bus
from app.services.xianyu_polling import (
    XianyuPollFlowControlled,
    jittered_poll_delay,
    next_fallback_poll_delay,
    select_changed_conversation_items,
)
from app.services.xianyu_protocol import (
    WebSession,
    build_ack,
    connect,
    extract_incoming_text,
    extract_paid_order_event,
    extract_push_messages,
    extract_read_receipt,
    generate_device_id,
    generate_mid,
    get_access_token,
    heartbeat_loop,
    refresh_m_h5_token,
    register,
    send_image,
    send_text,
)

logger = logging.getLogger(__name__)

APPLICATION_STREAM_SILENCE_SECONDS = 10 * 60


@dataclass
class AccountConnection:
    account_id: str
    session: WebSession
    task: asyncio.Task | None = None
    ws: object | None = None
    connected: asyncio.Event = field(default_factory=asyncio.Event)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    request_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    sync_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: dict[str, asyncio.Future] = field(default_factory=dict)
    last_send_at: float = 0
    last_request_at: float = 0
    connected_at: float = 0
    last_frame_at: float = 0
    token_refresh_attempted: bool = False
    conversation_signatures: dict[str, str] = field(default_factory=dict)
    conversation_index_seeded: bool = False
    credential_last_verified_at: datetime | None = None


class XianyuRuntime:
    """Owns one isolated IM connection per experimental account."""

    def __init__(self) -> None:
        self._connections: dict[str, AccountConnection] = {}
        self._guard = asyncio.Lock()
        self._product_sync_locks: dict[str, asyncio.Lock] = {}
        self._last_product_sync: dict[str, float] = {}
        self._avatar_backfill_attempted_at: dict[str, float] = {}

    async def _load(self, account_id: str) -> AccountConnection:
        async with SessionLocal() as db:
            account = await db.get(XianyuAccount, account_id)
            credential = await db.scalar(
                select(XianyuAccountCredential).where(XianyuAccountCredential.account_id == account_id)
            )
            if not account or account.adapter_type != "experimental-web":
                raise RuntimeError("账号不是实验性网页版接入")
            if not credential:
                raise RuntimeError("账号没有扫码登录凭据，请重新扫码")
            try:
                payload = json.loads(decrypt_secret(credential.encrypted_payload))
                cookies = payload["cookies"]
                unb = str(cookies["unb"])
            except Exception as exc:
                raise RuntimeError("账号登录凭据无法解密，请重新扫码") from exc
        http = requests.Session()
        http.trust_env = False
        http.cookies.update(cookies)
        device_id = str(payload.get("device_id") or generate_device_id(unb))
        return AccountConnection(
            account_id=account_id,
            session=WebSession(
                http=http,
                unb=unb,
                tracknick=unquote(str(cookies.get("tracknick", ""))),
                device_id=device_id,
            ),
            credential_last_verified_at=credential.last_verified_at,
        )

    async def start(self, account_id: str) -> None:
        async with self._guard:
            existing = self._connections.get(account_id)
            if existing and existing.task and not existing.task.done():
                return
            connection = await self._load(account_id)
            if self._startup_refresh_due(connection):
                try:
                    refreshed = await asyncio.to_thread(
                        refresh_m_h5_token, connection.session
                    )
                    if refreshed:
                        await self._persist_credentials(connection)
                        connection.credential_last_verified_at = datetime.now(UTC).replace(
                            tzinfo=None
                        )
                        logger.info(
                            "Xianyu account %s credentials refreshed before startup",
                            account_id,
                        )
                except Exception as exc:
                    logger.warning(
                        "Xianyu account %s startup credential refresh failed: %s",
                        account_id,
                        type(exc).__name__,
                    )
            connection.task = asyncio.create_task(self._run(connection), name=f"xianyu-{account_id}")
            self._connections[account_id] = connection

    async def wait_connected(self, account_id: str, timeout: float = 20) -> bool:
        connection = self._connections.get(account_id)
        if not connection:
            return False
        try:
            await asyncio.wait_for(connection.connected.wait(), timeout)
            return True
        except TimeoutError:
            return False

    async def stop(self, account_id: str) -> None:
        async with self._guard:
            connection = self._connections.pop(account_id, None)
        if connection and connection.task:
            connection.task.cancel()
            with suppress(asyncio.CancelledError):
                await connection.task
            with suppress(Exception):
                await self._persist_credentials(connection)
            connection.session.http.close()

    async def start_all(self) -> None:
        async with SessionLocal() as db:
            ids = (
                await db.scalars(
                    select(XianyuAccount.id).where(
                        XianyuAccount.adapter_type == "experimental-web",
                        XianyuAccount.status.in_(["CONNECTED", "CONNECTING"]),
                    )
                )
            ).all()
        for account_id in ids:
            with suppress(Exception):
                await self.start(account_id)

    async def stop_all(self) -> None:
        for account_id in list(self._connections):
            await self.stop(account_id)

    def is_connected(self, account_id: str) -> bool:
        connection = self._connections.get(account_id)
        return bool(connection and connection.connected.is_set() and connection.ws)

    async def send(self, account_id: str, conversation_id: str, recipient_id: str, content: str) -> str:
        connection = self._connections.get(account_id)
        if not connection or not connection.ws or not connection.connected.is_set():
            raise RuntimeError("闲鱼账号长连接不在线")
        cid = conversation_id.removeprefix(f"web:{account_id}:")
        async with connection.send_lock:
            delay = 1.5 - (time.monotonic() - connection.last_send_at)
            if delay > 0:
                await asyncio.sleep(delay)
            mid = await send_text(
                connection.ws,
                myid=connection.session.unb,
                cid=cid,
                toid=recipient_id,
                text=content,
            )
            connection.last_send_at = time.monotonic()
            return mid

    async def send_image(
        self, account_id: str, conversation_id: str, recipient_id: str, image_url: str
    ) -> str:
        connection = self._connections.get(account_id)
        if not connection or not connection.ws or not connection.connected.is_set():
            raise RuntimeError("闲鱼账号长连接不在线")
        cid = conversation_id.removeprefix(f"web:{account_id}:")
        async with connection.send_lock:
            delay = 1.5 - (time.monotonic() - connection.last_send_at)
            if delay > 0:
                await asyncio.sleep(delay)
            mid = await send_image(
                connection.ws,
                myid=connection.session.unb,
                cid=cid,
                toid=recipient_id,
                image_url=image_url,
            )
            connection.last_send_at = time.monotonic()
            return mid

    async def _request(self, connection: AccountConnection, payload: dict, timeout: float = 12) -> dict:
        if not connection.ws or not connection.connected.is_set():
            raise RuntimeError("闲鱼账号长连接不在线")
        mid = generate_mid()
        payload.setdefault("headers", {})["mid"] = mid
        future = asyncio.get_running_loop().create_future()
        connection.pending[mid] = future
        try:
            async with connection.request_lock:
                delay = 0.5 - (time.monotonic() - connection.last_request_at)
                if delay > 0:
                    await asyncio.sleep(delay)
                await connection.ws.send(json.dumps(payload, ensure_ascii=False))
                connection.last_request_at = time.monotonic()
            return await asyncio.wait_for(future, timeout)
        finally:
            connection.pending.pop(mid, None)

    async def sync_account_data(self, account_id: str) -> dict[str, int | str]:
        connection = self._connections.get(account_id)
        if not connection or not connection.connected.is_set() or not connection.ws:
            await self.start(account_id)
            if not await self.wait_connected(account_id, timeout=20):
                raise RuntimeError("闲鱼账号尚未建立长连接，请重新连接后再同步")
            connection = self._connections[account_id]
        if connection.sync_lock.locked():
            raise RuntimeError("该账号正在同步，请等待当前任务完成后再试")
        async with connection.sync_lock:
            return await self._sync_account_data_locked(account_id, connection)

    async def _sync_account_data_locked(
        self, account_id: str, connection: AccountConnection
    ) -> dict[str, int | str]:
        from app.services.xianyu_sync import (
            fetch_conversation_user_info,
            parse_conversation,
            persist_conversations,
            sync_products,
        )

        result = await sync_products(account_id, connection.session)
        response = await self._request(connection, {
            "lwp": "/r/Conversation/listNewestPagination",
            "body": [9007199254740991, 50],
        })
        body = response.get("body") or {}
        items = body.get("userConvs") or [] if isinstance(body, dict) else []
        logger.info(
            "Xianyu conversation index account=%s code=%s body_type=%s body_keys=%s count=%s",
            account_id,
            response.get("code"),
            type(body).__name__,
            sorted(body.keys()) if isinstance(body, dict) else [],
            len(items),
        )
        if response.get("code") != 200:
            logger.warning(
                "Xianyu conversation index rejected account=%s reason=%s developer_message=%s",
                account_id,
                str(body.get("reason") or body.get("code") or "")[:200],
                str(body.get("developerMessage") or "")[:300],
            )
            reason = str(body.get("reason") or body.get("code") or "")
            if "flow control" in reason.casefold():
                result.update(
                    {
                        "conversations_created": 0,
                        "messages_created": 0,
                        "purchase_conversations_skipped": 0,
                        "conversation_sync_deferred": 1,
                        "warning": (
                            "商品已同步；闲鱼暂时限制批量会话历史读取。"
                            "现有会话不会丢失，实时新消息仍由长连接接收，系统稍后会低频补拉。"
                        ),
                    }
                )
                return result
            raise RuntimeError(f"闲鱼会话同步失败：{reason or response.get('code')}")
        histories: dict[str, list[dict]] = {}
        profiles: dict[str, dict[str, str]] = {}
        async with SessionLocal() as db:
            products = (
                await db.scalars(select(Product).where(Product.account_id == account_id))
            ).all()
            owned_ids = {
                product.external_product_id
                for product in products
                if not bool((product.details or {}).get("auto_created"))
                and (product.details or {}).get("source") != "xianyu_conversation_sync"
            }
            known_avatar_conversations = set(
                (
                    await db.scalars(
                        select(Conversation.external_conversation_id).where(
                            Conversation.account_id == account_id,
                            Conversation.buyer_avatar.is_not(None),
                            Conversation.buyer_avatar != "",
                        )
                    )
                ).all()
            )
        seller_items: list[dict] = []
        for item in items[:50]:
            parsed = parse_conversation(item, connection.session.unb)
            if not parsed or parsed["product_id"] not in owned_ids:
                continue
            seller_items.append(item)
            external_cid = f"web:{account_id}:{parsed['cid']}"
            needs_profile = (
                not parsed["buyer_avatar"]
                and external_cid not in known_avatar_conversations
                and len(profiles) < 6
            )
            if needs_profile:
                await asyncio.sleep(0.5)
                try:
                    profiles[parsed["cid"]] = await asyncio.to_thread(
                        fetch_conversation_user_info, connection.session, parsed["cid"]
                    )
                except Exception as exc:
                    logger.warning(
                        "Xianyu avatar lookup failed account=%s cid=%s error=%s detail=%s",
                        account_id,
                        parsed["cid"],
                        type(exc).__name__,
                        str(exc)[:200],
                    )
            # Persist the complete conversation index, but only fetch message
            # history for the most recent conversations. Re-reading 50 histories
            # and 50 profiles on every button click is what triggers flow control.
            if len(seller_items) > 12:
                continue
            message_response = await self._request(connection, {
                "lwp": "/r/MessageManager/listUserMessages",
                "body": [f"{parsed['cid']}@goofish", False, 9007199254740991, 20, False],
            })
            message_body = message_response.get("body") or {}
            histories[parsed["cid"]] = message_body.get("userMessageModels") or [] if isinstance(message_body, dict) else []
        purchase_conversations_skipped = len(items[:50]) - len(seller_items)
        persisted = await persist_conversations(
            account_id, connection.session.unb, seller_items, histories, profiles
        )
        for item in seller_items:
            parsed = parse_conversation(item, connection.session.unb)
            if parsed:
                connection.conversation_signatures[parsed["cid"]] = parsed[
                    "last_message_signature"
                ]
        persisted["purchase_conversations_skipped"] += purchase_conversations_skipped
        result.update(persisted)
        return result

    async def _run(self, connection: AccountConnection) -> None:
        backoff = 2.0
        try:
            while True:
                try:
                    token = await asyncio.to_thread(get_access_token, connection.session)
                    connection.token_refresh_attempted = False
                    async with connect(connection.session) as ws:
                        connection.ws = ws
                        await register(ws, connection.session, token)
                        connection.connected_at = time.monotonic()
                        connection.last_frame_at = connection.connected_at
                        connection.connected.set()
                        await self._set_status(connection.account_id, "CONNECTED")
                        await self._update_health(
                            connection.account_id,
                            connected=True,
                            state="connected",
                            connected_at=utc_now_iso(),
                            last_frame_at=utc_now_iso(),
                            reconnect_attempt=0,
                            last_error="",
                        )
                        heartbeat = asyncio.create_task(heartbeat_loop(ws))
                        renewal = asyncio.create_task(self._renewal_loop(connection))
                        maintenance = asyncio.create_task(
                            self._account_maintenance_loop(connection.account_id)
                        )
                        watchdog = asyncio.create_task(
                            self._connection_watchdog(connection, ws, heartbeat)
                        )
                        backoff = 2.0
                        try:
                            async for raw in ws:
                                connection.last_frame_at = time.monotonic()
                                try:
                                    frame = json.loads(raw)
                                except json.JSONDecodeError:
                                    continue
                                headers = frame.get("headers") or {}
                                mid = str(headers.get("mid") or "") if isinstance(headers, dict) else ""
                                pending = connection.pending.get(mid)
                                if pending and not pending.done():
                                    pending.set_result(frame)
                                    continue
                                with suppress(Exception):
                                    await ws.send(json.dumps(build_ack(frame)))
                                for decoded in extract_push_messages(frame):
                                    read_receipt = extract_read_receipt(decoded)
                                    if read_receipt:
                                        asyncio.create_task(
                                            self._receive_read_receipt(
                                                connection.account_id,
                                                read_receipt,
                                            )
                                        )
                                        continue
                                    paid_event = extract_paid_order_event(decoded)
                                    if paid_event:
                                        asyncio.create_task(
                                            self._handle_paid_event(connection.account_id, paid_event)
                                        )
                                    incoming = extract_incoming_text(decoded)
                                    if not incoming or not str(incoming.get("send_message") or "").strip():
                                        continue
                                    operation = decoded.get("operation") or {}
                                    message_id = str(
                                        operation.get("messageId")
                                        or operation.get("uuid")
                                        or decoded.get("messageId")
                                        or ""
                                    ).strip()
                                    external_message_id = (
                                        f"xianyu-history-{message_id}" if message_id else None
                                    )
                                    # Ignore our own WebSocket echo before platform-card
                                    # classification. Some seller messages are echoed in a
                                    # reminder-shaped envelope even though they are not system
                                    # notices.
                                    if str(incoming.get("send_user_id")) == connection.session.unb:
                                        if message_id:
                                            asyncio.create_task(
                                                self._receive_outbound_echo(
                                                    connection.account_id,
                                                    str(incoming.get("cid") or ""),
                                                    message_id,
                                                    str(operation.get("uuid") or ""),
                                                    str(incoming.get("send_message") or ""),
                                                )
                                            )
                                        continue
                                    if incoming.pop("_platform_message", False):
                                        asyncio.create_task(
                                            self._receive_system(
                                                connection.account_id,
                                                str(incoming.get("cid") or ""),
                                                external_message_id,
                                                str(incoming.get("send_message") or ""),
                                            )
                                        )
                                        continue
                                    item_id = self._item_id(decoded)
                                    asyncio.create_task(
                                        self._receive(
                                            connection.account_id,
                                            incoming,
                                            decoded,
                                            item_id,
                                            external_message_id=external_message_id,
                                        )
                                    )
                        finally:
                            for task in (heartbeat, renewal, maintenance, watchdog):
                                task.cancel()
                            await asyncio.gather(
                                heartbeat,
                                renewal,
                                maintenance,
                                watchdog,
                                return_exceptions=True,
                            )
                            connection.connected.clear()
                            connection.ws = None
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    connection.connected.clear()
                    connection.ws = None
                    message = str(exc)
                    logger.warning("Xianyu account %s disconnected: %s", connection.account_id, message)
                    await self._update_health(
                        connection.account_id,
                        connected=False,
                        state="reconnecting",
                        last_error=message[:500],
                    )
                    if not connection.token_refresh_attempted and self._is_refreshable_login_error(
                        message
                    ):
                        connection.token_refresh_attempted = True
                        try:
                            refreshed = await asyncio.to_thread(refresh_m_h5_token, connection.session)
                            if refreshed:
                                await self._persist_credentials(connection)
                                await self._set_status(connection.account_id, "CONNECTING")
                                backoff = 2.0
                                continue
                        except Exception as refresh_exc:
                            logger.warning(
                                "Xianyu account %s token renewal failed: %s",
                                connection.account_id,
                                type(refresh_exc).__name__,
                            )
                    if self._is_risk_error(message):
                        await self._set_status(connection.account_id, "ERROR", message, notify=True)
                        return
                    await self._set_status(connection.account_id, "CONNECTING", message)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
        finally:
            connection.connected.clear()
            connection.ws = None
            await self._update_health(
                connection.account_id,
                connected=False,
                state="stopped",
            )

    async def _connection_watchdog(
        self, connection: AccountConnection, websocket: object, heartbeat: asyncio.Task
    ) -> None:
        """Close stale registrations so the outer loop obtains a fresh token and reconnects."""
        while True:
            await asyncio.sleep(30)
            await self._update_health(
                connection.account_id,
                connected=connection.connected.is_set(),
                state="connected" if connection.connected.is_set() else "reconnecting",
                last_frame_age_seconds=max(
                    0, int(time.monotonic() - connection.last_frame_at)
                ),
                connection_age_seconds=max(
                    0, int(time.monotonic() - connection.connected_at)
                ),
            )
            # A quiet shop can legitimately receive no application frames for
            # several minutes. Transport ping/pong and heartbeat failures above
            # remain the fast half-open checks; this slower guard only refreshes
            # a registration that has been silent for an unusually long time.
            if (
                time.monotonic() - connection.last_frame_at
                >= APPLICATION_STREAM_SILENCE_SECONDS
            ):
                logger.warning(
                    "Xianyu application stream silent account=%s; reconnecting",
                    connection.account_id,
                )
                await websocket.close(code=1012, reason="application stream silent")
                return
            if heartbeat.done():
                with suppress(Exception):
                    heartbeat.exception()
                logger.warning(
                    "Xianyu heartbeat stopped account=%s; reconnecting",
                    connection.account_id,
                )
                await websocket.close(code=1012, reason="application heartbeat stopped")
                return
            # Refresh the IM registration periodically even if TCP ping/pong is
            # healthy. This prevents a stale server-side subscription from
            # looking connected forever.
            if time.monotonic() - connection.connected_at >= 45 * 60:
                logger.info(
                    "Xianyu scheduled connection refresh account=%s",
                    connection.account_id,
                )
                await websocket.close(code=1012, reason="scheduled registration refresh")
                return

    async def _handle_paid_event(self, account_id: str, event: dict[str, str]) -> None:
        """Bridge a verified system payment event into product-scoped fulfillment."""
        from app.services.auto_delivery import AutoDeliveryService

        try:
            async with SessionLocal() as db:
                product = await db.scalar(
                    select(Product).where(
                        Product.account_id == account_id,
                        Product.external_product_id == event["external_product_id"],
                    )
                )
                if not product:
                    return
                cid = event.get("conversation_id") or ""
                result = await AutoDeliveryService(db).handle_paid_order(
                    account_id=account_id,
                    product_id=product.id,
                    external_order_id=event["external_order_id"],
                    buyer_id=event["buyer_id"],
                    conversation_id=f"web:{account_id}:{cid}" if cid else None,
                    source="experimental-web",
                    raw_payload={"reminder": event.get("reminder", "")[:300]},
                )
                logger.info(
                    "Paid event handled account=%s product=%s status=%s",
                    account_id,
                    product.id,
                    result.get("status"),
                )
        except Exception:
            logger.exception("Paid event processing failed account=%s", account_id)

    async def _persist_credentials(self, connection: AccountConnection) -> None:
        cookies = connection.session.http.cookies.get_dict()
        payload = json.dumps(
            {"cookies": cookies, "device_id": connection.session.device_id},
            ensure_ascii=False,
        )
        async with SessionLocal() as db:
            credential = await db.scalar(
                select(XianyuAccountCredential).where(
                    XianyuAccountCredential.account_id == connection.account_id
                )
            )
            if not credential:
                raise RuntimeError("账号登录凭据不存在")
            credential.encrypted_payload = encrypt_secret(payload)
            credential.last_verified_at = datetime.now(UTC)
            await db.commit()

    @staticmethod
    def _startup_refresh_due(connection: AccountConnection) -> bool:
        verified_at = connection.credential_last_verified_at
        if verified_at is None:
            return True
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - verified_at >= timedelta(minutes=30)

    @staticmethod
    def _is_refreshable_login_error(message: str) -> bool:
        upper = message.upper()
        return any(
            marker in upper
            for marker in ("TOKEN_EXOIRED", "TOKEN_EXPIRED", "TOKEN_EMPTY", "SESSION_EXPIRED")
        )

    async def _renewal_loop(self, connection: AccountConnection) -> None:
        """Renew the short-lived MTOP signing token and persist rotated cookies."""
        while True:
            await asyncio.sleep(random.uniform(90 * 60, 150 * 60))
            try:
                if await asyncio.to_thread(refresh_m_h5_token, connection.session):
                    await self._persist_credentials(connection)
                    logger.info("Xianyu account %s credentials renewed", connection.account_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Xianyu account %s scheduled renewal failed: %s",
                    connection.account_id,
                    type(exc).__name__,
                )

    @staticmethod
    def _is_risk_error(message: str) -> bool:
        lowered = message.casefold()
        return any(
            word in lowered
            for word in (
                "captcha",
                "slider",
                "verify",
                "rgv",
                "风控",
                "验证",
                "401",
                "session_expired",
                "session过期",
            )
        )

    @staticmethod
    def _item_id(decoded: dict) -> str:
        operation = decoded.get("operation") or {}
        info = operation.get("sessionInfo") or {}
        extensions = info.get("extensions") or info.get("extension") or {}
        if isinstance(extensions, str):
            with suppress(json.JSONDecodeError, TypeError):
                extensions = json.loads(extensions)
        operation_extension = operation.get("extension") or {}
        if isinstance(operation_extension, str):
            with suppress(json.JSONDecodeError, TypeError):
                operation_extension = json.loads(operation_extension)
        return str(
            (extensions.get("itemId") if isinstance(extensions, dict) else "")
            or (operation_extension.get("itemId") if isinstance(operation_extension, dict) else "")
            or operation.get("itemId")
            or decoded.get("itemId")
            or ""
        )

    async def _account_maintenance_loop(self, account_id: str) -> None:
        """Bootstrap history, then recover any push messages missed by the gateway."""
        await asyncio.sleep(1)
        async with SessionLocal() as db:
            has_products = bool(await db.scalar(
                select(Product.id).where(Product.account_id == account_id).limit(1)
            ))
            has_conversations = bool(await db.scalar(
                select(Conversation.id).where(Conversation.account_id == account_id).limit(1)
            ))
        if not has_products or not has_conversations:
            try:
                result = await self.sync_account_data(account_id)
                logger.info("Initial Xianyu sync completed account=%s result=%s", account_id, result)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Initial Xianyu sync failed account=%s", account_id)
        # The long connection is the primary path. This adaptive history safety
        # net checks sooner after a recovered message, settles back to a quiet
        # cadence when idle, and adds jitter so multiple accounts do not probe
        # the platform in lockstep.
        poll_delay = 20.0
        while True:
            await asyncio.sleep(jittered_poll_delay(poll_delay))
            try:
                received = await self._poll_recent_messages(account_id)
                poll_delay = next_fallback_poll_delay(
                    poll_delay,
                    recovered=received,
                )
                if received:
                    logger.info(
                        "Xianyu realtime fallback recovered account=%s messages=%s",
                        account_id,
                        received,
                    )
                for attempt in range(3):
                    if not await self._backfill_one_avatar(account_id):
                        break
                    if attempt < 2:
                        await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except XianyuPollFlowControlled:
                poll_delay = next_fallback_poll_delay(
                    poll_delay,
                    flow_controlled=True,
                )
                logger.warning(
                    "Xianyu realtime fallback flow-controlled account=%s retry_in=%ss",
                    account_id,
                    int(poll_delay),
                )
            except Exception as exc:
                poll_delay = next_fallback_poll_delay(
                    poll_delay,
                    failed=True,
                )
                logger.warning(
                    "Xianyu realtime fallback failed account=%s error=%s detail=%s retry_in=%ss",
                    account_id,
                    type(exc).__name__,
                    str(exc)[:300],
                    int(poll_delay),
                )

    async def _backfill_one_avatar(self, account_id: str) -> bool:
        """Gradually fill missing public avatars without burst profile requests."""
        connection = self._connections.get(account_id)
        if not connection or not connection.connected.is_set() or connection.sync_lock.locked():
            return False
        now = time.monotonic()
        async with SessionLocal() as db:
            candidates = (
                await db.scalars(
                    select(Conversation)
                    .where(
                        Conversation.account_id == account_id,
                        (Conversation.buyer_avatar.is_(None))
                        | (Conversation.buyer_avatar == ""),
                        Conversation.external_conversation_id.like(f"web:{account_id}:%"),
                    )
                    .order_by(Conversation.updated_at.desc())
                    .limit(30)
                )
            ).all()
            conversation = next(
                (
                    row
                    for row in candidates
                    if now - self._avatar_backfill_attempted_at.get(row.id, 0) >= 3600
                ),
                None,
            )
            if not conversation:
                return False
            self._avatar_backfill_attempted_at[conversation.id] = now
            cid = conversation.external_conversation_id.rsplit(":", 1)[-1]
            try:
                from app.services.xianyu_sync import fetch_conversation_user_info

                profile = await asyncio.to_thread(
                    fetch_conversation_user_info, connection.session, cid
                )
            except Exception as exc:
                logger.warning(
                    "Xianyu gradual avatar backfill failed account=%s cid=%s error=%s detail=%s",
                    account_id,
                    cid,
                    type(exc).__name__,
                    str(exc)[:200],
                )
                return False
            avatar = str(profile.get("avatar") or "").strip()
            nickname = str(profile.get("nickname") or "").strip()
            if avatar:
                conversation.buyer_avatar = avatar
            if nickname and (
                not conversation.buyer_nickname
                or conversation.buyer_nickname.startswith("闲鱼用户 ")
            ):
                conversation.buyer_nickname = nickname
            if avatar or nickname:
                await db.commit()
                await self._deliver_event(
                    "conversation_profile",
                    {
                        "account_id": account_id,
                        "cid": cid,
                        "buyer_nickname": conversation.buyer_nickname,
                        "buyer_avatar": conversation.buyer_avatar,
                    },
                )
            return True

    async def _poll_recent_messages(self, account_id: str) -> int:
        """Poll only recent seller conversations as a conservative realtime fallback."""
        connection = self._connections.get(account_id)
        if not connection or not connection.connected.is_set() or not connection.ws:
            return 0
        if connection.sync_lock.locked():
            return 0
        async with connection.sync_lock:
            return await self._poll_recent_messages_locked(account_id, connection)

    async def _poll_recent_messages_locked(
        self, account_id: str, connection: AccountConnection
    ) -> int:
        from app.services.xianyu_sync import (
            decode_history_message,
            parse_conversation,
            persist_conversations,
        )

        # The index is a single lightweight request and tells us exactly which
        # conversations changed. Fetching history only for changed signatures
        # is both more reliable and less noisy than polling a DB top-three list.
        async with SessionLocal() as db:
            owned_product_ids = {
                product.external_product_id
                for product in (
                    await db.scalars(
                        select(Product).where(
                            Product.account_id == account_id,
                            Product.status == "ACTIVE",
                        )
                    )
                ).all()
                if not bool((product.details or {}).get("auto_created"))
                and (product.details or {}).get("source") != "xianyu_conversation_sync"
            }

        index_response = await self._request(
            connection,
            {
                "lwp": "/r/Conversation/listNewestPagination",
                "body": [9007199254740991, 50],
            },
            timeout=8,
        )
        index_body = index_response.get("body") or {}
        if index_response.get("code") != 200:
            reason = (
                str(index_body.get("reason") or index_body.get("code") or "")
                if isinstance(index_body, dict)
                else ""
            )
            if "flow control" in reason.casefold():
                raise XianyuPollFlowControlled(reason)
            raise RuntimeError(
                f"Xianyu conversation index failed: {reason or index_response.get('code')}"
            )
        index_items = (
            index_body.get("userConvs") or []
            if isinstance(index_body, dict)
            else []
        )
        parsed_items: list[tuple[dict, dict]] = []
        for raw_item in index_items[:50]:
            parsed = parse_conversation(raw_item, connection.session.unb)
            if not parsed or parsed["product_id"] not in owned_product_ids:
                continue
            parsed_items.append((raw_item, parsed))
        candidates = select_changed_conversation_items(
            parsed_items,
            connection.conversation_signatures,
            seeded=connection.conversation_index_seeded,
        )
        connection.conversation_index_seeded = True
        await self._update_health(
            account_id,
            last_index_poll_at=utc_now_iso(),
            indexed_conversations=len(parsed_items),
            changed_conversations=len(candidates),
        )

        recovered = 0
        for raw_item, parsed in candidates:
            cid = parsed["cid"]
            external_cid = f"web:{account_id}:{cid}"
            async with SessionLocal() as db:
                conversation = await db.scalar(
                    select(Conversation).where(
                        Conversation.external_conversation_id == external_cid
                    )
                )
            if not conversation:
                await persist_conversations(
                    account_id,
                    connection.session.unb,
                    [raw_item],
                    {},
                )
                async with SessionLocal() as db:
                    conversation = await db.scalar(
                        select(Conversation).where(
                            Conversation.external_conversation_id == external_cid
                        )
                    )
            if not conversation:
                continue
            message_response = await self._request(connection, {
                "lwp": "/r/MessageManager/listUserMessages",
                "body": [f"{cid}@goofish", False, 9007199254740991, 8, False],
            }, timeout=8)
            message_body = message_response.get("body") or {}
            if message_response.get("code") != 200:
                reason = (
                    str(message_body.get("reason") or message_body.get("code") or "")
                    if isinstance(message_body, dict)
                    else ""
                )
                if "flow control" in reason.casefold():
                    raise XianyuPollFlowControlled(reason)
                raise RuntimeError(
                    f"闲鱼活跃会话补拉失败：{reason or message_response.get('code')}"
                )
            models = (
                message_body.get("userMessageModels") or []
                if isinstance(message_body, dict)
                else []
            )
            decoded_messages = [
                decoded
                for model in models
                if (decoded := decode_history_message(model, connection.session.unb, cid))
            ]
            decoded_messages.sort(key=lambda value: value["created_at"])
            for message in decoded_messages:
                external_id = message["external_message_id"]
                async with SessionLocal() as db:
                    if await db.scalar(
                        select(Message.id).where(Message.external_message_id == external_id)
                    ):
                        continue
                if message["sender_type"] == SenderType.customer:
                    incoming = {
                        "cid": cid,
                        "send_user_id": conversation.buyer_id,
                        "send_user_name": message.get("sender_name") or conversation.buyer_nickname,
                        "send_message": message["content"],
                    }
                    await self._receive(
                        account_id,
                        incoming,
                        {"history_message_id": external_id},
                        parsed["product_id"],
                        external_message_id=external_id,
                    )
                    recovered += 1
                    continue
                if message["sender_type"] == SenderType.system:
                    await self._receive_system(
                        account_id,
                        cid,
                        external_id,
                        message["content"],
                        created_at=message["created_at"].isoformat(),
                    )
                    recovered += 1
                    continue
                async with SessionLocal() as db:
                    local_conversation = await db.scalar(
                        select(Conversation).where(
                            Conversation.external_conversation_id
                            == f"web:{account_id}:{cid}"
                        )
                    )
                    existing_outbound = (
                        await db.scalar(
                            select(Message)
                            .where(
                                Message.conversation_id == local_conversation.id,
                                Message.sender_type.in_([SenderType.ai, SenderType.human]),
                                Message.content == message["content"],
                                Message.created_at
                                >= message["created_at"] - timedelta(minutes=2),
                                Message.created_at
                                <= message["created_at"] + timedelta(minutes=2),
                            )
                            .order_by(Message.created_at.desc())
                        )
                        if local_conversation
                        else None
                    )
                    if existing_outbound:
                        if existing_outbound.external_message_id != external_id:
                            existing_outbound.external_message_id = external_id
                        if existing_outbound.platform_read_status is None:
                            existing_outbound.platform_read_status = False
                        await db.commit()
                        continue
                await self._receive_human(
                    account_id,
                    cid,
                    external_id,
                    message["content"],
                    created_at=message["created_at"].isoformat(),
                )
                recovered += 1
        return recovered

    async def _refresh_product_for_message(self, account_id: str) -> None:
        """Throttled seller-product refresh used when a live message references a new item."""
        now = time.monotonic()
        if now - self._last_product_sync.get(account_id, 0) < 30:
            return
        lock = self._product_sync_locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            if now - self._last_product_sync.get(account_id, 0) < 30:
                return
            connection = self._connections.get(account_id)
            if not connection or not connection.connected.is_set():
                return
            from app.services.xianyu_sync import sync_products

            await sync_products(account_id, connection.session)
            self._last_product_sync[account_id] = time.monotonic()

    async def _receive(
        self,
        account_id: str,
        incoming: dict,
        decoded: dict,
        item_id: str,
        external_message_id: str | None = None,
    ) -> None:
        cid = str(incoming.get("cid") or "")
        buyer_id = str(incoming.get("send_user_id") or "")
        if not cid or not buyer_id:
            return
        content = str(incoming.get("send_message") or "").strip()
        digest = hashlib.sha256(json.dumps(decoded, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if not content:
            return
        # A newly published seller item may be referenced by a push before the
        # product list has been refreshed. Refresh only that account and only
        # under the existing throttle before handing the event to the API.
        if item_id:
            async with SessionLocal() as db:
                product_exists = bool(
                    await db.scalar(
                        select(Product.id).where(
                            Product.account_id == account_id,
                            Product.external_product_id == item_id,
                        )
                    )
                )
            if not product_exists:
                with suppress(Exception):
                    await self._refresh_product_for_message(account_id)

        payload = {
            "account_id": account_id,
            "item_id": item_id,
            "incoming": incoming,
            "external_message_id": external_message_id or f"xianyu-{digest}",
        }
        await self._deliver_event("incoming_customer", payload)
        if not str(incoming.get("send_user_avatar") or "").strip():
            asyncio.create_task(self._lookup_profile_for_incoming(account_id, cid))
        await self._update_health(
            account_id,
            last_message_at=utc_now_iso(),
            last_message_id=payload["external_message_id"],
        )

    async def _lookup_profile_for_incoming(self, account_id: str, cid: str) -> None:
        """Fetch a missing profile after delivering the buyer message immediately."""
        connection = self._connections.get(account_id)
        if not connection or not connection.connected.is_set():
            return
        attempt_key = f"live:{account_id}:{cid}"
        now = time.monotonic()
        if now - self._avatar_backfill_attempted_at.get(attempt_key, 0) < 900:
            return
        self._avatar_backfill_attempted_at[attempt_key] = now
        try:
            from app.services.xianyu_sync import fetch_conversation_user_info

            profile = await asyncio.to_thread(
                fetch_conversation_user_info, connection.session, cid
            )
            nickname = str(profile.get("nickname") or "").strip()
            avatar = str(profile.get("avatar") or "").strip()
            if nickname or avatar:
                await self._deliver_event(
                    "conversation_profile",
                    {
                        "account_id": account_id,
                        "cid": cid,
                        "buyer_nickname": nickname,
                        "buyer_avatar": avatar,
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Xianyu realtime profile lookup failed account=%s cid=%s error=%s detail=%s",
                account_id,
                cid,
                type(exc).__name__,
                str(exc)[:200],
            )

    async def _receive_human(
        self,
        account_id: str,
        cid: str,
        external_message_id: str,
        content: str,
        created_at: str | None = None,
    ) -> None:
        await self._deliver_event(
            "human_message",
            {
                "account_id": account_id,
                "cid": cid,
                "external_message_id": external_message_id,
                "content": content,
                "created_at": created_at,
            },
        )

    async def _receive_read_receipt(
        self,
        account_id: str,
        receipt: dict[str, object],
    ) -> None:
        await self._deliver_event(
            "message_read",
            {
                "account_id": account_id,
                "cid": str(receipt.get("cid") or ""),
                "message_ids": list(receipt.get("message_ids") or []),
                "read": bool(receipt.get("read")),
                "timestamp": str(receipt.get("timestamp") or ""),
            },
        )

    async def _receive_outbound_echo(
        self,
        account_id: str,
        cid: str,
        platform_message_id: str,
        client_message_id: str,
        content: str,
    ) -> None:
        await self._deliver_event(
            "outbound_message_echo",
            {
                "account_id": account_id,
                "cid": cid,
                "platform_message_id": platform_message_id,
                "client_message_id": client_message_id,
                "content": content,
            },
        )

    async def _receive_system(
        self,
        account_id: str,
        cid: str,
        external_message_id: str | None,
        content: str,
        created_at: str | None = None,
    ) -> None:
        if not cid or not content.strip():
            return
        digest = hashlib.sha256(f"{account_id}:{cid}:{content}".encode()).hexdigest()
        await self._deliver_event(
            "system_message",
            {
                "account_id": account_id,
                "cid": cid,
                "external_message_id": external_message_id or f"xianyu-system-{digest}",
                "content": content,
                "created_at": created_at,
            },
        )

    async def _deliver_event(self, kind: str, payload: dict) -> None:
        if get_settings().xianyu_runtime_mode == "listener":
            try:
                await xianyu_bus.publish_event(kind, payload)
                return
            except Exception:
                # Redis is normally persistent and mandatory, but direct DB
                # processing is safer than dropping a buyer message entirely.
                logger.exception("Redis event publish failed; using direct fallback")
        from app.services.xianyu_events import handle_xianyu_event

        await handle_xianyu_event(kind, payload)

    async def _update_health(self, account_id: str, **values: object) -> None:
        if get_settings().xianyu_runtime_mode != "listener":
            return
        try:
            await xianyu_bus.update_account_health(account_id, **values)
        except Exception:
            logger.exception("Failed to update Xianyu account health account=%s", account_id)

    async def _set_status(self, account_id: str, status: str, error: str | None = None, notify: bool = False) -> None:
        async with SessionLocal() as db:
            account = await db.get(XianyuAccount, account_id)
            if not account:
                return
            account.status = status
            account.last_error = error
            if notify:
                db.add(Notification(
                    type="XIANYU_RISK_STOP",
                    title=f"闲鱼账号已因验证或风控停止：{account.nickname}",
                    content=error or "平台要求额外验证，请人工检查后重新扫码。",
                ))
            await db.commit()
        await ws_manager.broadcast("account_status", {"account_id": account_id, "status": status})
        await self._update_health(
            account_id,
            connected=status == "CONNECTED",
            state=status.casefold(),
            last_error=error or "",
        )


xianyu_runtime = XianyuRuntime()
