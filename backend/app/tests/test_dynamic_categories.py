"""
Tests for Staging UX Enhancements (T11 & Category Management).

Covers:
- GET /api/sessions/{session_id}/categories (listing & auto-seeding defaults)
- POST /api/sessions/{session_id}/categories (creating custom categories)
- DELETE /api/sessions/{session_id}/categories/{name} (deleting custom categories with locks)
- POST /api/sessions/{session_id}/assets/stage (multi-image staging)
- POST /api/assets/{asset_id}/generate-details (LLM vision details generation)
"""

import io
import uuid
from unittest import mock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession
from PIL import Image as PILImage

from app.models import Session as SessionModel, Asset, AssetImage, Category
from app.auth import get_current_admin, get_current_user


SESSION_ID = uuid.uuid4()
ASSET_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()
HEIR_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-dynamic-categories")
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

    with mock.patch("app.main.SessionLocal", return_value=mock_db), \
         mock.patch("app.main.limiter.limit", lambda rate: lambda f: f), \
         mock.patch("app.main.get_provider") as mock_provider, \
         mock.patch("app.main.get_storage_driver") as mock_storage_driver:
        
        mock_storage = mock.MagicMock()
        mock_storage.save = mock.MagicMock(return_value="static/uploads/test.webp")
        mock_storage.get = mock.MagicMock(return_value=b"test-image-bytes")
        mock_storage.delete = mock.MagicMock()
        mock_storage_driver.return_value = mock_storage

        # Setup mock LLM Provider
        mock_llm = mock.MagicMock()
        import json as json_mod
        mock_llm.generate_vision.return_value = json_mod.dumps({
            "title": "Beautiful Victorian Lamp",
            "item_overview": "An elegant antique brass lamp with a green glass shade.",
            "specifications": "- Brass base\n- Green glass shade",
            "condition_report": "Minor tarnish on base, otherwise excellent.",
            "keywords": "Victorian, Antique, Brass, Lamp, Green Glass",
        })
        mock_provider.return_value = mock_llm
        
        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client, mock_db, mock_storage, mock_llm
    
    app.dependency_overrides.clear()


# ===================================================================
# 1. Category Tests
# ===================================================================

class TestCategoryManagement:

    def test_get_categories_auto_seeds_defaults(self, client):
        test_client, mock_db, _, _ = client

        # Mock Category query to return empty first, then return seeded categories
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value
        
        cats = [
            Category(session_id=SESSION_ID, name="Jewelry"),
            Category(session_id=SESSION_ID, name="Furniture"),
            Category(session_id=SESSION_ID, name="Art"),
            Category(session_id=SESSION_ID, name="Other"),
        ]
        mock_filter.all.side_effect = [[], cats]

        resp = test_client.get(f"/api/sessions/{SESSION_ID}/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        assert "Jewelry" in data
        assert "Other" in data
        
        # Verify db.add was called to seed the 4 defaults
        assert mock_db.add.call_count == 4

    def test_create_category_success(self, client):
        test_client, mock_db, _, _ = client

        # Mock duplicate check to return None
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/categories",
            json={"name": "Books"},
        )
        assert resp.status_code == 201
        assert resp.json()["category"] == "Books"
        mock_db.add.assert_called_once()
        assert mock_db.add.call_args[0][0].name == "Books"

    def test_create_category_duplicate_fails(self, client):
        test_client, mock_db, _, _ = client

        # Mock duplicate check to find existing
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = Category(session_id=SESSION_ID, name="Books")

        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/categories",
            json={"name": "Books"},
        )
        assert resp.status_code == 400
        assert "exists" in resp.json()["detail"].lower()

    def test_delete_category_in_use_fails(self, client):
        test_client, mock_db, _, _ = client

        # Mock count of assets in this category to be > 0
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.count.return_value = 2

        resp = test_client.delete(f"/api/sessions/{SESSION_ID}/categories/Books")
        assert resp.status_code == 400
        assert "in use" in resp.json()["detail"].lower()

    def test_delete_category_success(self, client):
        test_client, mock_db, _, _ = client

        # Mock asset count = 0
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.count.return_value = 0
        
        # Mock finding category record
        cat = Category(session_id=SESSION_ID, name="Books")
        mock_filter.first.return_value = cat

        resp = test_client.delete(f"/api/sessions/{SESSION_ID}/categories/Books")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        mock_db.delete.assert_called_once_with(cat)


# ===================================================================
# 2. Multi-Image Staging Tests
# ===================================================================

class TestMultiImageStaging:

    def test_stage_multiple_images_success(self, client):
        test_client, mock_db, mock_storage, _ = client
        session = _build_session(status="SETUP")

        first_results = [session]
        def _first_side_effect(*args, **kwargs):
            return first_results.pop(0) if first_results else None

        mock_db.query.return_value.filter.return_value.first.side_effect = _first_side_effect
        mock_db.add = mock.MagicMock()

        img1 = _make_fake_webp_image()
        img2 = _make_fake_webp_image()
        img3 = _make_fake_webp_image()

        resp = test_client.post(
            f"/api/sessions/{SESSION_ID}/assets/stage",
            files=[
                ("files", ("img1.webp", io.BytesIO(img1), "image/webp")),
                ("files", ("img2.webp", io.BytesIO(img2), "image/webp")),
                ("files", ("img3.webp", io.BytesIO(img3), "image/webp")),
            ],
        )
        assert resp.status_code == 201
        
        # Verify db.add is called for:
        # - 1 Asset record
        # - 1 Primary AssetImage record
        # - 2 Secondary AssetImage records
        assert mock_db.add.call_count == 4
        calls = [call[0][0] for call in mock_db.add.call_args_list]
        
        assets = [c for c in calls if isinstance(c, Asset)]
        images = [c for c in calls if isinstance(c, AssetImage)]
        
        assert len(assets) == 1
        assert len(images) == 3
        
        primary_imgs = [i for i in images if i.is_primary]
        secondary_imgs = [i for i in images if not i.is_primary]
        
        assert len(primary_imgs) == 1
        assert len(secondary_imgs) == 2
        assert secondary_imgs[0].angle_label == "View 2"
        assert secondary_imgs[1].angle_label == "View 3"
        
        # Verify file storage saves
        assert mock_storage.save.call_count == 3


# ===================================================================
# 3. AI Detail Generation Tests
# ===================================================================

class TestAIDetailGeneration:

    def test_generate_details_success(self, client):
        test_client, mock_db, mock_storage, mock_llm = client
        asset = Asset(
            id=ASSET_ID,
            session_id=SESSION_ID,
            image_uri="static/uploads/lamp.webp",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = asset

        resp = test_client.post(f"/api/assets/{ASSET_ID}/generate-details")
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["title"] == "Beautiful Victorian Lamp"
        assert data["item_overview"] == "An elegant antique brass lamp with a green glass shade."
        assert data["specifications"] == "- Brass base\n- Green glass shade"
        assert data["condition_report"] == "Minor tarnish on base, otherwise excellent."
        assert data["keywords"] == "Victorian, Antique, Brass, Lamp, Green Glass"
        
        mock_storage.get.assert_called_once_with("static/uploads/lamp.webp")
        mock_llm.generate_vision.assert_called_once()
        assert "appraiser" in mock_llm.generate_vision.call_args[1]["prompt"]

    def test_save_ai_feedback_success(self, client):
        test_client, mock_db, _, _ = client
        asset = Asset(
            id=ASSET_ID,
            session_id=SESSION_ID,
            image_uri="static/uploads/lamp.webp",
            title="Beautiful Victorian Lamp",
            description="An elegant antique brass lamp with a green glass shade.",
            valuation_min=100.0,
            valuation_max=200.0,
            sentiment_tag="Antique",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = asset

        payload = {
            "rating": "thumbs_up",
            "comment": "Perfect description"
        }
        resp = test_client.post(f"/api/assets/{ASSET_ID}/ai-feedback", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        # Verify it was serialized and saved to asset.ai_feedback
        assert asset.ai_feedback is not None
        import json as json_mod
        saved = json_mod.loads(asset.ai_feedback)
        assert saved["rating"] == "thumbs_up"
        assert saved["comment"] == "Perfect description"
        assert saved["snapshot"]["title"] == "Beautiful Victorian Lamp"

    def test_save_ai_feedback_not_found(self, client):
        test_client, mock_db, _, _ = client
        mock_db.query.return_value.filter.return_value.first.return_value = None

        resp = test_client.post(f"/api/assets/{ASSET_ID}/ai-feedback", json={"rating": "thumbs_up"})
        assert resp.status_code == 404

