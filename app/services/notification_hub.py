"""WebSocket hub pour notifications temps réel."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket


class NotificationHub:
    def __init__(self) -> None:
        self._clients: Dict[int, Set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients[user_id].add(websocket)

    async def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            if user_id in self._clients and websocket in self._clients[user_id]:
                self._clients[user_id].remove(websocket)
            if user_id in self._clients and not self._clients[user_id]:
                del self._clients[user_id]

    async def push(self, user_id: int, payload: dict) -> None:
        async with self._lock:
            targets = list(self._clients.get(user_id, set()))
        stale = []
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            await self.disconnect(user_id, ws)


hub = NotificationHub()
