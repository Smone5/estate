"""
Tests for T31: Government ID Scan Upload API.
"""

import uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession
from cryptography.fernet import Fernet

from app.models import User
from app.auth import get_current_user


HEIR_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "t31-test-secret")
    # Fernet.generate_key() produces a valid 44-char url-safe base64 key
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("STORAGE_DRIVER", "MOCK")


def _make_heir_payload():
    return {
        "user_id": str(HEIR_ID),
        "username": "heir_test",
        "role": "HEIR",
        "session_id": str(SESSION_ID),
    }


def _build_heir():
    return User(
        id=HEIR_ID,
        session_id=SESSION_ID,
        username="heir_test",
        role="HEIR",
        status="PROFILE_HOLD",
        identity_verified=False,
        id_scan_uri=None,
    )


@pytest.fixture
def mock_db():
    return mock.MagicMock(spec=DBSession)


@pytest.fixture
def client(mock_db):
    from app.main import app

    app.dependency_overrides[get_current_user] = _make_heir_payload

    with mock.patch("app.main.SessionLocal", return_value=mock_db), \
         mock.patch("app.main.limiter.limit", lambda rate: lambda f: f), \
         mock.patch("app.main.get_storage_driver") as mock_storage:
        mock_sd = mock.MagicMock()
        mock_sd.save = mock.MagicMock()
        mock_storage.return_value = mock_sd

        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client, mock_db, mock_sd

    app.dependency_overrides.clear()


class TestUploadIdScan:

    def test_upload_id_success(self, client):
        test_client, mock_db, mock_sd = client
        heir = _build_heir()
        mock_db.query.return_value.filter.return_value.first.return_value = heir

        resp = test_client.post(
            "/api/heirs/me/upload-id",
            files={"file": ("id.jpg", b"fake-id-bytes", "image/jpeg")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "encrypted" in data["message"].lower()

        # Verify storage was called
        mock_sd.save.assert_called_once()
        # Verify heir state updated
        assert heir.id_scan_uri is not None
        assert heir.identity_verified is False
        mock_db.commit.assert_called()

    def test_upload_id_no_file_returns_400(self, client):
        test_client, mock_db, _ = client
        heir = _build_heir()
        mock_db.query.return_value.filter.return_value.first.return_value = heir

        resp = test_client.post("/api/heirs/me/upload-id")
        assert resp.status_code == 400

    def test_upload_id_admin_rejected_403(self, client):
        test_client, mock_db, _ = client
        mock_db.query.return_value.filter.return_value.first.return_value = _build_heir()

        from app.main import app
        from app.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": str(HEIR_ID),
            "username": "admin",
            "role": "ADMIN",
            "session_id": None,
        }
        resp = test_client.post(
            "/api/heirs/me/upload-id",
            files={"file": ("id.jpg", b"fake", "image/jpeg")},
        )
        assert resp.status_code == 403