from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.services.xianyu_bus import xianyu_bus
from app.services.xianyu_runtime import xianyu_runtime


def listener_is_remote() -> bool:
    return get_settings().xianyu_runtime_mode == "api"


async def connect_account(account_id: str) -> bool:
    if listener_is_remote():
        result = await xianyu_bus.request("connect", account_id, timeout=35)
        return bool(result.get("connected"))
    await xianyu_runtime.start(account_id)
    return await xianyu_runtime.wait_connected(account_id, timeout=20)


async def disconnect_account(account_id: str) -> None:
    if listener_is_remote():
        await xianyu_bus.request("disconnect", account_id)
        return
    await xianyu_runtime.stop(account_id)


async def sync_account(account_id: str) -> dict[str, Any]:
    if listener_is_remote():
        return await xianyu_bus.request("sync", account_id, timeout=60)
    return await xianyu_runtime.sync_account_data(account_id)


async def send_text(
    account_id: str,
    conversation_id: str,
    recipient_id: str,
    content: str,
) -> str:
    if listener_is_remote():
        result = await xianyu_bus.request(
            "send_text",
            account_id,
            {
                "conversation_id": conversation_id,
                "recipient_id": recipient_id,
                "content": content,
            },
        )
        return str(result["external_message_id"])
    return await xianyu_runtime.send(account_id, conversation_id, recipient_id, content)


async def send_image(
    account_id: str,
    conversation_id: str,
    recipient_id: str,
    image_url: str,
) -> str:
    if listener_is_remote():
        result = await xianyu_bus.request(
            "send_image",
            account_id,
            {
                "conversation_id": conversation_id,
                "recipient_id": recipient_id,
                "image_url": image_url,
            },
        )
        return str(result["external_message_id"])
    return await xianyu_runtime.send_image(
        account_id,
        conversation_id,
        recipient_id,
        image_url,
    )


async def runtime_health(account_id: str) -> dict[str, Any]:
    if listener_is_remote():
        return await xianyu_bus.account_health(account_id)
    return {
        "listener_alive": True,
        "connected": xianyu_runtime.is_connected(account_id),
        "state": "connected" if xianyu_runtime.is_connected(account_id) else "disconnected",
    }
