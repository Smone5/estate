"""
Tests for POST /api/admin/settings/test-connection — lets an admin verify a
provider/model/credential combination actually works before (or without)
saving it, by firing one minimal real call through the LLM provider
abstraction.
"""
import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_admin
from app.main import app


def _make_admin_payload():
    return {"user_id": "00000000-0000-0000-0000-000000000001", "role": "ADMIN"}


@pytest.fixture
def client():
    app.dependency_overrides[get_current_admin] = _make_admin_payload
    with mock.patch("app.main.limiter.limit", lambda rate: lambda f: f):
        yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_test_connection_rejects_unknown_purpose(client):
    resp = client.post("/api/admin/settings/test-connection", json={"purpose": "bogus"})
    assert resp.status_code == 400


def test_test_connection_rejects_non_llm_override_keys(client):
    resp = client.post(
        "/api/admin/settings/test-connection",
        json={"purpose": "fast", "overrides": {"JWT_SECRET": "hacked"}},
    )
    assert resp.status_code == 400
    assert "Unsupported override key" in resp.json()["detail"]


def test_test_connection_llm_success(client):
    with mock.patch("app.main.LLMProvider") as MockProvider:
        instance = MockProvider.return_value
        instance.generate_text.return_value = "OK"
        resp = client.post(
            "/api/admin/settings/test-connection",
            json={"purpose": "fast", "overrides": {"LLM_PROVIDER": "ollama", "FAST_THINKER_MODEL": "qwen3:8b"}},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["detail"] == "OK"
    assert "elapsed_ms" in body


def test_test_connection_embedding_success(client):
    with mock.patch("app.main.LLMProvider") as MockProvider:
        instance = MockProvider.return_value
        instance.get_embeddings.return_value = [0.1] * 768
        resp = client.post(
            "/api/admin/settings/test-connection",
            json={"purpose": "embedding", "overrides": {}},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "768" in body["detail"]


def test_test_connection_reports_failure_without_500(client):
    with mock.patch("app.main.LLMProvider") as MockProvider:
        instance = MockProvider.return_value
        instance.generate_text.side_effect = RuntimeError("connection refused")
        resp = client.post(
            "/api/admin/settings/test-connection",
            json={"purpose": "fast", "overrides": {}},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "connection refused" in body["error"]


def test_test_connection_restores_env_after_request(client):
    os.environ.pop("FAST_THINKER_MODEL", None)
    with mock.patch("app.main.LLMProvider") as MockProvider:
        instance = MockProvider.return_value
        instance.generate_text.return_value = "OK"
        client.post(
            "/api/admin/settings/test-connection",
            json={"purpose": "fast", "overrides": {"FAST_THINKER_MODEL": "qwen3:8b"}},
        )
    assert "FAST_THINKER_MODEL" not in os.environ
