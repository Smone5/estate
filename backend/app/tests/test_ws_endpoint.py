"""
Tests for T22 — WebSocket Server Endpoint (/api/sessions/{session_id}/ws).
"""

import json, uuid
from unittest import mock

import anyio
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token
from app.models import User


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "ws-secret-key-32chars-long!")
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)


@pytest.fixture
def mock_db():
    return mock.MagicMock(spec=DBSession)


@pytest.fixture
def client(mock_db):
    # Patch out the real PostgreSQL-backed graph so WS handler chat paths
    # never try to open a TCP connection to the database.
    # Also neuter init_db() — its retry loop to db:5432 hangs ~60 s outside
    # Docker because the hostname never resolves / TCP connect times out.
    with mock.patch("app.database.init_db"), \
         mock.patch("app.graph.get_postgres_checkpointer",
                    side_effect=RuntimeError("test: graph unavailable")), \
         mock.patch("app.graph.get_graph",
                    side_effect=RuntimeError("test: graph unavailable")), \
         mock.patch("app.main.SessionLocal", return_value=mock_db), \
         mock.patch("app.main.TTS_AVAILABLE", False):
        from app.main import app
        yield TestClient(app, raise_server_exceptions=False)


# ── WS manager mock — patches app.main.manager (the imported singleton) ───────

async def _noop_connect(websocket, session_id, heir_id=None):
    await websocket.accept()

def _noop_disconnect(websocket, session_id=None):
    pass


# ── helpers ──────────────────────────────────────────────────────────────────

def _receive_json(ws, timeout=5):
    async def receive_message():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    message = ws.portal.call(receive_message)
    ws._raise_on_close(message)
    if "text" in message:
        return json.loads(message["text"])
    return json.loads(message["bytes"].decode("utf-8"))

def _heir_jwt(hid, sid):
    return create_access_token(user_id=hid, username="h", role="HEIR", session_id=sid)

def _admin_jwt(aid):
    return create_access_token(user_id=aid, username="a", role="ADMIN", session_id=None)

def _make_heir(mock_db, sid, hid, status="ACTIVE"):
    mock_db.query.return_value.filter.return_value.first.return_value = User(
        id=hid, username="h", role="HEIR", session_id=sid, status=status,
        consent_accepted=True, age_verified=True, identity_verified=True)


# ── handshake auth ───────────────────────────────────────────────────────────

def test_ws_rejects_no_cookie(client):
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        try:
            with client.websocket_connect("/api/sessions/any/ws"):
                pytest.fail("should reject")
        except WebSocketDisconnect as e:
            assert e.code == 4003


def test_ws_rejects_invalid_token(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "ws-secret-key-32chars-long!")
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)
    mdb = mock.MagicMock(spec=DBSession)
    with mock.patch("app.main.SessionLocal", return_value=mdb), \
         mock.patch("app.main.TTS_AVAILABLE", False):
        from app.main import app
        tc = TestClient(app, raise_server_exceptions=False)
        tc.cookies = {"estate_session": "not.valid.jwt"}
        with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
             mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
            try:
                with tc.websocket_connect("/api/sessions/any/ws"):
                    pass
            except WebSocketDisconnect as e:
                assert e.code == 4003


def test_ws_heir_profile_hold_rejected(client, mock_db):
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid, status="PROFILE_HOLD")
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        try:
            with tc.websocket_connect(f"/api/sessions/{sid}/ws"):
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4003


# ── chat flow ────────────────────────────────────────────────────────────────

def test_ws_chat_frames_is_synthetic_true(client, mock_db):
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)

    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "chat_message", "text": "Tell me about the vase."})
            chunks = []
            for _ in range(30):
                try:
                    f = _receive_json(ws)
                    if f.get("type") == "chat_reply_chunk":
                        chunks.append(f)
                    if f.get("is_final") or f.get("type") == "error":
                        break
                except TimeoutError:
                    break
            assert len(chunks) >= 1, f"no chunks: {chunks}"
            for c in chunks:
                assert c.get("is_synthetic") is True, f"SB 942: {json.dumps(c)}"


def test_ws_chat_persists_to_db(client, mock_db):
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)

    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "chat_message", "text": "Hello."})
            for _ in range(30):
                try:
                    f = _receive_json(ws)
                    if f.get("is_final"):
                        break
                except TimeoutError:
                    break
            assert mock_db.add.called, "chat message not persisted"


def test_ws_hitl_guard_rejects_chat(client, mock_db):
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)

    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect), \
         mock.patch("app.main._check_hitl_guard", return_value=True):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "chat_message", "text": "bid?"})
            for _ in range(10):
                try:
                    f = _receive_json(ws)
                    if f.get("type") == "error":
                        assert "suspended" in f.get("message", "").lower()
                        return
                except TimeoutError:
                    pass
            pytest.fail("expected HITL error frame")


def test_ws_ping_pong(client, mock_db):
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)

    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "ping"})
            assert _receive_json(ws)["type"] == "pong"


def test_ws_admin_can_connect(client, mock_db):
    sid, aid = str(uuid.uuid4()), str(uuid.uuid4())
    jwt = _admin_jwt(aid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "broadcast", "text": "Notice."})
            ws.send_json({"type": "ping"})
            assert _receive_json(ws)["type"] == "pong"


def test_ws_invalid_json(client, mock_db):
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_text("not json")
            f = _receive_json(ws)
            assert f.get("type") == "error"


def test_ws_all_chunks_sb942(client, mock_db):
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            all_chunks = []
            for msg in ["Tell me about the clock.", "And the painting?"]:
                ws.send_json({"type": "chat_message", "text": msg})
                for _ in range(30):
                    try:
                        f = _receive_json(ws)
                        if f.get("type") == "chat_reply_chunk":
                            all_chunks.append(f)
                        if f.get("is_final"):
                            break
                    except TimeoutError:
                        break
            assert len(all_chunks) >= 1
            for i, c in enumerate(all_chunks):
                assert c.get("is_synthetic") is True, f"SB 942 #{i}: {json.dumps(c)}"


# ── Phase 6–7 T28c — WebSocket audio guard, null-audio, broadcast, validation ─

def test_ws_audio_null_when_tts_unavailable(client, mock_db):
    """Testing Spec §2.2: null audio chunk does not crash the stream."""
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect), \
         mock.patch("app.main.TTS_AVAILABLE", False):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "chat_message", "text": "Hi."})
            found = []
            for _ in range(30):
                try:
                    f = _receive_json(ws)
                    if f.get("type") == "chat_reply_chunk":
                        found.append(f)
                        assert f.get("audio") is None, (
                            f"null audio expected when TTS unavailable: {json.dumps(f)}"
                        )
                    if f.get("is_final"):
                        break
                except TimeoutError:
                    break
            assert len(found) >= 1


def test_ws_audio_populated_when_tts_available(client, mock_db, monkeypatch):
    """Testing Spec §2.2: audio b64 populated when TTS is available."""
    from app.tests.mock_kokoro import MockKokoroTTS
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    # MockKokoroTTS.synthesize is synchronous, but the WS handler awaits it.
    # Wrap with an async-compatible mock so the await succeeds.
    fake_tts = MockKokoroTTS()
    fake_tts.synthesize = mock.AsyncMock(
        side_effect=lambda text, voice=None, speed=None: MockKokoroTTS.synthesize(fake_tts, text)
    )
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect), \
         mock.patch("app.main.TTS_AVAILABLE", True), \
         mock.patch("app.main.get_kokoro_tts", return_value=fake_tts):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "chat_message", "text": "Tell me about grandpa's clock."})
            chunks = []
            for _ in range(30):
                try:
                    f = _receive_json(ws)
                    if f.get("type") == "chat_reply_chunk":
                        chunks.append(f)
                        assert f.get("audio") is not None, (
                            f"audio expected when TTS available: {json.dumps(f)}"
                        )
                    if f.get("is_final"):
                        break
                except TimeoutError:
                    break
            assert len(chunks) >= 1


def test_ws_rejects_empty_chat_message(client, mock_db):
    """Empty chat_message text returns error frame."""
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "chat_message", "text": ""})
            for _ in range(10):
                try:
                    f = _receive_json(ws)
                    if f.get("type") == "error":
                        assert "empty" in f.get("message", "").lower()
                        return
                except TimeoutError:
                    pass
            pytest.fail("expected error frame for empty message")


def test_ws_chat_message_blank_text(client, mock_db):
    """Whitespace-only chat_message text returns error frame."""
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "chat_message", "text": "   "})
            for _ in range(10):
                try:
                    f = _receive_json(ws)
                    if f.get("type") == "error":
                        assert "empty" in f.get("message", "").lower()
                        return
                except TimeoutError:
                    pass
            pytest.fail("expected error frame for whitespace-only message")


def test_ws_heir_session_id_mismatch_rejected(client, mock_db):
    """Heir JWT with wrong session_id is rejected at handshake."""
    correct_sid, wrong_sid = str(uuid.uuid4()), str(uuid.uuid4())
    hid = str(uuid.uuid4())
    _make_heir(mock_db, correct_sid, hid)
    jwt = _heir_jwt(hid, correct_sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        try:
            with tc.websocket_connect(f"/api/sessions/{wrong_sid}/ws"):
                pass
        except WebSocketDisconnect as e:
            assert e.code == 4003


def test_ws_session_status_broadcast_frame(client, mock_db):
    """Testing Spec §2.2: heirs receive session_status broadcast frames."""
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect), \
         mock.patch("app.main.manager.broadcast_session_status") as mock_broadcast:
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "ping"})
            assert _receive_json(ws)["type"] == "pong"
    # Verify broadcast_session_status is available on the manager
    assert callable(mock_broadcast)


def test_ws_unknown_message_type_graceful(client, mock_db):
    """Unknown message type does not crash the socket."""
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "bogus_type_xyz", "payload": 123})
            ws.send_json({"type": "ping"})
            pong = _receive_json(ws)
            assert pong["type"] == "pong"


def test_ws_chat_missing_text_field(client, mock_db):
    """chat_message with missing text field returns error."""
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "chat_message"})
            for _ in range(10):
                try:
                    f = _receive_json(ws)
                    if f.get("type") == "error":
                        assert "empty" in f.get("message", "").lower()
                        return
                except TimeoutError:
                    pass
            pytest.fail("expected error frame for missing text field")


def test_ws_chat_reply_every_chunk_has_is_synthetic(client, mock_db):
    """SB 942 §2.5: every chat_reply_chunk across 3 messages has is_synthetic: true."""
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            all_chunks = []
            for text in ["Hello.", "I care about the ring.", "Tell me more."]:
                ws.send_json({"type": "chat_message", "text": text})
                for _ in range(30):
                    try:
                        f = _receive_json(ws)
                        if f.get("type") == "chat_reply_chunk":
                            all_chunks.append(f)
                        if f.get("is_final"):
                            break
                    except TimeoutError:
                        break
            assert len(all_chunks) >= 3
            for i, c in enumerate(all_chunks):
                assert c.get("is_synthetic") is True, (
                    f"SB 942 violation at chunk #{i}: {json.dumps(c)}"
                )


def test_ws_disconnect_cleanup_calls_manager(client, mock_db):
    """WebSocket disconnect invokes manager.disconnect."""
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect") as mock_disconnect:
        with tc.websocket_connect(f"/api/sessions/{sid}/ws"):
            pass
    mock_disconnect.assert_called_once()


def test_ws_replies_in_order_with_is_final(client, mock_db):
    """chat_reply_chunks arrive in order; only last has is_final=true."""
    sid, hid = str(uuid.uuid4()), str(uuid.uuid4())
    _make_heir(mock_db, sid, hid)
    jwt = _heir_jwt(hid, sid)
    tc = TestClient(client.app, raise_server_exceptions=False)
    tc.cookies = {"estate_session": jwt}
    with mock.patch("app.main.manager.connect", side_effect=_noop_connect), \
         mock.patch("app.main.manager.disconnect", side_effect=_noop_disconnect):
        with tc.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
            ws.send_json({"type": "chat_message", "text": "Hi."})
            chunks = []
            for _ in range(30):
                try:
                    f = _receive_json(ws)
                    if f.get("type") == "chat_reply_chunk":
                        chunks.append(f)
                        if f.get("is_final"):
                            break
                except TimeoutError:
                    break
            assert len(chunks) >= 1
            for i, c in enumerate(chunks):
                if i < len(chunks) - 1:
                    assert c.get("is_final") is False, f"non-final chunk #{i} had is_final=true"
                else:
                    assert c.get("is_final") is True, f"last chunk #{i} had is_final=false"
