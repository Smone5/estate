"""
Tests for T40: Asset Deletion API.

Covers:
- DELETE /api/assets/{asset_id}  (asset deletion with file cleanup)
"""

import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token
from app.models import Asset, Session as SessionModel


TEST_JWT_SECRET = "test-secret-key-for-tests-only-do-not-use-in-production"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    """Set required env vars for auth and encryption modules."""
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)
    monkeypatch.setenv("STORAGE_DRIVER", "MOCK")


@pytest.fixture
def mock_db_session():
    """Return a MagicMock wrapping a SQLAlchemy session."""
    session = mock.MagicMock(spec=DBSession)
    return session


@pytest.fixture
def client(mock_db_session):
    """FastAPI TestClient with a mocked database session."""
    with mock.patch("app.main.SessionLocal", return_value=mock_db_session):
        from app.main import app
        yield TestClient(app, raise_server_exceptions=False)


def _make_admin_token():
    """Return a valid JWT token for an Admin user."""
    return create_access_token(
        user_id=str(uuid.uuid4()),
        username="executor",
        role="ADMIN",
        session_id=None,
    )


def _make_asset(session_id=None, status="STAGED"):
    """Build an Asset ORM object."""
    sid = session_id or uuid.uuid4()
    return Asset(
        id=uuid.uuid4(),
        session_id=sid,
        title="Test Asset",
        description="A test asset",
        category="Furniture",
        valuation_min=100.0,
        valuation_max=500.0,
        valuation_source="Appraisal",
        sentiment_tag="Memento",
        image_uri=f"static/uploads/{uuid.uuid4()}.webp",
        audio_uri=None,
        ocr_status="COMPLETED",
        status=status,
    )


def _make_session(status="SETUP"):
    """Build a Session ORM object."""
    return SessionModel(
        id=uuid.uuid4(),
        title="Test Estate",
        status=status,
        is_paused=False,
        is_deadlocked=False,
    )


# ---------------------------------------------------------------------------
# DELETE /api/assets/{asset_id}
# ---------------------------------------------------------------------------


class TestAssetDeletion:
    """DELETE /api/assets/{asset_id} — asset deletion with session gate."""

    def test_delete_requires_auth(self, client, mock_db_session, test_env):
        """Unauthenticated request must return 401."""
        resp = client.delete(f"/api/assets/{uuid.uuid4()}")
        assert resp.status_code == 401

    def test_delete_requires_admin(self, client, mock_db_session, test_env):
        """HEIR token must return 403."""
        heir_token = create_access_token(
            user_id=str(uuid.uuid4()),
            username="heir_bob",
            role="HEIR",
            session_id=str(uuid.uuid4()),
        )
        resp = client.delete(
            f"/api/assets/{uuid.uuid4()}",
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_delete_success_in_setup(self, client, mock_db_session, test_env):
        """Deletion succeeds when session is in SETUP status."""
        token = _make_admin_token()
        session = _make_session(status="SETUP")
        asset = _make_asset(session_id=session.id, status="STAGED")

        # Configure mock: first query returns asset, second returns session
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        resp = client.delete(
            f"/api/assets/{asset.id}",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "deleted" in data["message"].lower()
        mock_db_session.commit.assert_called_once()

    def test_delete_nonexistent_asset_returns_404(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        resp = client.delete(
            f"/api/assets/{uuid.uuid4()}",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 404

    def test_delete_blocked_in_active(self, client, mock_db_session, test_env):
        """Deletion returns 400 when session is ACTIVE."""
        token = _make_admin_token()
        session = _make_session(status="ACTIVE")
        asset = _make_asset(session_id=session.id)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        resp = client.delete(
            f"/api/assets/{asset.id}",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 400
        assert "SETUP" in resp.json()["detail"]

    def test_delete_blocked_in_locked(self, client, mock_db_session, test_env):
        """Deletion returns 400 when session is LOCKED."""
        token = _make_admin_token()
        session = _make_session(status="LOCKED")
        asset = _make_asset(session_id=session.id)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        resp = client.delete(
            f"/api/assets/{asset.id}",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 400

    def test_delete_blocked_in_finalized(self, client, mock_db_session, test_env):
        """Deletion returns 400 when session is FINALIZED."""
        token = _make_admin_token()
        session = _make_session(status="FINALIZED")
        asset = _make_asset(session_id=session.id)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        resp = client.delete(
            f"/api/assets/{asset.id}",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 400

    def test_delete_calls_storage_delete_for_image(self, client, mock_db_session, test_env):
        """Verify that storage.delete() is called for the image file."""
        token = _make_admin_token()
        session = _make_session(status="SETUP")
        asset = _make_asset(session_id=session.id, status="STAGED")

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        with mock.patch("app.main.get_storage_driver") as mock_storage:
            mock_driver = mock.MagicMock()
            mock_storage.return_value = mock_driver

            resp = client.delete(
                f"/api/assets/{asset.id}",
                cookies={"estate_session": token},
            )
            assert resp.status_code == 200
            mock_driver.delete.assert_called_with(asset.image_uri)