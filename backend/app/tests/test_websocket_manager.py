"""
Tests for T38 — WebSocket Connection Manager.

Verifies:
- ConnectionManager is a singleton (manager instance accessible)
- connect() accepts WebSocket and registers it in session/heir indices
- disconnect() removes WebSocket from all indices
- broadcast_session_status() sends JSON payload to all session connections
- broadcast_announcement() sends announcement_updated frame
- broadcast_asset_ocr_completed() sends asset_ocr_completed frame
- send_to_heir() sends frame to a specific heir's private channel
- get_session_count() returns correct count
- is_heir_connected() returns correct boolean
- Disconnecting a dead WebSocket during broadcast is handled gracefully
"""

import json

import pytest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from app.websocket_manager import ConnectionManager, manager


@pytest.fixture
def fresh_manager():
    """Return a fresh ConnectionManager instance for isolated testing."""
    return ConnectionManager()


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket with async accept and send_text."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


class TestSingleton:
    """T38: Verify the module-level singleton is available."""

    def test_manager_is_connection_manager(self):
        """manager is a ConnectionManager instance."""
        assert isinstance(manager, ConnectionManager)

    def test_manager_is_same_instance_on_reimport(self):
        """Re-importing gives the same singleton."""
        from app.websocket_manager import manager as manager2
        assert manager is manager2


class TestConnect:
    """T38: Verify connect() registers connections."""

    @pytest.mark.asyncio
    async def test_connect_registers_session(self, fresh_manager, mock_websocket):
        await fresh_manager.connect(mock_websocket, "session-1")
        assert fresh_manager.get_session_count("session-1") == 1
        mock_websocket.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_registers_heir(self, fresh_manager, mock_websocket):
        await fresh_manager.connect(mock_websocket, "session-1", heir_id="heir-A")
        assert fresh_manager.is_heir_connected("session-1", "heir-A") is True

    @pytest.mark.asyncio
    async def test_connect_multiple_to_same_session(self, fresh_manager):
        ws1 = MagicMock()
        ws1.accept = AsyncMock()
        ws2 = MagicMock()
        ws2.accept = AsyncMock()

        await fresh_manager.connect(ws1, "session-1")
        await fresh_manager.connect(ws2, "session-1")
        assert fresh_manager.get_session_count("session-1") == 2


class TestDisconnect:
    """T38: Verify disconnect() removes connections."""

    @pytest.mark.asyncio
    async def test_disconnect_removes_from_session(self, fresh_manager, mock_websocket):
        await fresh_manager.connect(mock_websocket, "session-1")
        fresh_manager.disconnect(mock_websocket, session_id="session-1")
        assert fresh_manager.get_session_count("session-1") == 0

    @pytest.mark.asyncio
    async def test_disconnect_removes_heir(self, fresh_manager, mock_websocket):
        await fresh_manager.connect(mock_websocket, "session-1", heir_id="heir-A")
        fresh_manager.disconnect(mock_websocket, session_id="session-1")
        assert fresh_manager.is_heir_connected("session-1", "heir-A") is False

    @pytest.mark.asyncio
    async def test_disconnect_without_session_id_scans_all(self, fresh_manager):
        ws = MagicMock()
        ws.accept = AsyncMock()
        await fresh_manager.connect(ws, "session-1")
        fresh_manager.disconnect(ws)
        assert fresh_manager.get_session_count("session-1") == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown_session_noop(self, fresh_manager, mock_websocket):
        # Should not raise
        fresh_manager.disconnect(mock_websocket, session_id="no-such-session")


class TestBroadcastSessionStatus:
    """T38: Verify broadcast_session_status sends to all session connections."""

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self, fresh_manager):
        ws1 = MagicMock()
        ws1.accept = AsyncMock()
        ws1.send_text = AsyncMock()
        ws2 = MagicMock()
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()

        await fresh_manager.connect(ws1, "session-1")
        await fresh_manager.connect(ws2, "session-1")

        payload = {"type": "session_status", "status": "ACTIVE"}
        await fresh_manager.broadcast_session_status("session-1", payload)

        expected_frame = json.dumps(payload)
        ws1.send_text.assert_awaited_once_with(expected_frame)
        ws2.send_text.assert_awaited_once_with(expected_frame)

    @pytest.mark.asyncio
    async def test_broadcast_empty_session_noop(self, fresh_manager):
        # Should not raise
        await fresh_manager.broadcast_session_status(
            "no-session", {"type": "session_status"}
        )

    @pytest.mark.asyncio
    async def test_broadcast_handles_dead_connection(self, fresh_manager):
        ws_dead = MagicMock()
        ws_dead.accept = AsyncMock()
        ws_dead.send_text = AsyncMock(side_effect=Exception("Connection lost"))

        ws_alive = MagicMock()
        ws_alive.accept = AsyncMock()
        ws_alive.send_text = AsyncMock()

        await fresh_manager.connect(ws_dead, "session-1")
        await fresh_manager.connect(ws_alive, "session-1")

        payload = {"type": "session_status", "status": "LOCKED"}
        await fresh_manager.broadcast_session_status("session-1", payload)

        # Dead connection should be removed
        assert fresh_manager.get_session_count("session-1") == 1
        # Alive connection should still receive the broadcast
        expected_frame = json.dumps(payload)
        ws_alive.send_text.assert_awaited_once_with(expected_frame)


class TestBroadcastAnnouncement:
    """T38: Verify broadcast_announcement sends announcement_updated frame."""

    @pytest.mark.asyncio
    async def test_announcement_frame_format(self, fresh_manager, mock_websocket):
        mock_websocket.send_text = AsyncMock()
        await fresh_manager.connect(mock_websocket, "session-1")

        await fresh_manager.broadcast_announcement(
            "session-1",
            "Important notice",
            "2026-06-10T20:00:00Z",
        )

        frame = json.loads(mock_websocket.send_text.call_args[0][0])
        assert frame["type"] == "announcement_updated"
        assert frame["announcement"] == "Important notice"
        assert frame["announcement_updated_at"] == "2026-06-10T20:00:00Z"

    @pytest.mark.asyncio
    async def test_announcement_null_is_sent(self, fresh_manager, mock_websocket):
        mock_websocket.send_text = AsyncMock()
        await fresh_manager.connect(mock_websocket, "session-1")

        await fresh_manager.broadcast_announcement("session-1", None, None)

        frame = json.loads(mock_websocket.send_text.call_args[0][0])
        assert frame["announcement"] is None
        assert frame["announcement_updated_at"] is None


class TestBroadcastAssetOCR:
    """T38: Verify broadcast_asset_ocr_completed sends asset_ocr_completed frame."""

    @pytest.mark.asyncio
    async def test_asset_ocr_frame_format(self, fresh_manager, mock_websocket):
        mock_websocket.send_text = AsyncMock()
        await fresh_manager.connect(mock_websocket, "session-1")

        asset_data = {"id": "uuid-1", "title": "Vase", "status": "STAGED"}
        await fresh_manager.broadcast_asset_ocr_completed("session-1", asset_data)

        frame = json.loads(mock_websocket.send_text.call_args[0][0])
        assert frame["type"] == "asset_ocr_completed"
        assert frame["asset"] == asset_data


class TestSendToHeir:
    """T38: Verify send_to_heir sends to a specific heir."""

    @pytest.mark.asyncio
    async def test_send_to_heir_delivers_to_correct_heir(self, fresh_manager):
        ws_heir_a = MagicMock()
        ws_heir_a.accept = AsyncMock()
        ws_heir_a.send_text = AsyncMock()

        ws_heir_b = MagicMock()
        ws_heir_b.accept = AsyncMock()
        ws_heir_b.send_text = AsyncMock()

        await fresh_manager.connect(ws_heir_a, "session-1", heir_id="heir-A")
        await fresh_manager.connect(ws_heir_b, "session-1", heir_id="heir-B")

        payload = {"type": "private_message", "text": "Hello"}
        await fresh_manager.send_to_heir("session-1", "heir-A", payload)

        ws_heir_a.send_text.assert_awaited_once_with(json.dumps(payload))
        ws_heir_b.send_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_to_heir_unknown_heir_noop(self, fresh_manager):
        # Should not raise
        await fresh_manager.send_to_heir(
            "session-1", "no-such-heir", {"type": "test"}
        )

    @pytest.mark.asyncio
    async def test_send_to_heir_handles_dead_connection(self, fresh_manager):
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock(side_effect=Exception("Connection lost"))
        await fresh_manager.connect(ws, "session-1", heir_id="heir-A")

        await fresh_manager.send_to_heir(
            "session-1", "heir-A", {"type": "test"}
        )
        # Dead connection should be removed
        assert fresh_manager.is_heir_connected("session-1", "heir-A") is False


class TestSessionCount:
    """T38: Verify get_session_count."""

    def test_count_zero_for_unknown_session(self, fresh_manager):
        assert fresh_manager.get_session_count("no-session") == 0

    @pytest.mark.asyncio
    async def test_count_reflects_connections(self, fresh_manager):
        ws1 = MagicMock()
        ws1.accept = AsyncMock()
        ws2 = MagicMock()
        ws2.accept = AsyncMock()

        await fresh_manager.connect(ws1, "session-1")
        assert fresh_manager.get_session_count("session-1") == 1
        await fresh_manager.connect(ws2, "session-1")
        assert fresh_manager.get_session_count("session-1") == 2


class TestIsHeirConnected:
    """T38: Verify is_heir_connected."""

    def test_false_for_unknown(self, fresh_manager):
        assert fresh_manager.is_heir_connected("s1", "h1") is False

    @pytest.mark.asyncio
    async def test_true_for_registered(self, fresh_manager, mock_websocket):
        await fresh_manager.connect(mock_websocket, "session-1", heir_id="heir-A")
        assert fresh_manager.is_heir_connected("session-1", "heir-A") is True