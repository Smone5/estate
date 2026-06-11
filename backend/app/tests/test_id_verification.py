"""
Tests for T34: Executor ID Verification State Transition API.

Covers:
- POST /api/heirs/{heir_id}/verify-identity (approve / reject)
"""

import os
import uuid
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token
from app.models import User, Asset


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


def _make_heir(status="PROFILE_HOLD", session_id=None, id_scan_uri=None):
    return User(
        id=uuid.uuid4(),
        session_id=session_id or uuid.uuid4(),
        username="heir_test",
        role="HEIR",
        status=status,
        identity_verified=False,
        id_scan_uri=id_scan_uri,
    )


def _make_asset(asset_id=None, session_id=None):
    return Asset(
        id=asset_id or uuid.uuid4(),
        session_id=session_id or uuid.uuid4(),
        title="Test",
        description="Desc",
        category="Jewelry",
        valuation_min=100.0,
        valuation_max=500.0,
        valuation_source="Appraisal",
        sentiment_tag="Memento",
        image_uri="static/uploads/test.webp",
        status="LIVE",
    )


class TestIdentityVerification:
    def test_requires_auth(self, client, mock_db_session, test_env):
        resp = client.post(
            f"/api/heirs/{uuid.uuid4()}/verify-identity",
            json={"action": "approve"},
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
            f"/api/heirs/{uuid.uuid4()}/verify-identity",
            json={"action": "approve"},
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_approve_transitions_heir_to_active(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        heir = _make_heir(status="PROFILE_HOLD")

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = heir

        # Mock the asset query to return empty list
        mock_asset_query = mock.MagicMock()
        mock_asset_filter = mock_asset_query.filter.return_value
        mock_asset_filter.all.return_value = []

        def query_side_effect(model):
            if model == User:
                return mock_query
            elif model == Asset:
                return mock_asset_query
            elif model.__name__ == "Valuation":
                m = mock.MagicMock()
                m.filter.return_value.first.return_value = None
                return m
            return mock_query

        mock_db_session.query.side_effect = query_side_effect

        resp = client.post(
            f"/api/heirs/{heir.id}/verify-identity",
            json={"action": "approve"},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        assert heir.status == "ACTIVE"
        assert heir.identity_verified is True

    def test_reject_clears_scan(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        heir = _make_heir(status="PROFILE_HOLD", id_scan_uri="static/uploads/identities/test.scan")

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = heir

        resp = client.post(
            f"/api/heirs/{heir.id}/verify-identity",
            json={"action": "reject", "rejection_reason": "Invalid document"},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        assert heir.id_scan_uri is None

    def test_invalid_action_returns_422(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        resp = client.post(
            f"/api/heirs/{uuid.uuid4()}/verify-identity",
            json={"action": "invalid"},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 422