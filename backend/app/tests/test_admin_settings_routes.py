"""
Tests for GET/PUT /api/admin/settings — admin-editable runtime settings routes.
"""

import uuid
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token


TEST_JWT_SECRET = "test-secret-key-for-tests-only-do-not-use-in-production"
TEST_ENCRYPTION_KEY = "gdM1BemlB1hZLDqKATsfQNANKHQQ_HQH7F61aPJh9bU="


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)


@pytest.fixture
def mock_db_session():
    return mock.MagicMock(spec=DBSession)


@pytest.fixture
def client(mock_db_session):
    with mock.patch("app.main.SessionLocal", return_value=mock_db_session):
        from app.main import app

        yield TestClient(app, raise_server_exceptions=False), mock_db_session


def _admin_token():
    return create_access_token(
        user_id=str(uuid.uuid4()),
        username="executor",
        role="ADMIN",
        session_id=None,
    )


def _heir_token():
    return create_access_token(
        user_id=str(uuid.uuid4()),
        username="heir",
        role="HEIR",
        session_id=str(uuid.uuid4()),
    )


class TestGetAdminSettings:
    def test_requires_admin_auth(self, client):
        test_client, _ = client
        resp = test_client.get("/api/admin/settings")
        assert resp.status_code in (401, 403)

    def test_rejects_non_admin_role(self, client):
        test_client, _ = client
        resp = test_client.get(
            "/api/admin/settings",
            cookies={"estate_session": _heir_token()},
        )
        assert resp.status_code == 403

    def test_admin_can_fetch_settings(self, client):
        test_client, mock_db = client
        mock_db.query.return_value.all.return_value = []
        resp = test_client.get(
            "/api/admin/settings",
            cookies={"estate_session": _admin_token()},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"llm", "smtp", "storage"}


class TestPutAdminSettings:
    def test_requires_admin_auth(self, client):
        test_client, _ = client
        resp = test_client.put(
            "/api/admin/settings",
            json={"updates": {"LLM_PROVIDER": "openai"}},
        )
        assert resp.status_code in (401, 403)

    def test_rejects_unknown_setting_key(self, client):
        test_client, mock_db = client
        resp = test_client.put(
            "/api/admin/settings",
            json={"updates": {"JWT_SECRET": "newsecret"}},
            cookies={"estate_session": _admin_token()},
        )
        assert resp.status_code == 400

    def test_admin_can_update_settings(self, client):
        test_client, mock_db = client
        mock_db.query.return_value.filter.return_value.one_or_none.return_value = None
        resp = test_client.put(
            "/api/admin/settings",
            json={"updates": {"LLM_PROVIDER": "openai"}},
            cookies={"estate_session": _admin_token()},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["llm"]["LLM_PROVIDER"]["value"] == "openai"
        mock_db.commit.assert_called_once()
