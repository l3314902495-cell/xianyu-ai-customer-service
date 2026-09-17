from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from app.services.xianyu_bus import XianyuCommandConsumer, xianyu_bus
from app.services.xianyu_runtime import xianyu_runtime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def handle_command(action: str, account_id: str, payload: dict[str, Any]) -> Any:
    if action == "connect":
        await xianyu_runtime.start(account_id)
        connected = await xianyu_runtime.wait_connected(account_id, timeout=20)
        return {"connected": connected}
    if action == "disconnect":
        await xianyu_runtime.stop(account_id)
        return {"connected": False}
    if action == "sync":
        return await xianyu_runtime.sync_account_data(account_id)
    if action == "send_text":
        external_id = await xianyu_runtime.send(
            account_id,
            str(payload["conversation_id"]),
            str(payload["recipient_id"]),
            str(payload["content"]),
        )
        return {"external_message_id": external_id}
    if action == "send_image":
        external_id = await xianyu_runtime.send_image(
            account_id,
            str(payload["conversation_id"]),
            str(payload["recipient_id"]),
            str(payload["image_url"]),
        )
        return {"external_message_id": external_id}
    raise RuntimeError(f"Unsupported listener command: {action}")


async def listener_heartbeat() -> None:
    while True:
        await xianyu_bus.mark_listener_alive()
        await asyncio.sleep(10)


async def run() -> None:
    command_consumer = XianyuCommandConsumer(handle_command)
    await command_consumer.bus.ensure_groups()
    await xianyu_bus.mark_listener_alive()
    await xianyu_runtime.start_all()
    commands = asyncio.create_task(command_consumer.run(), name="xianyu-command-consumer")
    heartbeat = asyncio.create_task(listener_heartbeat(), name="xianyu-listener-heartbeat")
    logger.info("Xianyu listener service started")
    try:
        await asyncio.gather(commands, heartbeat)
    finally:
        for task in (commands, heartbeat):
            task.cancel()
        await asyncio.gather(commands, heartbeat, return_exceptions=True)
        with suppress(Exception):
            await xianyu_runtime.stop_all()


if __name__ == "__main__":
    asyncio.run(run())
