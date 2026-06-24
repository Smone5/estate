"""
Tests for Post-Publish Asset Revision & Batch Updates.
"""

import io
import uuid
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession
from PIL import Image as PILImage

from app.models import Session as SessionModel, User, Asset, AuditLog
from app.auth import get_current_admin, get_current_user


SESSION_ID = uuid.uuid4()
ASSET_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()
HEIR_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "revision-test-secret-key")
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)
    monkeypatch.setenv("STORAGE_DRIVER", "MOCK")


def _make_admin_payload():
    return {
        "user_id": str(ADMIN_ID),
        "username": "executor",
        "role": "ADMIN",
        "session_id": None,
    }


def _make_heir_payload():
    return {
        "user_id": str(HEIR_ID),
        "username": "heir_test",
        "role": "HEIR",
        "session_id": str(SESSION_ID),
    }


def _build_session(status="ACTIVE"):
    return SessionModel(
        id=SESSION_ID,
        title="Test Estate",
        status=status,
        is_paused=False,
        is_deadlocked=False,
    )


def _build_asset(asset_id=ASSET_ID, status="LIVE"):
    return Asset(
        id=asset_id,
        session_id=SESSION_ID,
        title="Original Title",
        description="Original Description",
        category="Jewelry",
        valuation_min=100.0,
        valuation_max=200.0,
        valuation_source="Appraisal",
        sentiment_tag="heirloom",
        status=status,
        ocr_status="COMPLETED",
    )


def _make_fake_webp_image() -> bytes:
    """Create a minimal in-memory RGB WebP image for testing."""
    img = PILImage.new("RGB", (100, 100), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80)
    return buf.getvalue()


@pytest.fixture
def mock_db():
    db = mock.MagicMock(spec=DBSession)
    # Enable chaining for database queries
    mock_query = db.query.return_value
    mock_filter = mock_query.filter.return_value
    mock_filter.with_for_update.return_value = mock_filter
    mock_filter.order_by.return_value = mock_filter
    mock_filter.all.return_value = []
    return db


@pytest.fixture
def client(mock_db):
    from app.main import app

    app.dependency_overrides[get_current_admin] = _make_admin_payload
    app.dependency_overrides[get_current_user] = _make_heir_payload

    async def _async_noop(*args, **kwargs):
        pass

    with mock.patch("app.main.SessionLocal", return_value=mock_db), \
         mock.patch("app.main.manager") as mock_mgr, \
         mock.patch("app.main.limiter.limit", lambda rate: lambda f: f), \
         mock.patch("app.main.get_provider") as mock_provider, \
         mock.patch("app.main.get_storage_driver") as mock_storage_driver, \
         mock.patch("app.services.smtp_service.send_email_background") as mock_email:
        
        mock_mgr.broadcast_session_status = mock.AsyncMock(side_effect=_async_noop)
        mock_storage = mock.MagicMock()
        mock_storage.save = mock.MagicMock(return_value="static/uploads/test.webp")
        mock_storage_driver.return_value = mock_storage

        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client, mock_db, mock_mgr, mock_email

    app.dependency_overrides.clear()


class TestAssetRevision:

    def test_stage_asset_allowed_in_active_phase(self, client):
        test_client, mock_db, _, _ = client
        session = _build_session(status="ACTIVE")

        # Mock: 1. check session status, 2. check existing asset, 3. get prev audit log hash
        mock_db.query.return_value.filter.return_value.first.side_effect = [session, None, None]
        mock_db.add = mock.MagicMock()

        img_bytes = _make_fake_webp_image()
        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/assets/stage",
            files={"file": ("test.webp", io.BytesIO(img_bytes), "image/webp")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "asset_id" in data
        assert data["status"] == "STAGED"

    def test_save_major_edit_requires_reason(self, client):
        test_client, mock_db, _, _ = client
        session = _build_session(status="ACTIVE")
        asset = _build_asset(status="LIVE")

        # Mock the asset query, session query, and lock queries
        mock_db.query.return_value.filter.return_value.first.side_effect = [asset, session, session, asset]

        # Payload modifies title (major edit) but lacks reason
        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/save",
            json={
                "title": "New Major Title",
                "description": "Original Description",
                "category": "Jewelry",
                "valuation_min": 100.0,
                "valuation_max": 200.0,
                "valuation_source": "Appraisal",
                "sentiment_tag": "heirloom",
            },
        )
        assert resp.status_code == 400
        assert "reason" in resp.json()["detail"].lower()

    def test_save_major_edit_success_with_reason(self, client):
        test_client, mock_db, _, _ = client
        session = _build_session(status="ACTIVE")
        asset = _build_asset(status="LIVE")

        # Mock query return: query for asset, query for session, session lock, asset lock, prev log (None)
        mock_db.query.return_value.filter.return_value.first.side_effect = [asset, session, session, asset, None]

        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/save",
            json={
                "title": "New Major Title",
                "description": "Original Description",
                "category": "Jewelry",
                "valuation_min": 100.0,
                "valuation_max": 200.0,
                "valuation_source": "Appraisal",
                "sentiment_tag": "heirloom",
                "reason": "Re-appraised by certified expert",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "Asset details saved successfully."
        
        # Verify db.add was called (for AuditLog and changes committed)
        mock_db.commit.assert_called()

    def test_save_minor_edit_does_not_require_reason(self, client):
        test_client, mock_db, _, _ = client
        session = _build_session(status="ACTIVE")
        asset = _build_asset(status="LIVE")

        # Mock query return: query for asset, query for session, session lock, asset lock, prev log (None)
        mock_db.query.return_value.filter.return_value.first.side_effect = [asset, session, session, asset, None]

        # Modifying only description (minor)
        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/save",
            json={
                "title": "Original Title",
                "description": "Updated minor description",
                "category": "Jewelry",
                "valuation_min": 100.0,
                "valuation_max": 200.0,
                "valuation_source": "Appraisal",
                "sentiment_tag": "heirloom",
            },
        )
        assert resp.status_code == 200
        mock_db.commit.assert_called()

    def test_delete_asset_requires_reason_in_active_phase(self, client):
        test_client, mock_db, _, _ = client
        session = _build_session(status="ACTIVE")
        asset = _build_asset(status="LIVE")

        mock_db.query.return_value.filter.return_value.first.side_effect = [asset, session]

        resp = test_client.delete(f"/api/assets/{ASSET_ID}")
        assert resp.status_code == 400
        assert "reason" in resp.json()["detail"].lower()

    def test_delete_asset_success_with_reason_and_resets_heirs(self, client):
        test_client, mock_db, _, _ = client
        session = _build_session(status="ACTIVE")
        asset = _build_asset(status="LIVE")
        heir = User(id=HEIR_ID, session_id=SESSION_ID, role="HEIR", status="SUBMITTED")

        # Mock queries: query for asset, query for session, session lock, asset lock, prev audit log (None)
        mock_db.query.return_value.filter.return_value.first.side_effect = [asset, session, session, asset, None]
        mock_db.query.return_value.filter.return_value.all.return_value = [heir]

        resp = test_client.delete(f"/api/assets/{ASSET_ID}?reason=Returned%20to%20rental%20shop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        
        # Heir status should be reset to ACTIVE
        assert heir.status == "ACTIVE"
        mock_db.commit.assert_called()

    def test_get_pending_updates_count(self, client):
        test_client, mock_db, _, _ = client
        log = AuditLog(
            id=1,
            session_id=SESSION_ID,
            event_type="ASSET_UPDATED",
            state_snapshot={"event": "ASSET_UPDATED", "notified": False},
            prev_hash="",
            sha256_hash=""
        )

        mock_db.query.return_value.filter.return_value.all.return_value = [log]

        resp = test_client.get(f"/api/sessions/{SESSION_ID}/pending-updates")
        assert resp.status_code == 200
        assert resp.json()["pending_count"] == 1

    def test_publish_updates_success_and_broadcasts(self, client):
        test_client, mock_db, mock_mgr, mock_email = client
        session = _build_session(status="ACTIVE")
        log = AuditLog(
            id=1,
            session_id=SESSION_ID,
            event_type="ASSET_UPDATED",
            state_snapshot={"event": "ASSET_UPDATED", "notified": False, "asset_title": "Vase", "reason": "Correction"},
            prev_hash="",
            sha256_hash=""
        )
        heir = User(id=HEIR_ID, session_id=SESSION_ID, role="HEIR", status="ACTIVE", email="heir@test.com")

        # Query calls:
        # 1. session lock query: returns session
        # 2. audit log query: returns [log]
        # 3. _log_asset_audit_event (queries log for prev_hash): returns None
        # 4. heirs query: returns [heir]
        mock_db.query.return_value.filter.return_value.first.side_effect = [session, None]
        mock_db.query.return_value.filter.return_value.all.side_effect = [[log], [heir]]

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/publish-updates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "modified" in data["summary"].lower()

        # Log notified status should be updated to True
        assert log.state_snapshot["notified"] is True

        # Email and WebSocket broadcast should be triggered
        mock_email.assert_called_once()
        mock_mgr.broadcast_session_status.assert_called_once_with(
            str(SESSION_ID),
            {
                "type": "inventory_updated",
                "summary": data["summary"],
                "session_status": "ACTIVE",
            }
        )
