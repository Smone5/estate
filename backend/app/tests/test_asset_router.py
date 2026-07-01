"""
Tests for T11: FastAPI Asset Router.

Covers:
- POST /api/sessions/{session_id}/assets/stage
- POST /api/assets/{asset_id}/publish
- GET  /api/sessions/{session_id}/assets
"""

import io
import uuid
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession
from PIL import Image as PILImage

from app.models import Session as SessionModel, User, Asset, Valuation
from app.auth import get_current_admin, get_current_user


SESSION_ID = uuid.uuid4()
ASSET_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()
HEIR_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "t11-test-secret-key")
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


def _build_staged_asset(asset_id=ASSET_ID):
    return Asset(
        id=asset_id,
        session_id=SESSION_ID,
        title=None,
        description=None,
        category=None,
        valuation_min=None,
        valuation_max=None,
        valuation_source=None,
        sentiment_tag=None,
        image_uri=f"static/uploads/{asset_id}.webp",
        audio_uri=None,
        ocr_status="PROCESSING",
        status="STAGED",
    )


def _build_active_heir(heir_id=HEIR_ID):
    return User(
        id=heir_id,
        session_id=SESSION_ID,
        username="heir_test",
        role="HEIR",
        pw_hash=None,
        status="ACTIVE",
    )


def _make_fake_webp_image() -> bytes:
    """Create a minimal in-memory RGB WebP image for testing."""
    img = PILImage.new("RGB", (100, 100), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=80)
    return buf.getvalue()


@pytest.fixture
def mock_db():
    return mock.MagicMock(spec=DBSession)


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
         mock.patch("app.main.get_storage_driver") as mock_storage_driver:
        mock_mgr.broadcast_session_status = mock.AsyncMock(side_effect=_async_noop)
        mock_mgr.broadcast_announcement = mock.AsyncMock(side_effect=_async_noop)
        mock_mgr.broadcast_asset_ocr_completed = mock.AsyncMock(side_effect=_async_noop)

        mock_provider.return_value.get_embeddings = mock.MagicMock(
            return_value=[0.1] * 768
        )

        mock_storage = mock.MagicMock()
        mock_storage.save = mock.MagicMock(return_value="static/uploads/test.webp")
        mock_storage.get = mock.MagicMock(return_value=b"test")
        mock_storage.delete = mock.MagicMock()
        mock_storage_driver.return_value = mock_storage

        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client, mock_db, mock_mgr, mock_provider, mock_storage

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/assets/stage
# ---------------------------------------------------------------------------


class TestAssetStage:

    def test_stage_success_returns_201(self, client):
        test_client, mock_db, *_ = client
        session = _build_session(status="SETUP")

        # Use a list so we can pop in order: session, then add
        first_results = [session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect
        mock_db.add = mock.MagicMock()

        image_bytes = _make_fake_webp_image()
        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/assets/stage",
            files={"file": ("test.webp", io.BytesIO(image_bytes), "image/webp")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "asset_id" in data
        assert data["status"] == "STAGED"
        assert data["ocr_status"] == "PROCESSING"

    def test_stage_no_file_returns_400(self, client):
        test_client, mock_db, *_ = client
        session = _build_session(status="SETUP")
        mock_db.query.return_value.filter.return_value.first.return_value = session

        resp = test_client.post(f"/api/sessions/{SESSION_ID}/assets/stage")
        assert resp.status_code == 400

    def test_stage_not_setup_returns_400(self, client):
        """Staging is allowed in SETUP or ACTIVE, but rejected once LOCKED."""
        test_client, mock_db, *_ = client
        session = _build_session(status="LOCKED")
        mock_db.query.return_value.filter.return_value.first.return_value = session

        image_bytes = _make_fake_webp_image()
        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/assets/stage",
            files={"file": ("test.webp", io.BytesIO(image_bytes), "image/webp")},
        )
        assert resp.status_code == 400
        assert "SETUP" in resp.json()["detail"]

    def test_stage_session_not_found_returns_404(self, client):
        test_client, mock_db, *_ = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        image_bytes = _make_fake_webp_image()
        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/assets/stage",
            files={"file": ("test.webp", io.BytesIO(image_bytes), "image/webp")},
        )
        assert resp.status_code == 404

    def test_stage_with_custom_asset_id_and_location(self, client):
        test_client, mock_db, *_ = client
        session = _build_session(status="SETUP")

        # Mock session query first, then existing asset check returns None
        mock_db.query.return_value.filter.return_value.first.side_effect = [session, None]
        mock_db.add = mock.MagicMock()

        image_bytes = _make_fake_webp_image()
        custom_uuid = uuid.uuid4()
        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/assets/stage",
            data={
                "asset_id": str(custom_uuid),
                "location": "Living Room",
                "auto_appraise": "false",
            },
            files={"file": ("test.webp", io.BytesIO(image_bytes), "image/webp")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["asset_id"] == str(custom_uuid)
        assert data["status"] == "STAGED"
        assert data["ocr_status"] == "COMPLETED"

    def test_stage_idempotency_existing_asset(self, client):
        test_client, mock_db, *_ = client
        session = _build_session(status="SETUP")
        asset = _build_staged_asset(asset_id=ASSET_ID)

        # Mock session query first, then existing asset check returns existing asset
        mock_db.query.return_value.filter.return_value.first.side_effect = [session, asset]

        image_bytes = _make_fake_webp_image()
        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/assets/stage",
            data={"asset_id": str(ASSET_ID)},
            files={"file": ("test.webp", io.BytesIO(image_bytes), "image/webp")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_id"] == str(ASSET_ID)

    def test_stage_with_audio_file(self, client):
        test_client, mock_db, *_ = client
        session = _build_session(status="SETUP")

        mock_db.query.return_value.filter.return_value.first.side_effect = [session, None]
        mock_db.add = mock.MagicMock()

        image_bytes = _make_fake_webp_image()
        audio_bytes = b"fake-audio-payload"

        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/assets/stage",
            data={"auto_appraise": "false"},
            files={
                "file": ("test.webp", io.BytesIO(image_bytes), "image/webp"),
                "audio": ("voice.webm", io.BytesIO(audio_bytes), "audio/webm"),
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "asset_id" in data
        assert data["status"] == "STAGED"


class TestBackgroundTasks:

    @pytest.mark.asyncio
    async def test_analyze_staged_asset_background_success(self):
        from app.main import analyze_staged_asset_background, Asset
        
        mock_db = mock.MagicMock(spec=DBSession)
        asset = Asset(
            id=ASSET_ID,
            session_id=SESSION_ID,
            image_uri="static/uploads/test.webp",
            ocr_status="PROCESSING",
            images=[],
            audio_uri="static/uploads/audio.wav",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = asset
        
        mock_provider = mock.MagicMock()
        mock_provider.generate_vision.return_value = '{"title": "Antique Chair", "item_overview": "Nice chair", "specifications": "- Wood\\n- Brown", "condition_report": "Good", "keywords": "chair, vintage", "valuation_min": 100, "valuation_max": 200, "sentiment_tags": "Heirloom", "valuation_confidence": "Medium"}'
        mock_provider.get_embeddings.return_value = [0.1] * 768
        
        mock_storage = mock.MagicMock()
        mock_storage.get.return_value = b"fake-image"
        
        with mock.patch("app.main._get_session_factory") as mock_factory, \
             mock.patch("app.main.get_provider", return_value=mock_provider), \
             mock.patch("app.main.get_storage_driver", return_value=mock_storage), \
             mock.patch("app.main.manager") as mock_mgr:
            
            mock_factory.return_value = mock.MagicMock(return_value=mock_db)
            mock_mgr.broadcast_asset_ocr_completed = mock.AsyncMock()
            
            await analyze_staged_asset_background(str(ASSET_ID), str(SESSION_ID), "Living Room")
            
            assert asset.title == "Antique Chair"
            assert asset.ocr_status == "COMPLETED"
            mock_db.commit.assert_called()
            mock_mgr.broadcast_asset_ocr_completed.assert_called_once()

    def test_cleanup_stuck_ocr_tasks(self):
        from app.main import cleanup_stuck_ocr_tasks, Asset
        mock_db = mock.MagicMock(spec=DBSession)
        asset = Asset(
            id=ASSET_ID,
            session_id=SESSION_ID,
            ocr_status="PROCESSING",
            description_json=None,
        )
        mock_db.query.return_value.filter.return_value.all.return_value = [asset]
        
        with mock.patch("app.main._get_session_factory") as mock_factory:
            mock_factory.return_value = mock.MagicMock(return_value=mock_db)
            cleanup_stuck_ocr_tasks()
            
            assert asset.ocr_status == "FAILED"
            assert "Task interrupted" in asset.description_json
            mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/assets/{asset_id}/publish
# ---------------------------------------------------------------------------


class TestAssetPublish:

    def test_publish_success_returns_200(self, client):
        test_client, mock_db, mock_mgr, mock_provider, mock_storage = client
        session = _build_session(status="SETUP")
        asset = _build_staged_asset()

        first_results = [asset, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect
        mock_db.query.return_value.filter.return_value.all.return_value = []
        # The endpoint re-fetches session then asset under a row lock
        # (with_for_update) before applying edits — return the same objects.
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.side_effect = [session, asset]

        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/publish",
            json={
                "title": "Vintage Watch",
                "description": "A gold pocket watch from 1920.",
                "category": "Jewelry",
                "valuation_min": 500.0,
                "valuation_max": 1500.0,
                "valuation_source": "Appraisal by Smith & Co.",
                "sentiment_tag": "heirloom",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_id"] == str(ASSET_ID)
        assert data["status"] == "LIVE"

    def test_publish_missing_required_fields_returns_400(self, client):
        test_client, mock_db, *_ = client
        asset = _build_staged_asset()

        first_results = [asset, _build_session(status="SETUP")]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/publish",
            json={
                "title": "Watch",
                "description": "Nice watch",
                "category": "Jewelry",
                "valuation_min": 100.0,
                "valuation_max": 500.0,
                "valuation_source": None,  # Missing
                "sentiment_tag": "heirloom",
            },
        )
        assert resp.status_code == 400
        assert "valuation_source" in resp.json()["detail"]

    def test_publish_asset_not_found_returns_404(self, client):
        test_client, mock_db, *_ = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/publish",
            json={
                "title": "Watch",
                "description": "Nice watch",
                "category": "Jewelry",
                "valuation_min": 100.0,
                "valuation_max": 500.0,
                "valuation_source": "Appraisal",
                "sentiment_tag": "heirloom",
            },
        )
        assert resp.status_code == 404

    def test_publish_not_staged_returns_400(self, client):
        test_client, mock_db, *_ = client
        asset = _build_staged_asset()
        asset.status = "LIVE"

        first_results = [asset, _build_session(status="SETUP")]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/publish",
            json={
                "title": "Watch",
                "description": "Nice watch",
                "category": "Jewelry",
                "valuation_min": 100.0,
                "valuation_max": 500.0,
                "valuation_source": "Appraisal",
                "sentiment_tag": "heirloom",
            },
        )
        assert resp.status_code == 400

    def test_publish_session_not_setup_returns_400(self, client):
        """Publishing is allowed in SETUP or ACTIVE, but rejected once LOCKED."""
        test_client, mock_db, *_ = client
        asset = _build_staged_asset()
        session = _build_session(status="LOCKED")

        first_results = [asset, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/publish",
            json={
                "title": "Watch",
                "description": "Nice watch",
                "category": "Jewelry",
                "valuation_min": 100.0,
                "valuation_max": 500.0,
                "valuation_source": "Appraisal",
                "sentiment_tag": "heirloom",
            },
        )
        assert resp.status_code == 400
        assert "SETUP" in resp.json()["detail"]

    def test_publish_seeds_valuations_for_active_heirs(self, client):
        test_client, mock_db, mock_mgr, mock_provider, mock_storage = client
        asset = _build_staged_asset()
        session = _build_session(status="SETUP")
        heir = _build_active_heir()

        first_results = [asset, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect
        # Mock the active heirs query
        mock_db.query.return_value.filter.return_value.all.return_value = [heir]
        # The endpoint re-fetches session then asset under a row lock
        # (with_for_update) before applying edits — return the same objects.
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.side_effect = [session, asset]
        mock_db.add = mock.MagicMock()

        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/publish",
            json={
                "title": "Vintage Watch",
                "description": "A gold pocket watch from 1920.",
                "category": "Jewelry",
                "valuation_min": 500.0,
                "valuation_max": 1500.0,
                "valuation_source": "Appraisal by Smith & Co.",
                "sentiment_tag": "heirloom",
            },
        )
        assert resp.status_code == 200
        # Verify commit was called (which includes the valuation inserts)
        mock_db.commit.assert_called()

    def test_publish_all_fields_missing_returns_400_with_all_reported(self, client):
        test_client, mock_db, *_ = client
        asset = _build_staged_asset()
        session = _build_session(status="SETUP")

        first_results = [asset, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        # category pattern is enforced by Pydantic (422), so use a valid
        # value and let the endpoint validation gate catch the rest.
        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/publish",
            json={
                "title": "",
                "description": "",
                "category": "Jewelry",
                "valuation_source": None,
                "sentiment_tag": None,
            },
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "title" in detail
        assert "description" in detail
        assert "valuation_source" in detail
        assert "sentiment_tag" in detail


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id}/assets
# ---------------------------------------------------------------------------


class TestSessionAssets:

    def test_list_assets_success(self, client):
        test_client, mock_db, *_ = client
        session = _build_session(status="ACTIVE")
        asset1 = Asset(
            id=uuid.uuid4(),
            session_id=SESSION_ID,
            title="Watch",
            description="Gold watch",
            category="Jewelry",
            status="LIVE",
            image_uri="static/uploads/a.webp",
        )
        asset2 = Asset(
            id=uuid.uuid4(),
            session_id=SESSION_ID,
            title="Chair",
            description="Antique chair",
            category="Furniture",
            status="LIVE",
            image_uri="static/uploads/b.webp",
        )

        # Build a self-propagating mock query chain so that all .filter(),
        # .join(), .order_by(), .ilike() calls return the same mock, and
        # terminal calls (.first(), .all()) return the correct values.
        mock_query = mock.MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.ilike.return_value = mock_query
        mock_query.notin_.return_value = mock_query
        mock_query.first.return_value = session
        mock_query.all.return_value = [asset1, asset2]
        mock_db.query.return_value = mock_query

        resp = test_client.get(f"/api/sessions/{SESSION_ID}/assets")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 2

    def test_list_assets_session_not_found_returns_404(self, client):
        test_client, mock_db, *_ = client
        mock_query = mock.MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None
        mock_db.query.return_value = mock_query

        resp = test_client.get(f"/api/sessions/{SESSION_ID}/assets")
        assert resp.status_code == 404

    def test_list_assets_with_category_filter(self, client):
        test_client, mock_db, *_ = client
        session = _build_session(status="ACTIVE")
        asset = Asset(
            id=uuid.uuid4(),
            session_id=SESSION_ID,
            title="Watch",
            description="Gold watch",
            category="Jewelry",
            status="LIVE",
            image_uri="static/uploads/a.webp",
        )

        mock_query = mock.MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.in_.return_value = True
        mock_query.first.return_value = session
        mock_query.all.return_value = [asset]
        mock_db.query.return_value = mock_query

        resp = test_client.get(
            f"/api/sessions/{SESSION_ID}/assets",
            params={"category": "Jewelry"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1

    def test_list_assets_with_search_query(self, client):
        test_client, mock_db, *_ = client
        session = _build_session(status="ACTIVE")
        asset = Asset(
            id=uuid.uuid4(),
            session_id=SESSION_ID,
            title="Vintage Watch",
            description="Antique gold",
            category="Jewelry",
            status="LIVE",
            image_uri="static/uploads/a.webp",
        )

        mock_query = mock.MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.ilike.return_value = True
        mock_query.first.return_value = session
        mock_query.all.return_value = [asset]
        mock_db.query.return_value = mock_query

        resp = test_client.get(
            f"/api/sessions/{SESSION_ID}/assets",
            params={"q": "vintage"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1


# ---------------------------------------------------------------------------
# POST /api/assets/{asset_id}/save
# ---------------------------------------------------------------------------


class TestAssetSave:

    def test_save_success_returns_200(self, client):
        test_client, mock_db, mock_mgr, mock_provider, mock_storage = client
        asset = _build_staged_asset()
        session = _build_session(status="SETUP")

        first_results = [asset, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect
        # The endpoint re-fetches session then asset under a row lock
        # (with_for_update) before applying edits — return the same objects.
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.side_effect = [session, asset]

        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/save",
            json={
                "title": "Vintage Watch Draft",
                "description": "Draft description.",
                "category": "Jewelry",
                "valuation_min": 400.0,
                "valuation_max": None,
                "valuation_source": "Personal Estimate",
                "sentiment_tag": None,
                "specifications": "Specs text",
                "condition_report": "Mint",
                "keywords": "watch, gold",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_id"] == str(ASSET_ID)
        assert data["status"] == "STAGED"
        assert data["message"] == "Asset details saved successfully."

        assert asset.title == "Vintage Watch Draft"
        assert asset.description == "Draft description."
        assert asset.valuation_min == 400.0
        assert asset.valuation_max is None

    def test_save_asset_not_found_returns_404(self, client):
        test_client, mock_db, *_ = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/save",
            json={"title": "Draft"},
        )
        assert resp.status_code == 404

    def test_save_not_staged_returns_400(self, client):
        test_client, mock_db, *_ = client
        asset = _build_staged_asset()
        asset.status = "LIVE"

        mock_db.query.return_value.filter.return_value.first.return_value = asset

        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/save",
            json={"title": "Draft"},
        )
        assert resp.status_code == 400
