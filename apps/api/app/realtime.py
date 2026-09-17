
from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, event: str, payload: dict) -> None:
        dead: list[WebSocket] = []
        for socket in self.connections:
            try:
                await socket.send_json({"event": event, "payload": payload})
            except Exception:
                dead.append(socket)
        for socket in dead:
            self.disconnect(socket)


ws_manager = WebSocketManager()
