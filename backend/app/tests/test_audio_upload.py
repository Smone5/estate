"""
Tests for T41: Admin Audio Story Upload & Delete API.

Covers:
- POST /api/assets/{asset_id}/audio  (audio upload)
- DELETE /api/assets/{asset_id}/audio  (audio deletion)
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


def _make_asset(session_id=None, audio_uri=None):
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
        audio_uri=audio_uri,
        ocr_status="COMPLETED",
        status="STAGED",
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
# POST /api/assets/{asset_id}/audio
# ---------------------------------------------------------------------------


class TestAudioUpload:
    """POST /api/assets/{asset_id}/audio — upload audio story."""

    def test_upload_requires_auth(self, client, mock_db_session, test_env):
        resp = client.post(f"/api/assets/{uuid.uuid4()}/audio")
        assert resp.status_code == 401

    def test_upload_requires_admin(self, client, mock_db_session, test_env):
        heir_token = create_access_token(
            user_id=str(uuid.uuid4()),
            username="heir_bob",
            role="HEIR",
            session_id=str(uuid.uuid4()),
        )
        resp = client.post(
            f"/api/assets/{uuid.uuid4()}/audio",
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_upload_success_returns_200(self, client, mock_db_session, test_env):
        """Upload succeeds when session is SETUP."""
        token = _make_admin_token()
        session = _make_session(status="SETUP")
        asset = _make_asset(session_id=session.id)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        with mock.patch("app.main.get_storage_driver") as mock_storage:
            mock_driver = mock.MagicMock()
            mock_storage.return_value = mock_driver

            fake_audio = b"\x00\x01\x02\x03" * 100  # small fake audio bytes
            resp = client.post(
                f"/api/assets/{asset.id}/audio",
                files={"file": ("test.webm", fake_audio, "audio/webm")},
                cookies={"estate_session": token},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "success"
            assert "audio_uri" in data
            assert data["audio_uri"].startswith("static/uploads/")
            mock_db_session.commit.assert_called_once()

    def test_upload_updates_audio_uri(self, client, mock_db_session, test_env):
        """After upload, the asset's audio_uri should be set."""
        token = _make_admin_token()
        session = _make_session(status="SETUP")
        asset = _make_asset(session_id=session.id)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        with mock.patch("app.main.get_storage_driver"):
            fake_audio = b"test audio bytes"
            client.post(
                f"/api/assets/{asset.id}/audio",
                files={"file": ("test.webm", fake_audio, "audio/webm")},
                cookies={"estate_session": token},
            )
            # audio_uri should have been updated on the asset object
            assert asset.audio_uri is not None
            assert "static/uploads/" in asset.audio_uri

    def test_upload_blocked_in_active(self, client, mock_db_session, test_env):
        """Upload returns 400 when session is ACTIVE."""
        token = _make_admin_token()
        session = _make_session(status="ACTIVE")
        asset = _make_asset(session_id=session.id)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        fake_audio = b"test audio bytes"
        resp = client.post(
            f"/api/assets/{asset.id}/audio",
            files={"file": ("test.webm", fake_audio, "audio/webm")},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 400

    def test_upload_nonexistent_asset_returns_404(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        fake_audio = b"test audio bytes"
        resp = client.post(
            f"/api/assets/{uuid.uuid4()}/audio",
            files={"file": ("test.webm", fake_audio, "audio/webm")},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 404

    def test_upload_missing_file_returns_400(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        session = _make_session(status="SETUP")
        asset = _make_asset(session_id=session.id)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        resp = client.post(
            f"/api/assets/{asset.id}/audio",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/assets/{asset_id}/audio
# ---------------------------------------------------------------------------


class TestAudioDeletion:
    """DELETE /api/assets/{asset_id}/audio — remove audio story."""

    def test_delete_requires_auth(self, client, mock_db_session, test_env):
        resp = client.delete(f"/api/assets/{uuid.uuid4()}/audio")
        assert resp.status_code == 401

    def test_delete_requires_admin(self, client, mock_db_session, test_env):
        heir_token = create_access_token(
            user_id=str(uuid.uuid4()),
            username="heir_bob",
            role="HEIR",
            session_id=str(uuid.uuid4()),
        )
        resp = client.delete(
            f"/api/assets/{uuid.uuid4()}/audio",
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_delete_success_returns_200(self, client, mock_db_session, test_env):
        """Deletion succeeds when session is SETUP and audio_uri exists."""
        token = _make_admin_token()
        session = _make_session(status="SETUP")
        asset = _make_asset(
            session_id=session.id,
            audio_uri="static/uploads/test-audio.webm",
        )

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        with mock.patch("app.main.get_storage_driver") as mock_storage:
            mock_driver = mock.MagicMock()
            mock_storage.return_value = mock_driver

            resp = client.delete(
                f"/api/assets/{asset.id}/audio",
                cookies={"estate_session": token},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "success"
            assert "deleted" in data["message"].lower()
            assert asset.audio_uri is None
            mock_driver.delete.assert_called_once()

    def test_delete_nullifies_audio_uri(self, client, mock_db_session, test_env):
        """After deletion, audio_uri should be set to None."""
        token = _make_admin_token()
        session = _make_session(status="SETUP")
        asset = _make_asset(
            session_id=session.id,
            audio_uri="static/uploads/test-audio.webm",
        )

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        with mock.patch("app.main.get_storage_driver"):
            client.delete(
                f"/api/assets/{asset.id}/audio",
                cookies={"estate_session": token},
            )
            assert asset.audio_uri is None

    def test_delete_no_audio_returns_404(self, client, mock_db_session, test_env):
        """Deleting audio when asset has no audio_uri returns 404."""
        token = _make_admin_token()
        session = _make_session(status="SETUP")
        asset = _make_asset(session_id=session.id, audio_uri=None)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        resp = client.delete(
            f"/api/assets/{asset.id}/audio",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 404

    def test_delete_blocked_in_active(self, client, mock_db_session, test_env):
        """Deletion returns 400 when session is ACTIVE."""
        token = _make_admin_token()
        session = _make_session(status="ACTIVE")
        asset = _make_asset(
            session_id=session.id,
            audio_uri="static/uploads/test-audio.webm",
        )

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        resp = client.delete(
            f"/api/assets/{asset.id}/audio",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 400