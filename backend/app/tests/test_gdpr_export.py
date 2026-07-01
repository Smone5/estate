"""
T57: Test GDPR Data Portability API — GET /api/heirs/me/export

Per Testing Spec §1.1 (Test GDPR Portability Export):
Verify that the endpoint returns a structured JSON payload containing
the decrypted chat history, valuations, and support logs matching
Compliance Spec §2.2 schema.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import get_current_user


HEIR_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()
ASSET1_ID = uuid.uuid4()
ASSET2_ID = uuid.uuid4()
TICKET_ID = uuid.uuid4()
NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "t57-test-secret")
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)


def _make_heir_payload():
    return {
        "user_id": str(HEIR_ID),
        "username": "export_test_user",
        "role": "HEIR",
        "session_id": str(SESSION_ID),
    }


def _build_heir():
    user = mock.MagicMock()
    user.id = HEIR_ID
    user.username = "export_test_user"
    user.role = "HEIR"
    user.legal_first_name = "Test"
    user.legal_middle_name = "Middle"
    user.legal_last_name = "Heir"
    user.relationship_to_decedent = "Child"
    user.date_of_birth = datetime(1990, 5, 15).date()
    user.email = "export_test@example.com"
    user.phone = "555-000-1111"
    user.physical_address = "456 Export Blvd, Testville, TX 75001"
    user.identity_verified = True
    user.consent_accepted = True
    user.age_verified = True
    user.consent_timestamp = NOW - timedelta(days=1)
    user.is_submitted = False
    return user


def _build_valuation(asset_id, points, reasoning, is_shared):
    v = mock.MagicMock()
    v.asset_id = asset_id
    v.points = points
    v.reasoning = reasoning
    v.is_reasoning_shared = is_shared
    return v


def _build_chat(delta_hours, sender, text):
    m = mock.MagicMock()
    m.created_at = NOW - timedelta(hours=delta_hours)
    m.sender = sender
    m.message_text = text
    return m


def _build_ticket(ticket_id, message, status):
    t = mock.MagicMock()
    t.id = ticket_id
    t.message = message
    t.status = status
    t.admin_response = None
    t.initiator_role = "HEIR"
    t.created_at = NOW - timedelta(hours=3)
    t.responded_at = None
    t.resolved_at = None
    return t


@pytest.fixture
def mock_db():
    return mock.MagicMock(spec=DBSession)


@pytest.fixture
def client(mock_db):
    from app.main import app

    app.dependency_overrides[get_current_user] = _make_heir_payload

    with mock.patch("app.main.SessionLocal", return_value=mock_db), \
         mock.patch("app.main.limiter.limit", lambda rate: lambda f: f):
        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client, mock_db

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGdprExport:
    def test_export_returns_flat_schema(self, client):
        """Verify export returns flat JSON matching Compliance Spec §2.2."""
        test_client, mock_db = client

        heir = _build_heir()
        v1 = _build_valuation(ASSET1_ID, 600, "Family heirloom.", True)
        v2 = _build_valuation(ASSET2_ID, 400, "Private value.", False)
        chat1 = _build_chat(2, "heir", "Hello, I need help.")
        chat2 = _build_chat(1, "agent", "I am here to help.")
        ticket = _build_ticket(TICKET_ID, "Need help with export feature.", "OPEN")

        # Set up the DB query chain to return different values in sequence.
        # The endpoint makes 4 queries:
        #   1. User.filter().first() → heir
        #   2. Valuation.filter().all() → [v1, v2]
        #   3. ChatMessage.filter().order_by().all() → [chat1, chat2]
        #   4. SupportRequest.filter().order_by().all() → [ticket]

        # All queries start from mock_db.query() which returns a single mock.
        # We set up the inner mock to return different results via side_effect
        # on its .first() and on the .order_by() → .all() chain.

        filter_mock = mock.MagicMock()

        # Query 1: .first() → heir
        filter_mock.first.return_value = heir

        # Query 2: Valuation.filter().all()   (NO .order_by() — direct .all())
        filter_mock.all.return_value = [v1, v2]

        # Queries 3-4: .order_by().all() returns sequenced results
        order_mock = mock.MagicMock()
        order_mock.all.side_effect = [
            [chat1, chat2],  # chat query
            [ticket],        # support ticket query
        ]
        filter_mock.order_by.return_value = order_mock

        mock_db.query.return_value.filter.return_value = filter_mock

        response = test_client.get("/api/heirs/me/export")
        assert response.status_code == 200

        data = response.json()

        # Top-level keys match Compliance Spec §2.2 flat schema
        assert "heir_id" in data
        assert "username" in data
        assert "legal_first_name" in data
        assert "legal_middle_name" in data
        assert "legal_last_name" in data
        assert "relationship_to_decedent" in data
        assert "date_of_birth" in data
        assert "identity_verified" in data
        assert "email" in data
        assert "phone" in data
        assert "physical_address" in data
        assert "consent_accepted" in data
        assert "age_verified" in data
        assert "consent_timestamp" in data
        assert "is_submitted" in data
        assert "valuations" in data
        assert "chat_history" in data
        assert "support_tickets" in data

        # Verify flat schema — no nested "profile" or extra metadata
        assert "profile" not in data
        assert "export_timestamp_utc" not in data
        assert "support_requests" not in data

        # Verify profile values
        assert data["heir_id"] == str(HEIR_ID)
        assert data["legal_first_name"] == "Test"
        assert data["legal_middle_name"] == "Middle"
        assert data["legal_last_name"] == "Heir"
        assert data["relationship_to_decedent"] == "Child"
        assert data["date_of_birth"] == "1990-05-15"
        assert data["email"] == "export_test@example.com"

        # Verify valuations
        assert len(data["valuations"]) == 2

        # Verify chat_history uses spec keys: timestamp, sender, text
        assert len(data["chat_history"]) == 2
        for msg in data["chat_history"]:
            assert "timestamp" in msg
            assert "sender" in msg
            assert "text" in msg
            assert "id" not in msg
            assert "message_text" not in msg
            assert "scrubbed_text" not in msg

        # Verify support_tickets uses spec keys
        assert len(data["support_tickets"]) == 1
        ticket_data = data["support_tickets"][0]
        assert ticket_data["id"] == str(TICKET_ID)
        assert ticket_data["message"] == "Need help with export feature."
        assert ticket_data["status"] == "OPEN"
        assert "initiator_role" in ticket_data
        assert "created_at" in ticket_data
        assert "admin_response" in ticket_data
        assert "responded_at" in ticket_data
        assert "resolved_at" in ticket_data

    def test_export_rejects_non_heir(self, client):
        """Verify non-HEIR users get 403 Forbidden."""
        from app.main import app

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "admin-id",
            "username": "admin_user",
            "role": "ADMIN",
            "session_id": None,
        }

        test_client, _ = client
        response = test_client.get("/api/heirs/me/export")
        assert response.status_code == 403
        assert "Heir access required" in response.json()["detail"]

        app.dependency_overrides.clear()
        app.dependency_overrides[get_current_user] = _make_heir_payload

    def test_export_returns_401_for_nonexistent_heir(self, client):
        """Verify a JWT for a non-existent Heir returns 401."""
        from app.main import app

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": str(uuid.uuid4()),
            "username": "nonexistent",
            "role": "HEIR",
            "session_id": str(uuid.uuid4()),
        }

        mock_db = client[1]
        filter_mock = mock.MagicMock()
        filter_mock.first.return_value = None
        mock_db.query.return_value.filter.return_value = filter_mock

        test_client = client[0]
        response = test_client.get("/api/heirs/me/export")
        assert response.status_code == 401
        assert "Heir not found" in response.json()["detail"]

        app.dependency_overrides.clear()
        app.dependency_overrides[get_current_user] = _make_heir_payload
