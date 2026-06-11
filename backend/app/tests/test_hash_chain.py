"""
T82: Test Hash Chain Verification Tool — GET /api/system/verify-hash-chain
"""

import uuid
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

SESSION_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "t82-test-secret")
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)


@pytest.fixture
def mock_db():
    return mock.MagicMock(spec=DBSession)


@pytest.fixture
def client(mock_db):
    from app.main import app

    with mock.patch("app.main.SessionLocal", return_value=mock_db), \
         mock.patch("app.main.limiter.limit", lambda rate: lambda f: f):
        test_client = TestClient(app, raise_server_exceptions=False)
        yield test_client, mock_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHashChainVerify:
    def test_empty_logs_returns_empty_status(self, client):
        """When there are no audit logs, return status=empty."""
        test_client, mock_db = client

        # Chain: db.query(AuditLog).order_by(AuditLog.id.asc()).all()
        ordered_mock = mock.MagicMock()
        ordered_mock.all.return_value = []
        mock_db.query.return_value.order_by.return_value = ordered_mock

        response = test_client.get("/api/system/verify-hash-chain")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "empty"
        assert data["verified"] is True
        assert data["rows"] == []

    def test_valid_chain_passes_verification(self, client):
        """A valid chain where all hashes match should return status=valid."""
        test_client, mock_db = client

        import hashlib

        snapshot1 = {"key": "value1"}
        snapshot2 = {"key": "value2"}

        prev_hash1 = "0" * 64
        sn1_sorted = str(sorted(snapshot1.items()))
        raw1 = f"1:EVENT_ONE:{sn1_sorted}:{prev_hash1}"
        hash1 = hashlib.sha256(raw1.encode("utf-8")).hexdigest()

        sn2_sorted = str(sorted(snapshot2.items()))
        raw2 = f"2:EVENT_TWO:{sn2_sorted}:{hash1}"
        hash2 = hashlib.sha256(raw2.encode("utf-8")).hexdigest()

        log1 = mock.MagicMock()
        log1.id = 1
        log1.event_type = "EVENT_ONE"
        log1.session_id = SESSION_ID
        log1.state_snapshot = snapshot1
        log1.prev_hash = prev_hash1
        log1.sha256_hash = hash1
        log1.created_at = datetime.now(timezone.utc)

        log2 = mock.MagicMock()
        log2.id = 2
        log2.event_type = "EVENT_TWO"
        log2.session_id = SESSION_ID
        log2.state_snapshot = snapshot2
        log2.prev_hash = hash1
        log2.sha256_hash = hash2
        log2.created_at = datetime.now(timezone.utc)

        # Chain: db.query(AuditLog).order_by(...).all()
        ordered_mock = mock.MagicMock()
        ordered_mock.all.return_value = [log1, log2]
        mock_db.query.return_value.order_by.return_value = ordered_mock

        response = test_client.get("/api/system/verify-hash-chain")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "valid"
        assert data["verified"] is True
        assert data["total_rows"] == 2
        assert len(data["breaks"]) == 0

        # Verify per-row validation
        assert data["rows"][0]["hash_valid"] is True
        assert data["rows"][0]["prev_hash_match"] is True
        assert data["rows"][1]["hash_valid"] is True
        assert data["rows"][1]["prev_hash_match"] is True

    def test_broken_chain_detects_tampering(self, client):
        """A chain with a mismatched hash should be detected as broken."""
        test_client, mock_db = client

        import hashlib

        snapshot1 = {"key": "value1"}

        prev_hash1 = "0" * 64
        sn1_sorted = str(sorted(snapshot1.items()))
        raw1 = f"1:EVENT_ONE:{sn1_sorted}:{prev_hash1}"
        hash1 = hashlib.sha256(raw1.encode("utf-8")).hexdigest()

        log1 = mock.MagicMock()
        log1.id = 1
        log1.event_type = "EVENT_ONE"
        log1.session_id = SESSION_ID
        log1.state_snapshot = snapshot1
        log1.prev_hash = prev_hash1
        # Tampered hash — store a wrong value
        log1.sha256_hash = "a" * 64
        log1.created_at = datetime.now(timezone.utc)

        ordered_mock = mock.MagicMock()
        ordered_mock.all.return_value = [log1]
        mock_db.query.return_value.order_by.return_value = ordered_mock

        response = test_client.get("/api/system/verify-hash-chain")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "broken"
        assert data["verified"] is False
        assert data["total_rows"] == 1
        assert len(data["breaks"]) == 1
        assert data["breaks"][0]["row_id"] == 1

    def test_filter_by_session_id(self, client):
        """Verify session_id query param filters correctly."""
        test_client, mock_db = client

        # Chain: db.query(AuditLog).order_by(...).filter(...).all()
        filtered_mock = mock.MagicMock()
        filtered_mock.all.return_value = []
        ordered_mock = mock.MagicMock()
        ordered_mock.filter.return_value = filtered_mock
        mock_db.query.return_value.order_by.return_value = ordered_mock

        response = test_client.get(f"/api/system/verify-hash-chain?session_id={SESSION_ID}")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "empty"
        assert data["session_id"] == str(SESSION_ID)