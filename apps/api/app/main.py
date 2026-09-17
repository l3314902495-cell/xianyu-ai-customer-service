import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import accounts, ai, auth, auto_delivery, conversations, dev, operations, products
from app.config import get_settings
from app.database import SessionLocal
from app.models import SystemSetting, User
from app.realtime import ws_manager
from app.security import decode_token_subject
from app.services.auto_delivery import auto_delivery_reconciler
from app.services.global_ai_control import global_ai_control
from app.services.xianyu_bus import XianyuEventConsumer
from app.services.xianyu_events import handle_xianyu_event
from app.services.xianyu_runtime import xianyu_runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    event_task: asyncio.Task | None = None
    delivery_task = asyncio.create_task(
        auto_delivery_reconciler.run(), name="auto-delivery-reconciler"
    )
    async with SessionLocal() as db:
        switch = await db.get(SystemSetting, "global_ai_enabled")
        global_ai_control.set_enabled(True if not switch else bool(switch.value.get("enabled", True)))
    if settings.xianyu_runtime_mode == "api":
        event_task = asyncio.create_task(
            XianyuEventConsumer(handle_xianyu_event).run(),
            name="xianyu-event-consumer",
        )
    else:
        await xianyu_runtime.start_all()
    yield
    delivery_task.cancel()
    with suppress(asyncio.CancelledError):
        await delivery_task
    if event_task:
        event_task.cancel()
        with suppress(asyncio.CancelledError):
            await event_task
    else:
        await xianyu_runtime.stop_all()


app = FastAPI(title=get_settings().app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for router in [
    auth.router,
    accounts.browser_router,
    accounts.router,
    products.router,
    auto_delivery.router,
    conversations.router,
    ai.router,
    dev.router,
    operations.router,
]:
    app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "xianyu-ai-api"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    user_id = decode_token_subject(websocket.cookies.get("access_token", ""))
    if not user_id:
        await websocket.close(code=4401, reason="authentication required")
        return
    async with SessionLocal() as db:
        if not await db.get(User, user_id):
            await websocket.close(code=4401, reason="authentication required")
            return
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)
