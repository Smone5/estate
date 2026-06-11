"""
Tests for Heir Profile Endpoints: GET /api/heirs/me and PUT /api/heirs/me/profile.
"""

import uuid
from datetime import datetime, timezone, date, timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.models import User, Session as SessionModel, AuditLog
from app.auth import get_current_user


HEIR_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "profile-test-secret")
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)
    monkeypatch.setenv("STORAGE_DRIVER", "MOCK")


def _make_heir_payload():
    return {
        "user_id": str(HEIR_ID),
        "username": "heir_test",
        "role": "HEIR",
        "session_id": str(SESSION_ID),
    }


def _build_heir(status="ACTIVE", verified=True, id_scan="identities/scan.enc"):
    return User(
        id=HEIR_ID,
        session_id=SESSION_ID,
        username="heir_test",
        role="HEIR",
        status=status,
        identity_verified=verified,
        id_scan_uri=id_scan,
        legal_first_name="Jane",
        legal_middle_name="Anne",
        legal_last_name="Doe",
        relationship_to_decedent="Daughter",
        date_of_birth=date(1990, 5, 15),
        email="jane@example.com",
        phone="555-0199",
        physical_address="123 Maple St",
    )


def _build_session(status="ACTIVE"):
    return SessionModel(
        id=SESSION_ID,
        title="Test Estate",
        status=status,
        is_paused=False,
        is_deadlocked=False,
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
         mock.patch("app.main.get_storage_driver") as mock_storage, \
         mock.patch("app.main.manager.broadcast_session_status", new_callable=mock.AsyncMock) as mock_broadcast:
        mock_sd = mock.MagicMock()
        mock_sd.delete = mock.MagicMock()
        mock_storage.return_value = mock_sd

        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client, mock_db, mock_sd, mock_broadcast

    app.dependency_overrides.clear()


class TestHeirProfileEndpoints:

    def test_get_heir_profile_success(self, client):
        test_client, mock_db, _, _ = client
        heir = _build_heir()
        mock_db.query.return_value.filter.return_value.first.return_value = heir

        resp = test_client.get("/api/heirs/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "heir_test"
        assert data["legal_first_name"] == "Jane"
        assert data["email"] == "jane@example.com"

    def test_update_heir_profile_non_legal_success(self, client):
        test_client, mock_db, mock_sd, mock_broadcast = client
        heir = _build_heir()
        session = _build_session()

        # Handle queries for User and SessionModel
        def mock_first(*args, **kwargs):
            # Inspect filter query
            q_str = str(mock_db.query.call_args)
            if "Session" in q_str:
                return session
            return heir

        mock_db.query.return_value.filter.return_value.first.side_effect = mock_first
        # last_log query returns None
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        payload = {
            "legal_first_name": "Jane",
            "legal_middle_name": "Anne",
            "legal_last_name": "Doe",
            "relationship_to_decedent": "Daughter",
            "date_of_birth": "1990-05-15",
            "email": "new_jane@example.com",
            "phone": "555-0200",
            "physical_address": "456 Oak Ave",
        }

        resp = test_client.put("/api/heirs/me/profile", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["identity_verified"] is True  # Didn't change legal fields

        assert heir.email == "new_jane@example.com"
        assert heir.phone == "555-0200"
        assert heir.physical_address == "456 Oak Ave"
        assert heir.id_scan_uri == "identities/scan.enc"  # ID scan preserved

        mock_db.add.assert_called()
        mock_db.commit.assert_called()
        mock_broadcast.assert_called_once()

    def test_update_heir_profile_legal_change_purges_scan(self, client):
        test_client, mock_db, mock_sd, mock_broadcast = client
        heir = _build_heir()
        session = _build_session()

        def mock_first(*args, **kwargs):
            q_str = str(mock_db.query.call_args)
            if "Session" in q_str:
                return session
            return heir

        mock_db.query.return_value.filter.return_value.first.side_effect = mock_first
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        payload = {
            "legal_first_name": "Janet",  # changed
            "legal_middle_name": "Anne",
            "legal_last_name": "Doe",
            "relationship_to_decedent": "Daughter",
            "date_of_birth": "1990-05-15",
            "email": "jane@example.com",
            "phone": "555-0199",
            "physical_address": "123 Maple St",
        }

        resp = test_client.put("/api/heirs/me/profile", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["identity_verified"] is False
        assert heir.status == "PROFILE_HOLD"
        assert heir.id_scan_uri is None
        mock_sd.delete.assert_called_once_with("identities/scan.enc")

    def test_update_profile_locked_session_returns_400(self, client):
        test_client, mock_db, _, _ = client
        heir = _build_heir()
        session = _build_session(status="LOCKED")  # locked!

        def mock_first(*args, **kwargs):
            q_str = str(mock_db.query.call_args)
            if "Session" in q_str:
                return session
            return heir

        mock_db.query.return_value.filter.return_value.first.side_effect = mock_first

        payload = {
            "legal_first_name": "Jane",
            "legal_middle_name": "Anne",
            "legal_last_name": "Doe",
            "relationship_to_decedent": "Daughter",
            "date_of_birth": "1990-05-15",
        }
        resp = test_client.put("/api/heirs/me/profile", json=payload)
        assert resp.status_code == 400
        assert "locked or finalized" in resp.json()["detail"].lower()

    def test_update_profile_abstained_heir_returns_400(self, client):
        test_client, mock_db, _, _ = client
        heir = _build_heir(status="ABSTAINED")  # abstained!
        session = _build_session()

        def mock_first(*args, **kwargs):
            q_str = str(mock_db.query.call_args)
            if "Session" in q_str:
                return session
            return heir

        mock_db.query.return_value.filter.return_value.first.side_effect = mock_first

        payload = {
            "legal_first_name": "Jane",
            "legal_middle_name": "Anne",
            "legal_last_name": "Doe",
            "relationship_to_decedent": "Daughter",
            "date_of_birth": "1990-05-15",
        }
        resp = test_client.put("/api/heirs/me/profile", json=payload)
        assert resp.status_code == 400
        assert "abstained or non-participating" in resp.json()["detail"].lower()
