"""
Tests for T37: FastAPI Session Lifecycle & Announcement API.

Covers:
- POST /api/sessions/{session_id}/launch
- POST /api/sessions/{session_id}/pause
- POST /api/sessions/{session_id}/unpause
- PUT  /api/sessions/{session_id}/announcement
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.models import Session as SessionModel, User, Asset, ChatMessage
from app.auth import get_current_admin


ASSET_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()
HEIR_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "t37-test-secret-key")
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)


def _make_admin_payload():
    return {
        "user_id": str(ADMIN_ID),
        "username": "executor",
        "role": "ADMIN",
        "session_id": None,
    }


def _build_session(status="SETUP", is_paused=False, paused_at=None, deadline=None):
    return SessionModel(
        id=SESSION_ID,
        title="Test Estate",
        status=status,
        is_paused=is_paused,
        paused_at=paused_at,
        is_deadlocked=False,
        deadline=deadline,
        announcement=None,
        announcement_updated_at=None,
    )


def _build_heir(token_expiry=None, invite_token_used=False):
    return User(
        id=HEIR_ID,
        session_id=SESSION_ID,
        username="heir_test",
        role="HEIR",
        pw_hash=None,
        invite_token=str(uuid.uuid4()),
        invite_token_expires_at=token_expiry or (datetime.now(timezone.utc) + timedelta(days=14)),
        invite_token_used=invite_token_used,
        consent_accepted=False,
        age_verified=False,
        status="PENDING",
    )


@pytest.fixture
def mock_db():
    """Return a MagicMock for the DB session."""
    return mock.MagicMock(spec=DBSession)


@pytest.fixture
def client(mock_db):
    """FastAPI TestClient with DB mock and auth dependency override."""
    from app.main import app

    # Override the auth dependency so all admin endpoints bypass JWT checks
    def _override_get_current_admin():
        return _make_admin_payload()

    from app.auth import get_current_user
    app.dependency_overrides[get_current_admin] = _override_get_current_admin
    app.dependency_overrides[get_current_user] = lambda: {"user_id": str(HEIR_ID), "role": "ADMIN"}

    async def _async_noop(*args, **kwargs):
        pass

    with mock.patch("app.main.SessionLocal", return_value=mock_db), \
         mock.patch("app.main.manager") as mock_mgr, \
         mock.patch("app.main.limiter.limit", lambda rate: lambda f: f):
        # Make async manager methods properly awaitable mocks
        mock_mgr.broadcast_session_status = mock.AsyncMock(side_effect=_async_noop)
        mock_mgr.broadcast_announcement = mock.AsyncMock(side_effect=_async_noop)

        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client, mock_db, mock_mgr

    # Clean up overrides
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/launch
# ---------------------------------------------------------------------------


class TestSessionLaunch:

    def test_launch_success_returns_200(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="SETUP")
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.count.return_value = 1

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/launch")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == str(SESSION_ID)
        assert data["status"] == "ACTIVE"

    def test_launch_updates_session_fields(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="SETUP")
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.count.return_value = 1

        test_client.post(f"/api/sessions/{SESSION_ID}/launch")
        assert session.status == "ACTIVE"
        assert session.deadline is not None
        mock_db.commit.assert_called()

    def test_launch_broadcasts_websocket(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="SETUP")
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.count.return_value = 1

        test_client.post(f"/api/sessions/{SESSION_ID}/launch")
        mock_mgr.broadcast_session_status.assert_called()

    def test_launch_session_not_found_returns_404(self, client):
        test_client, mock_db, mock_mgr = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/launch")
        assert resp.status_code == 404

    def test_launch_not_in_setup_returns_400(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="ACTIVE")
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/launch")
        assert resp.status_code == 400

    def test_launch_no_published_assets_returns_400(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="SETUP")
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/launch")
        assert resp.status_code == 400
        assert "no published assets" in resp.json()["detail"].lower()

    def test_launch_with_pre_allocated_assets_succeeds(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="SETUP")
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.count.return_value = 1

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/launch")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/pause
# ---------------------------------------------------------------------------


class TestSessionPause:

    def test_pause_active_session_succeeds(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="ACTIVE", is_paused=False)
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/pause")
        assert resp.status_code == 200
        assert resp.json()["is_paused"] is True

    def test_pause_sets_lock_status(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="ACTIVE", is_paused=False)
        mock_db.query.return_value.filter.return_value.first.return_value = session

        test_client.post(f"/api/sessions/{SESSION_ID}/pause")
        assert session.status == "LOCKED"
        assert session.is_paused is True
        assert session.paused_at is not None
        mock_db.commit.assert_called()

    def test_pause_broadcasts_websocket(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="ACTIVE", is_paused=False)
        mock_db.query.return_value.filter.return_value.first.return_value = session

        test_client.post(f"/api/sessions/{SESSION_ID}/pause")
        mock_mgr.broadcast_session_status.assert_called()

    def test_pause_setup_session_returns_400(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="SETUP", is_paused=False)
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/pause")
        assert resp.status_code == 400

    def test_pause_finalized_session_returns_400(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="FINALIZED", is_paused=False)
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/pause")
        assert resp.status_code == 400

    def test_pause_already_paused_returns_400(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="ACTIVE", is_paused=True)
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/pause")
        assert resp.status_code == 400
        assert "already paused" in resp.json()["detail"].lower()

    def test_pause_session_not_found_returns_404(self, client):
        test_client, mock_db, mock_mgr = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/pause")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/unpause
# ---------------------------------------------------------------------------


class TestSessionUnpause:

    def test_unpause_success_returns_200(self, client):
        test_client, mock_db, mock_mgr = client
        paused_at = datetime.now(timezone.utc) - timedelta(hours=2)
        session = _build_session(status="LOCKED", is_paused=True, paused_at=paused_at)
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.all.return_value = []

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/unpause")
        assert resp.status_code == 200
        assert resp.json()["is_paused"] is False

    def test_unpause_restores_active_status(self, client):
        test_client, mock_db, mock_mgr = client
        paused_at = datetime.now(timezone.utc) - timedelta(hours=2)
        session = _build_session(status="LOCKED", is_paused=True, paused_at=paused_at)
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.all.return_value = []

        test_client.post(f"/api/sessions/{SESSION_ID}/unpause")
        assert session.status == "ACTIVE"
        assert session.is_paused is False
        assert session.paused_at is None

    def test_unpause_extends_deadline(self, client):
        test_client, mock_db, mock_mgr = client
        paused_at = datetime.now(timezone.utc) - timedelta(hours=3)
        original_deadline = datetime.now(timezone.utc) + timedelta(days=10)
        session = _build_session(
            status="LOCKED", is_paused=True, paused_at=paused_at,
            deadline=original_deadline,
        )
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.all.return_value = []

        test_client.post(f"/api/sessions/{SESSION_ID}/unpause")
        # Deadline should be extended by roughly 3 hours
        assert session.deadline > original_deadline

    def test_unpause_extends_heir_tokens(self, client):
        test_client, mock_db, mock_mgr = client
        paused_at = datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)
        session = _build_session(status="LOCKED", is_paused=True, paused_at=paused_at)
        original_token_expiry = datetime.now(timezone.utc) + timedelta(days=5)
        heir = _build_heir(token_expiry=original_token_expiry)
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.all.return_value = [heir]

        test_client.post(f"/api/sessions/{SESSION_ID}/unpause")
        # Token expiry should be extended by ~1.5 hours
        assert heir.invite_token_expires_at > original_token_expiry

    def test_unpause_does_not_extend_expired_tokens(self, client):
        test_client, mock_db, mock_mgr = client
        paused_at = datetime.now(timezone.utc) - timedelta(hours=2)
        session = _build_session(status="LOCKED", is_paused=True, paused_at=paused_at)
        # Token already expired — should NOT be extended
        expired_token = datetime.now(timezone.utc) - timedelta(days=1)
        heir = _build_heir(token_expiry=expired_token)
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.all.return_value = [heir]

        test_client.post(f"/api/sessions/{SESSION_ID}/unpause")
        assert heir.invite_token_expires_at == expired_token

    def test_unpause_broadcasts_websocket(self, client):
        test_client, mock_db, mock_mgr = client
        paused_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        session = _build_session(status="LOCKED", is_paused=True, paused_at=paused_at)
        mock_db.query.return_value.filter.return_value.first.return_value = session
        mock_db.query.return_value.filter.return_value.all.return_value = []

        test_client.post(f"/api/sessions/{SESSION_ID}/unpause")
        mock_mgr.broadcast_session_status.assert_called()

    def test_unpause_not_paused_returns_400(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="ACTIVE", is_paused=False)
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/unpause")
        assert resp.status_code == 400
        assert "not paused" in resp.json()["detail"].lower()

    def test_unpause_missing_paused_at_returns_400(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="LOCKED", is_paused=True, paused_at=None)
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/unpause")
        assert resp.status_code == 400

    def test_unpause_session_not_found_returns_404(self, client):
        test_client, mock_db, mock_mgr = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/unpause")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/sessions/{session_id}/announcement
# ---------------------------------------------------------------------------


class TestSessionAnnouncement:

    def test_set_announcement_success(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="ACTIVE")
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.put(
            f"/api/sessions/{SESSION_ID}/announcement",
            json={"announcement": "The will reading is scheduled."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["announcement"] == "The will reading is scheduled."
        assert data["announcement_updated_at"] is not None

    def test_clear_announcement(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="ACTIVE")
        session.announcement = "Old message"
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.put(
            f"/api/sessions/{SESSION_ID}/announcement",
            json={"announcement": None},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["announcement"] is None

    def test_announcement_updates_timestamp(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="ACTIVE")
        mock_db.query.return_value.filter.return_value.first.return_value = session

        test_client.put(
            f"/api/sessions/{SESSION_ID}/announcement",
            json={"announcement": "Hello heirs."},
        )
        assert session.announcement_updated_at is not None

    def test_announcement_broadcasts_websocket(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="ACTIVE")
        mock_db.query.return_value.filter.return_value.first.return_value = session

        test_client.put(
            f"/api/sessions/{SESSION_ID}/announcement",
            json={"announcement": "Notice text."},
        )
        mock_mgr.broadcast_announcement.assert_called()

    def test_announcement_finalized_session_returns_400(self, client):
        test_client, mock_db, mock_mgr = client
        session = _build_session(status="FINALIZED")
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.put(
            f"/api/sessions/{SESSION_ID}/announcement",
            json={"announcement": "Too late."},
        )
        assert resp.status_code == 400

    def test_announcement_session_not_found_returns_404(self, client):
        test_client, mock_db, mock_mgr = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.put(
            f"/api/sessions/{SESSION_ID}/announcement",
            json={"announcement": "Test"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id} & GET /api/sessions
# ---------------------------------------------------------------------------


class TestGetSessionDetails:

    def test_get_session_details_success(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="ACTIVE")
        session.created_at = datetime.now(timezone.utc)
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.get(f"/api/sessions/{SESSION_ID}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(SESSION_ID)
        assert data["status"] == "ACTIVE"
        assert data["is_paused"] is False

    def test_get_session_details_not_found(self, client):
        test_client, mock_db, _ = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.get(f"/api/sessions/{SESSION_ID}")
        assert resp.status_code == 404

    def test_list_sessions_admin(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="SETUP")
        session.created_at = datetime.now(timezone.utc)
        mock_db.query.return_value.all.return_value = [session]

        resp = test_client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == str(SESSION_ID)