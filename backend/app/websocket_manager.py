"""
WebSocket Connection Manager — in-memory singleton registry.

Per Phase 1 Plan (Task T38):
  Holds active WebSocket connections indexed by session_id and heir_id.
  Exposes connect, disconnect, and broadcast helpers consumed by:
    - T37 (Session Lifecycle)
    - T11 (Asset Router)
    - T22 (WebSocket Server)
    - T42 (Support Request API)
    - T43 (Custom FAQ API)
    - T48 (Session Announcement UI)
"""

from fastapi import WebSocket
from typing import Dict, Set
import json
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Singleton WebSocket connection registry.

    Indexes connections by session_id → set of WebSocket objects,
    and by (session_id, heir_id) → WebSocket for private heir channels.
    """

    def __init__(self):
        # session_id -> set of WebSocket (Admin + Heir broadcast)
        self._session_connections: Dict[str, Set[WebSocket]] = {}
        # (session_id, heir_id) -> WebSocket (private heir channel)
        self._heir_connections: Dict[str, WebSocket] = {}

    async def connect(
        self, websocket: WebSocket, session_id: str, heir_id: str | None = None
    ):
        """Register a new WebSocket connection.

        Args:
            websocket: The accepted WebSocket connection.
            session_id: The session this connection belongs to.
            heir_id: Optional heir identifier for private channels.
        """
        await websocket.accept()

        if session_id not in self._session_connections:
            self._session_connections[session_id] = set()
        self._session_connections[session_id].add(websocket)

        if heir_id is not None:
            key = f"{session_id}:{heir_id}"
            self._heir_connections[key] = websocket

        logger.info(
            "WebSocket connected — session=%s heir=%s (session_count=%d)",
            session_id,
            heir_id,
            len(self._session_connections.get(session_id, set())),
        )

    def disconnect(self, websocket: WebSocket, session_id: str | None = None):
        """Remove a WebSocket connection from the registry.

        If session_id is not provided, scans all sessions to find and remove
        the websocket.
        """
        if session_id and session_id in self._session_connections:
            self._session_connections[session_id].discard(websocket)
            if not self._session_connections[session_id]:
                del self._session_connections[session_id]
        else:
            # Scan all sessions
            for sid in list(self._session_connections.keys()):
                self._session_connections[sid].discard(websocket)
                if not self._session_connections[sid]:
                    del self._session_connections[sid]

        # Remove from heir connections if present
        for key, ws in list(self._heir_connections.items()):
            if ws is websocket:
                del self._heir_connections[key]

        logger.info("WebSocket disconnected — session=%s", session_id)

    async def broadcast_session_status(
        self, session_id: str, payload: dict
    ):
        """Broadcast a session_status frame to all connections in a session."""
        frame = json.dumps(payload)
        dead: list[WebSocket] = []

        if session_id in self._session_connections:
            for ws in self._session_connections[session_id]:
                try:
                    await ws.send_text(frame)
                except Exception:
                    dead.append(ws)

        for ws in dead:
            self.disconnect(ws, session_id=session_id)

    async def broadcast_announcement(
        self, session_id: str, announcement: str | None, updated_at: str | None
    ):
        """Broadcast an announcement_updated frame to all connections in a session."""
        payload = {
            "type": "announcement_updated",
            "announcement": announcement,
            "announcement_updated_at": updated_at,
        }
        await self.broadcast_session_status(session_id, payload)

    async def broadcast_asset_ocr_completed(
        self, session_id: str, asset_data: dict
    ):
        """Broadcast an asset_ocr_completed frame to all connections in a session."""
        payload = {
            "type": "asset_ocr_completed",
            "asset": asset_data,
        }
        # Only broadcast to Admin connections — but since session connections
        # include all, we broadcast session-wide. Admins filter client-side.
        frame = json.dumps(payload)
        dead: list[WebSocket] = []

        if session_id in self._session_connections:
            for ws in self._session_connections[session_id]:
                try:
                    await ws.send_text(frame)
                except Exception:
                    dead.append(ws)

        for ws in dead:
            self.disconnect(ws, session_id=session_id)

    async def broadcast_support_alert(
        self, session_id: str, ticket_id: str, heir_name: str, message: str
    ):
        """Broadcast a support_alert frame to all Admin connections in a session."""
        import datetime
        payload = {
            "type": "support_alert",
            "ticket_id": ticket_id,
            "heir_name": heir_name,
            "message": message,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        await self.broadcast_session_status(session_id, payload)

    async def send_to_heir(
        self, session_id: str, heir_id: str, payload: dict
    ):
        """Send a frame to a specific heir's private channel."""
        key = f"{session_id}:{heir_id}"
        ws = self._heir_connections.get(key)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                self.disconnect(ws, session_id=session_id)

    def get_session_count(self, session_id: str) -> int:
        """Return the number of active connections in a session."""
        return len(self._session_connections.get(session_id, set()))

    def is_heir_connected(self, session_id: str, heir_id: str) -> bool:
        """Check if a specific heir has an active WebSocket connection."""
        key = f"{session_id}:{heir_id}"
        return key in self._heir_connections


# Singleton instance — imported by route modules
manager = ConnectionManager()