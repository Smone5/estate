"""
Tests for Multiple Asset Images.

Covers:
- POST /api/sessions/{session_id}/assets/stage (creates primary AssetImage)
- GET  /api/sessions/{session_id}/assets (serializes images list)
- POST /api/assets/{asset_id}/images (adds supplementary image)
- DELETE /api/assets/{asset_id}/images/{image_id} (deletes supplementary image)
- DELETE /api/assets/{asset_id} (cascade cleans up files)
"""

import io
import uuid
from unittest import mock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession
from PIL import Image as PILImage

from app.models import Session as SessionModel, Asset, AssetImage
from app.auth import get_current_admin, get_current_user


SESSION_ID = uuid.uuid4()
ASSET_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()
HEIR_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-multiple-images")
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


def _build_session(status="SETUP"):
    return SessionModel(
        id=SESSION_ID,
        title="Test Estate",
        status=status,
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
        ocr_status="PROCESSING",
        status="STAGED",
    )


def _make_fake_webp_image() -> bytes:
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
        
        mock_storage = mock.MagicMock()
        mock_storage.save = mock.MagicMock(return_value="static/uploads/test.webp")
        mock_storage.get = mock.MagicMock(return_value=b"test")
        mock_storage.delete = mock.MagicMock()
        mock_storage_driver.return_value = mock_storage

        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client, mock_db, mock_storage

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test Staging and Listing
# ---------------------------------------------------------------------------

class TestMultipleAssetImages:

    def test_stage_creates_primary_asset_image(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="SETUP")

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

        # Verify that the Asset and primary AssetImage were added to DB
        # (a third call adds the ASSET_CREATED AuditLog entry).
        assert mock_db.add.call_count == 3
        calls = mock_db.add.call_args_list
        assert isinstance(calls[0][0][0], Asset)
        assert isinstance(calls[1][0][0], AssetImage)
        assert calls[1][0][0].is_primary is True
        assert calls[1][0][0].angle_label == "Primary"

    def test_list_assets_serializes_images(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="ACTIVE")
        asset = _build_staged_asset()
        
        image = AssetImage(
            id=uuid.uuid4(),
            asset_id=ASSET_ID,
            image_uri="static/uploads/primary.webp",
            is_primary=True,
            angle_label="Primary"
        )
        asset.images = [image]

        mock_query = mock.MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = session
        mock_query.all.return_value = [asset]
        mock_db.query.return_value = mock_query

        resp = test_client.get(f"/api/sessions/{SESSION_ID}/assets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert "images" in data[0]
        assert len(data[0]["images"]) == 1
        assert data[0]["images"][0]["image_uri"] == "static/uploads/primary.webp"
        assert data[0]["images"][0]["is_primary"] is True
        assert data[0]["images"][0]["angle_label"] == "Primary"

    def test_add_asset_image_success(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="SETUP")
        asset = _build_staged_asset()

        # Mock the queries: first query retrieves the asset, second retrieves the session
        first_results = [asset, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect
        mock_db.add = mock.MagicMock()

        image_bytes = _make_fake_webp_image()
        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/images",
            data={"angle_label": "Back view"},
            files={"file": ("back.webp", io.BytesIO(image_bytes), "image/webp")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["is_primary"] is False
        assert data["angle_label"] == "Back view"
        assert "static/uploads/" in data["image_uri"]
        
        # Verify added to database
        mock_db.add.assert_called_once()
        added_img = mock_db.add.call_args[0][0]
        assert isinstance(added_img, AssetImage)
        assert added_img.is_primary is False
        assert added_img.angle_label == "Back view"

    def test_add_asset_image_fails_if_not_setup(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="ACTIVE")
        asset = _build_staged_asset()

        first_results = [asset, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        image_bytes = _make_fake_webp_image()
        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/images",
            data={"angle_label": "Back view"},
            files={"file": ("back.webp", io.BytesIO(image_bytes), "image/webp")},
        )
        assert resp.status_code == 400
        assert "SETUP" in resp.json()["detail"]

    def test_delete_supplementary_image_success(self, client):
        test_client, mock_db, mock_storage = client
        session = _build_session(status="SETUP")
        asset = _build_staged_asset()
        
        img = AssetImage(
            id=uuid.uuid4(),
            asset_id=ASSET_ID,
            image_uri="static/uploads/secondary.webp",
            is_primary=False,
            angle_label="Detail"
        )

        first_results = [asset, session, img]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        resp = test_client.delete(f"/api/assets/{ASSET_ID}/images/{img.id}")
        assert resp.status_code == 200
        mock_storage.delete.assert_called_with("static/uploads/secondary.webp")
        mock_db.delete.assert_called_with(img)

    def test_delete_primary_image_fails(self, client):
        test_client, mock_db, _ = client
        session = _build_session(status="SETUP")
        asset = _build_staged_asset()
        
        img = AssetImage(
            id=uuid.uuid4(),
            asset_id=ASSET_ID,
            image_uri="static/uploads/primary.webp",
            is_primary=True,
            angle_label="Primary"
        )

        first_results = [asset, session, img]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        resp = test_client.delete(f"/api/assets/{ASSET_ID}/images/{img.id}")
        assert resp.status_code == 400
        assert "primary" in resp.json()["detail"].lower()

    def test_replace_asset_image_success(self, client):
        test_client, mock_db, mock_storage = client
        session = _build_session(status="SETUP")
        asset = _build_staged_asset()

        img = AssetImage(
            id=uuid.uuid4(),
            asset_id=ASSET_ID,
            image_uri="static/uploads/secondary-old.webp",
            is_primary=False,
            angle_label="Detail",
        )

        first_results = [asset, session, img]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect

        image_bytes = _make_fake_webp_image()
        resp = test_client.post(
            f"/api/assets/{ASSET_ID}/images/{img.id}/replace",
            files={"file": ("edited.webp", io.BytesIO(image_bytes), "image/webp")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["image_id"] == str(img.id)
        assert data["is_primary"] is False
        assert data["angle_label"] == "Detail"
        assert data["image_uri"].startswith("static/uploads/")
        assert img.image_uri == data["image_uri"]
        mock_storage.save.assert_called_once()
        mock_storage.delete.assert_called_with("static/uploads/secondary-old.webp")

    def test_delete_asset_cascade_cleans_storage_files(self, client):
        test_client, mock_db, mock_storage = client
        session = _build_session(status="SETUP")
        asset = _build_staged_asset()
        
        img1 = AssetImage(
            id=uuid.uuid4(),
            asset_id=ASSET_ID,
            image_uri="static/uploads/primary.webp",
            is_primary=True,
            angle_label="Primary"
        )
        img2 = AssetImage(
            id=uuid.uuid4(),
            asset_id=ASSET_ID,
            image_uri="static/uploads/secondary.webp",
            is_primary=False,
            angle_label="Detail"
        )
        asset.images = [img1, img2]

        first_results = [asset, session]

        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect
        # The endpoint re-fetches session then asset under a row lock
        # (with_for_update) before deleting — return the same objects.
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.first.side_effect = [session, asset]

        resp = test_client.delete(f"/api/assets/{ASSET_ID}")
        assert resp.status_code == 200

        # Verify both images were deleted from storage
        delete_calls = [c[0][0] for c in mock_storage.delete.call_args_list]
        assert "static/uploads/primary.webp" in delete_calls
        assert "static/uploads/secondary.webp" in delete_calls
        mock_db.delete.assert_called_with(asset)
