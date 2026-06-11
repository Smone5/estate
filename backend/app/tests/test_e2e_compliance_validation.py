"""
T30: E2E compliance validation.

Validates the final cross-cutting compliance gate:
- GDPR Article 20 export schema
- CCPA/AB 2013 model transparency listings
- California SB 942 is_synthetic WebSocket frames
- SHA-256 audit hash-chain verification
"""

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from unittest import mock

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token, get_current_user
from app.models import User


SESSION_ID = uuid.uuid4()
HEIR_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "t30-compliance-secret")
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)


@pytest.fixture
def mock_db():
    return mock.MagicMock(spec=DBSession)


@pytest.fixture
def client(mock_db):
    with mock.patch("app.database.init_db"), \
         mock.patch("app.graph.get_postgres_checkpointer",
                    side_effect=RuntimeError("test: graph unavailable")), \
         mock.patch("app.graph.get_graph",
                    side_effect=RuntimeError("test: graph unavailable")), \
         mock.patch("app.main.SessionLocal", return_value=mock_db), \
         mock.patch("app.main.TTS_AVAILABLE", False):
        from app.main import app

        yield TestClient(app, raise_server_exceptions=False), app

        app.dependency_overrides.clear()


async def _accept_ws(websocket, session_id, heir_id=None):
    await websocket.accept()


def _receive_json(ws, timeout=5):
    async def receive_message():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    message = ws.portal.call(receive_message)
    ws._raise_on_close(message)
    if "text" in message:
        return json.loads(message["text"])
    return json.loads(message["bytes"].decode("utf-8"))


def _heir_payload():
    return {
        "user_id": str(HEIR_ID),
        "username": "compliance_heir",
        "role": "HEIR",
        "session_id": str(SESSION_ID),
    }


def _build_heir():
    heir = mock.MagicMock()
    heir.id = HEIR_ID
    heir.username = "compliance_heir"
    heir.role = "HEIR"
    heir.legal_first_name = "Ada"
    heir.legal_middle_name = None
    heir.legal_last_name = "Steward"
    heir.relationship_to_decedent = "Child"
    heir.date_of_birth = date(1988, 4, 12)
    heir.email = "ada@example.test"
    heir.phone = "555-0100"
    heir.physical_address = "10 Archive Lane"
    heir.identity_verified = True
    heir.consent_accepted = True
    heir.age_verified = True
    heir.consent_timestamp = datetime.now(timezone.utc)
    heir.is_submitted = False
    return heir


def _query_mock_for_export(heir):
    valuation = mock.MagicMock()
    valuation.asset_id = uuid.uuid4()
    valuation.points = 1000
    valuation.reasoning = "The keepsake preserves a family memory."
    valuation.is_reasoning_shared = True

    chat = mock.MagicMock()
    chat.created_at = datetime.now(timezone.utc)
    chat.sender = "heir"
    chat.message_text = "I would like the memory book."

    ticket = mock.MagicMock()
    ticket.id = uuid.uuid4()
    ticket.message = "Please confirm my export."
    ticket.status = "OPEN"

    filter_mock = mock.MagicMock()
    filter_mock.first.return_value = heir
    filter_mock.all.return_value = [valuation]

    ordered_mock = mock.MagicMock()
    ordered_mock.all.side_effect = [[chat], [ticket]]
    filter_mock.order_by.return_value = ordered_mock

    query_mock = mock.MagicMock()
    query_mock.filter.return_value = filter_mock
    return query_mock


class TestE2EComplianceValidation:
    def test_gdpr_export_matches_article_20_schema(self, client, mock_db):
        test_client, app = client
        app.dependency_overrides[get_current_user] = _heir_payload
        mock_db.query.return_value = _query_mock_for_export(_build_heir())

        response = test_client.get("/api/heirs/me/export")

        assert response.status_code == 200
        data = response.json()
        assert {
            "heir_id",
            "username",
            "legal_first_name",
            "legal_middle_name",
            "legal_last_name",
            "relationship_to_decedent",
            "date_of_birth",
            "identity_verified",
            "email",
            "phone",
            "physical_address",
            "consent_accepted",
            "age_verified",
            "consent_timestamp",
            "is_submitted",
            "valuations",
            "chat_history",
            "support_tickets",
        }.issubset(data.keys())
        assert data["valuations"][0]["asset_id"]
        assert data["chat_history"][0]["text"] == "I would like the memory book."
        assert data["support_tickets"][0]["status"] == "OPEN"
        assert "profile" not in data
        assert "support_requests" not in data

    def test_ccpa_ab2013_transparency_listing_is_public_and_complete(self, client):
        test_client, _ = client

        response = test_client.get("/api/system/models")

        assert response.status_code == 200
        models = response.json()["models"]
        components = {entry["component"] for entry in models}
        assert components == {
            "Fast Mediator (System 1)",
            "Slow Critic (System 2)",
            "Vision OCR Engine",
            "Local Speech Synthesis (TTS)",
            "Semantic Search & RAG Embedding Engine",
        }
        for entry in models:
            assert entry["name"]
            assert entry["parameters"]
            assert entry["license"]
            assert entry["provenance"]

    def test_websocket_chat_chunks_are_all_sb942_synthetic(self, client, mock_db):
        test_client, _ = client
        sid = str(SESSION_ID)
        hid = str(HEIR_ID)
        mock_db.query.return_value.filter.return_value.first.return_value = User(
            id=hid,
            username="compliance_heir",
            role="HEIR",
            session_id=sid,
            status="ACTIVE",
            consent_accepted=True,
            age_verified=True,
            identity_verified=True,
        )
        test_client.cookies = {
            "estate_session": create_access_token(
                user_id=hid,
                username="compliance_heir",
                role="HEIR",
                session_id=sid,
            )
        }

        with mock.patch("app.main.manager.connect", side_effect=_accept_ws), \
             mock.patch("app.main.manager.disconnect"):
            with test_client.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
                ws.send_json({"type": "chat_message", "text": "Tell me about the clock."})
                chunks = []
                for _ in range(30):
                    frame = _receive_json(ws)
                    if frame.get("type") == "chat_reply_chunk":
                        chunks.append(frame)
                    if frame.get("is_final") or frame.get("type") == "error":
                        break

        assert chunks
        for chunk in chunks:
            assert chunk["is_synthetic"] is True
            assert "audio" in chunk

    def test_hash_chain_verifier_confirms_valid_chain_and_detects_break(self, client, mock_db):
        test_client, _ = client

        snapshot = {"heir": "Anonymized", "action": "FINALIZED"}
        prev_hash = "0" * 64
        snapshot_str = str(sorted(snapshot.items()))
        valid_hash = hashlib.sha256(
            f"1:FINALIZED:{snapshot_str}:{prev_hash}".encode("utf-8")
        ).hexdigest()

        log = mock.MagicMock()
        log.id = 1
        log.event_type = "FINALIZED"
        log.session_id = SESSION_ID
        log.state_snapshot = snapshot
        log.prev_hash = prev_hash
        log.sha256_hash = valid_hash
        log.created_at = datetime.now(timezone.utc)

        ordered_mock = mock.MagicMock()
        ordered_mock.all.return_value = [log]
        mock_db.query.return_value.order_by.return_value = ordered_mock

        response = test_client.get("/api/system/verify-hash-chain")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "valid"
        assert data["verified"] is True
        assert data["rows"][0]["hash_valid"] is True

        log.sha256_hash = "b" * 64
        response = test_client.get("/api/system/verify-hash-chain")

        assert response.status_code == 200
        broken = response.json()
        assert broken["status"] == "broken"
        assert broken["verified"] is False
        assert broken["breaks"][0]["row_id"] == 1
