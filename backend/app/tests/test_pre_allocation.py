"""
Tests for T64: Asset Pre-Allocation API.

Covers:
- POST /api/assets/{asset_id}/pre-allocate
"""

import os
import uuid
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token
from app.models import Asset, Session as SessionModel, Valuation


TEST_JWT_SECRET = "test-secret-key-for-tests-only-do-not-use-in-production"


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)
    monkeypatch.setenv("STORAGE_DRIVER", "MOCK")


@pytest.fixture
def mock_db_session():
    return mock.MagicMock(spec=DBSession)


@pytest.fixture
def client(mock_db_session):
    with mock.patch("app.main.SessionLocal", return_value=mock_db_session):
        from app.main import app
        yield TestClient(app, raise_server_exceptions=False)


def _make_admin_token():
    return create_access_token(
        user_id=str(uuid.uuid4()),
        username="executor",
        role="ADMIN",
        session_id=None,
    )


def _make_asset(session_id=None, status="LIVE"):
    sid = session_id or uuid.uuid4()
    return Asset(
        id=uuid.uuid4(),
        session_id=sid,
        title="Test",
        description="Desc",
        category="Jewelry",
        valuation_min=100.0,
        valuation_max=500.0,
        valuation_source="Appraisal",
        sentiment_tag="Memento",
        image_uri="static/uploads/test.webp",
        status=status,
    )


def _make_session(status="SETUP"):
    return SessionModel(
        id=uuid.uuid4(),
        title="Test",
        status=status,
        is_paused=False,
        is_deadlocked=False,
    )


class TestPreAllocation:
    def test_requires_auth(self, client, mock_db_session, test_env):
        resp = client.post(
            f"/api/assets/{uuid.uuid4()}/pre-allocate",
            json={"allocated_to_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 401

    def test_requires_admin(self, client, mock_db_session, test_env):
        heir_token = create_access_token(
            user_id=str(uuid.uuid4()),
            username="h",
            role="HEIR",
            session_id=str(uuid.uuid4()),
        )
        resp = client.post(
            f"/api/assets/{uuid.uuid4()}/pre-allocate",
            json={"allocated_to_id": str(uuid.uuid4())},
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_success(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        session = _make_session(status="SETUP")
        asset = _make_asset(session_id=session.id)
        heir_id = uuid.uuid4()

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        resp = client.post(
            f"/api/assets/{asset.id}/pre-allocate",
            json={"allocated_to_id": str(heir_id)},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["allocated_to_id"] == str(heir_id)
        assert asset.status == "PRE_ALLOCATED"
        assert asset.allocated_to_id == str(heir_id)
        mock_db_session.commit.assert_called_once()

    def test_blocked_in_active(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        session = _make_session(status="ACTIVE")
        asset = _make_asset(session_id=session.id)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.side_effect = [asset, session]

        resp = client.post(
            f"/api/assets/{asset.id}/pre-allocate",
            json={"allocated_to_id": str(uuid.uuid4())},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 400

    def test_nonexistent_asset_returns_404(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        resp = client.post(
            f"/api/assets/{uuid.uuid4()}/pre-allocate",
            json={"allocated_to_id": str(uuid.uuid4())},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 404