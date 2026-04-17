"""WebSocket connection manager for real-time collaboration."""

import asyncio
import json
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

logger = logging.getLogger("smartsheet")


@dataclass
class ConnectedClient:
    websocket: WebSocket
    session_token: str
    user_id: str
    display_name: str
    color: str
    is_host: bool


class SyncManager:
    def __init__(self):
        self._clients: dict[str, ConnectedClient] = {}  # keyed by session_token
        self._cell_locks: dict[str, dict[tuple[int, int], str]] = {}  # sheet -> {(row,col): user_id}

    async def connect(self, websocket: WebSocket, session_token: str,
                      user_id: str, display_name: str, color: str, is_host: bool) -> ConnectedClient:
        await websocket.accept()

        client = ConnectedClient(
            websocket=websocket,
            session_token=session_token,
            user_id=user_id,
            display_name=display_name,
            color=color,
            is_host=is_host,
        )
        self._clients[session_token] = client

        # Broadcast user_join to all other clients
        await self.broadcast("user_join", {
            "user_id": user_id,
            "display_name": display_name,
            "color": color,
        }, exclude_token=session_token)

        # Send current presence list to the new client
        presence = self.get_presence()
        await self.send_to_client(session_token, "presence_list", {"users": presence})

        # Send current cell locks
        for sheet_name, locks in self._cell_locks.items():
            for (row, col), lock_user_id in locks.items():
                # Find the locker's info
                locker = self._find_client_by_user_id(lock_user_id)
                if locker:
                    await self.send_to_client(session_token, "cell_lock", {
                        "sheet": sheet_name,
                        "row": row,
                        "col": col,
                        "user_id": lock_user_id,
                        "color": locker.color,
                        "display_name": locker.display_name,
                    })

        logger.info(f"[WS] {display_name} connected ({len(self._clients)} total)")
        return client

    async def disconnect(self, session_token: str) -> None:
        client = self._clients.pop(session_token, None)
        if not client:
            return

        # Release all cell locks held by this user
        for sheet_name in list(self._cell_locks.keys()):
            locks = self._cell_locks[sheet_name]
            to_release = [(r, c) for (r, c), uid in locks.items() if uid == client.user_id]
            for r, c in to_release:
                del locks[r, c]
                await self.broadcast("cell_unlock", {
                    "sheet": sheet_name,
                    "row": r,
                    "col": c,
                    "user_id": client.user_id,
                })

        # Broadcast user_leave
        await self.broadcast("user_leave", {
            "user_id": client.user_id,
            "display_name": client.display_name,
        })

        logger.info(f"[WS] {client.display_name} disconnected ({len(self._clients)} total)")

    async def broadcast(self, event: str, data: dict, exclude_token: str | None = None) -> None:
        message = json.dumps({"event": event, "data": data})
        disconnected = []

        for token, client in self._clients.items():
            if token == exclude_token:
                continue
            try:
                await client.websocket.send_text(message)
            except Exception:
                disconnected.append(token)

        # Clean up disconnected clients
        for token in disconnected:
            self._clients.pop(token, None)

    async def send_to_host(self, event: str, data: dict) -> None:
        message = json.dumps({"event": event, "data": data})
        for client in self._clients.values():
            if client.is_host:
                try:
                    await client.websocket.send_text(message)
                except Exception:
                    pass

    async def send_to_client(self, session_token: str, event: str, data: dict) -> None:
        client = self._clients.get(session_token)
        if client:
            try:
                message = json.dumps({"event": event, "data": data})
                await client.websocket.send_text(message)
            except Exception:
                pass

    def lock_cell(self, sheet_name: str, row: int, col: int, user_id: str) -> bool:
        if sheet_name not in self._cell_locks:
            self._cell_locks[sheet_name] = {}

        locks = self._cell_locks[sheet_name]
        key = (row, col)

        existing = locks.get(key)
        if existing and existing != user_id:
            return False  # Locked by someone else

        locks[key] = user_id
        return True

    def unlock_cell(self, sheet_name: str, row: int, col: int, user_id: str) -> bool:
        locks = self._cell_locks.get(sheet_name, {})
        key = (row, col)

        if locks.get(key) == user_id:
            del locks[key]
            return True
        return False

    def get_locks(self, sheet_name: str) -> list[dict]:
        locks = self._cell_locks.get(sheet_name, {})
        result = []
        for (row, col), user_id in locks.items():
            client = self._find_client_by_user_id(user_id)
            result.append({
                "row": row,
                "col": col,
                "user_id": user_id,
                "color": client.color if client else "#999",
                "display_name": client.display_name if client else "Unknown",
            })
        return result

    def get_presence(self) -> list[dict]:
        return [
            {
                "user_id": c.user_id,
                "display_name": c.display_name,
                "color": c.color,
                "is_host": c.is_host,
            }
            for c in self._clients.values()
        ]

    async def force_disconnect(self, user_id: str) -> str | None:
        for token, client in list(self._clients.items()):
            if client.user_id == user_id:
                try:
                    await client.websocket.close(code=4001, reason="Disconnected by host")
                except Exception:
                    pass
                await self.disconnect(token)
                return token
        return None

    def _find_client_by_user_id(self, user_id: str) -> ConnectedClient | None:
        for client in self._clients.values():
            if client.user_id == user_id:
                return client
        return None

    @property
    def client_count(self) -> int:
        return len(self._clients)


_sync_manager: SyncManager | None = None


def get_sync_manager() -> SyncManager:
    global _sync_manager
    if _sync_manager is None:
        _sync_manager = SyncManager()
    return _sync_manager
