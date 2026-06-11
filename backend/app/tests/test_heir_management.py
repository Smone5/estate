"""
Tests for T13: FastAPI Heir Management & Invitations.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.models import Session as SessionModel, User
from app.auth import get_current_admin


SESSION_ID = uuid.uuid4()
HEIR_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "t13-test-secret")
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)


def _make_admin_payload():
    return {
        "user_id": str(ADMIN_ID),
        "username": "executor",
        "role": "ADMIN",
        "session_id": None,
    }


def _build_session(status="SETUP"):
    return SessionModel(
        id=SESSION_ID,
        title="Test Estate",
        status=status,
        is_paused=False,
        is_deadlocked=False,
    )


def _build_heir():
    return User(
        id=HEIR_ID,
        session_id=SESSION_ID,
        username="test_heir",
        role="HEIR",
        legal_first_name="Jane",
        legal_last_name="Doe",
        status="PENDING",
        invite_token=uuid.uuid4(),
        invite_token_expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        invite_token_used=False,
        consent_accepted=False,
        age_verified=False,
        is_submitted=False,
        draft_version=0,
        identity_verified=False,
        email="heir@example.com",
    )


@pytest.fixture
def mock_db():
    return mock.MagicMock(spec=DBSession)


@pytest.fixture
def client(mock_db):
    from app.main import app

    app.dependency_overrides[get_current_admin] = _make_admin_payload

    with mock.patch("app.main.SessionLocal", return_value=mock_db), \
         mock.patch("app.main.limiter.limit", lambda rate: lambda f: f), \
         mock.patch("app.main.send_email_background", new_callable=mock.AsyncMock) as mock_send:
        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client, mock_db, mock_send

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id}/heirs
# ---------------------------------------------------------------------------


class TestSessionHeirs:

    def test_list_heirs_success(self, client):
        test_client, mock_db, _ = client
        session = _build_session()
        heir = _build_heir()

        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.all.return_value = [heir]

        resp = test_client.get(f"/api/sessions/{SESSION_ID}/heirs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["username"] == "test_heir"
        assert data[0]["status"] == "PENDING"

    def test_list_heirs_session_not_found(self, client):
        test_client, mock_db, _ = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.get(f"/api/sessions/{SESSION_ID}/heirs")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/heirs
# ---------------------------------------------------------------------------


class TestCreateHeir:

    def test_create_heir_success(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="SETUP")
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.add = mock.MagicMock()

        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/heirs",
            json={
                "username": "alice",
                "legal_first_name": "Alice",
                "legal_last_name": "Smith",
                "email": "alice@example.com",
                "relationship_to_decedent": "Daughter",
                "date_of_birth": "1985-06-15",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "invite_token" in data
        assert "invite_url" in data
        assert data["username"] == "alice"

    def test_create_heir_locked_session_returns_400(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="LOCKED")
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/heirs",
            json={
                "username": "alice",
                "legal_first_name": "Alice",
                "legal_last_name": "Smith",
            },
        )
        assert resp.status_code == 400
        assert "locked" in resp.json()["detail"].lower()

    def test_create_heir_finalized_session_returns_400(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="FINALIZED")
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/heirs",
            json={
                "username": "alice",
                "legal_first_name": "Alice",
                "legal_last_name": "Smith",
            },
        )
        assert resp.status_code == 400

    def test_create_heir_session_not_found_returns_404(self, client):
        test_client, mock_db, _ = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/heirs",
            json={
                "username": "alice",
                "legal_first_name": "Alice",
                "legal_last_name": "Smith",
            },
        )
        assert resp.status_code == 404

    def test_create_heir_minimal_fields(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="SETUP")
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.add = mock.MagicMock()

        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/heirs",
            json={
                "username": "bob_min",
                "legal_first_name": "Bob",
                "legal_last_name": "Jones",
                # email, phone, dob, etc. all optional
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "bob_min"


# ---------------------------------------------------------------------------
# POST /api/heirs/{heir_id}/invite-token
# ---------------------------------------------------------------------------


class TestRenewInviteToken:

    def test_renew_token_success(self, client):
        test_client, mock_db, _ = client
        heir = _build_heir()
        session = _build_session(status="ACTIVE")

        # First call: find heir, then find session
        first_results = [heir, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        resp = test_client.post(
            f"/api/heirs/{HEIR_ID}/invite-token",
            json={"expiration_days": 7},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "invite_token" in data
        assert "invite_url" in data

    def test_renew_token_heir_not_found_returns_404(self, client):
        test_client, mock_db, _ = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.post(
            f"/api/heirs/{HEIR_ID}/invite-token",
            json={"expiration_days": 7},
        )
        assert resp.status_code == 404

    def test_renew_token_locked_session_returns_400(self, client):
        test_client, mock_db, _ = client
        heir = _build_heir()
        session = _build_session(status="LOCKED")

        first_results = [heir, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        resp = test_client.post(
            f"/api/heirs/{HEIR_ID}/invite-token",
            json={"expiration_days": 7},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/heirs/{heir_id}/send-invite
# ---------------------------------------------------------------------------


class TestSendInvite:

    def test_send_invite_success(self, client):
        test_client, mock_db, mock_send = client
        heir = _build_heir()
        session = _build_session(status="ACTIVE")

        first_results = [heir, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        resp = test_client.post(f"/api/heirs/{HEIR_ID}/send-invite")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "dispatched" in data["message"].lower()

        # Verify SMTP was called via background task
        mock_send.assert_called_once()

    def test_send_invite_no_email_returns_400(self, client):
        test_client, mock_db, _ = client
        heir = _build_heir()
        heir.email = None
        mock_db.query.return_value.filter.return_value.first.return_value = heir

        resp = test_client.post(f"/api/heirs/{HEIR_ID}/send-invite")
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()

    def test_send_invite_heir_not_found_returns_404(self, client):
        test_client, mock_db, _ = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.post(f"/api/heirs/{HEIR_ID}/send-invite")
        assert resp.status_code == 404

    def test_send_invite_locked_session_returns_400(self, client):
        test_client, mock_db, mock_send = client
        heir = _build_heir()
        session = _build_session(status="LOCKED")

        first_results = [heir, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        resp = test_client.post(f"/api/heirs/{HEIR_ID}/send-invite")
        assert resp.status_code == 400