from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, DefaultDict, Dict, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket
else:
    WebSocket = Any


class ChannelWebSocketManager:
    def __init__(self) -> None:
        self._connections: DefaultDict[str, Set[WebSocket]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, channel_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[channel_id].add(websocket)

    def disconnect(self, channel_id: str, websocket: WebSocket) -> None:
        self._connections[channel_id].discard(websocket)
        if not self._connections[channel_id]:
            self._connections.pop(channel_id, None)

    async def _broadcast(self, channel_id: str, payload: Dict[str, Any]) -> None:
        stale: Set[WebSocket] = set()
        for websocket in self._connections.get(channel_id, set()):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.add(websocket)
        for websocket in stale:
            self.disconnect(channel_id, websocket)

    def publish(self, channel_id: str, payload: Dict[str, Any]) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._broadcast(channel_id, payload),
            self._loop,
        )
