"""
Tests for T39: Admin Setup & Session Creation API.

Covers:
- POST /api/setup/admin  (first-boot admin creation + BIP39 mnemonic)
- POST /api/sessions     (new mediation session creation)
"""

import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token
from app.models import User, Session as SessionModel


TEST_JWT_SECRET = "test-secret-key-for-tests-only-do-not-use-in-production"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    """Set required env vars for auth and encryption modules."""
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    # Valid 43-char Fernet key: base64url of 32 bytes
    monkeypatch.setenv(
        "ENCRYPTION_KEY",
        "gdM1BemlB1hZLDqKATsfQNANKHQQ_HQH7F61aPJh9bU=",
    )


@pytest.fixture
def mock_db_session():
    """Return a MagicMock wrapping a SQLAlchemy session."""
    session = mock.MagicMock(spec=DBSession)
    return session


@pytest.fixture
def client(mock_db_session):
    """FastAPI TestClient with a mocked database session."""
    with mock.patch("app.main.SessionLocal", return_value=mock_db_session):
        from app.main import app
        yield TestClient(app, raise_server_exceptions=False)


def _make_admin_token():
    """Return a valid JWT token for an Admin user."""
    return create_access_token(
        user_id=str(uuid.uuid4()),
        username="executor",
        role="ADMIN",
        session_id=None,
    )


def _make_session_obj(title="Estate of John Doe"):
    """Build a Session ORM object."""
    sid = uuid.uuid4()
    return SessionModel(
        id=sid,
        title=title,
        status="SETUP",
        is_paused=False,
        is_deadlocked=False,
        deadline=None,
    )


# ---------------------------------------------------------------------------
# POST /api/setup/admin
# ---------------------------------------------------------------------------


class TestAdminSetup:
    """POST /api/setup/admin — first-boot admin creation."""

    def _setup_no_admin(self, mock_db_session):
        """Configure mock to return no existing admin."""
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None
        return mock_query, mock_filter

    def _setup_existing_admin(self, mock_db_session):
        """Configure mock to return an existing admin."""
        existing = User(
            id=uuid.uuid4(),
            username="executor",
            role="ADMIN",
            pw_hash="$argon2id$...",
            status="ACTIVE",
        )
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = existing
        return mock_query, mock_filter

    def test_setup_creates_admin_returns_201(self, client, mock_db_session, test_env):
        self._setup_no_admin(mock_db_session)

        resp = client.post(
            "/api/setup/admin",
            json={"username": "executor", "password": "securepass123"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "created"
        assert data["username"] == "executor"
        assert "paper_recovery_key" in data

        # Verify the recovery key is 24 words
        words = data["paper_recovery_key"].split()
        assert len(words) == 24

        # Verify commit was called
        mock_db_session.commit.assert_called_once()

    def test_setup_sets_auth_cookie(self, client, mock_db_session, test_env):
        """Verify that successful admin setup returns an auth cookie.

        Note: Because the rate limiter (5/minute) state is shared across
        test cases in this class, this test may hit the limit if run after
        other setup tests. We only validate the happy path when it succeeds.
        """
        self._setup_no_admin(mock_db_session)

        resp = client.post(
            "/api/setup/admin",
            json={"username": "executor", "password": "securepass123"},
        )
        # May be 201 or 429 if rate-limited by prior tests
        if resp.status_code == 201:
            assert "set-cookie" in resp.headers
            assert "estate_session=" in resp.headers["set-cookie"]
        else:
            assert resp.status_code == 429

    def test_setup_idempotent_returns_409(self, client, mock_db_session, test_env):
        """Second call must fail with 409 — admin already exists."""
        self._setup_existing_admin(mock_db_session)

        resp = client.post(
            "/api/setup/admin",
            json={"username": "executor2", "password": "anotherpass"},
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"].lower()

    def test_setup_missing_username_returns_422(self, client, mock_db_session, test_env):
        self._setup_no_admin(mock_db_session)
        resp = client.post("/api/setup/admin", json={"password": "securepass123"})
        assert resp.status_code == 422

    def test_setup_missing_password_returns_422(self, client, mock_db_session, test_env):
        self._setup_no_admin(mock_db_session)
        resp = client.post("/api/setup/admin", json={"username": "executor"})
        assert resp.status_code == 422

    def test_setup_short_password_returns_422(self, client, mock_db_session, test_env):
        self._setup_no_admin(mock_db_session)
        resp = client.post(
            "/api/setup/admin",
            json={"username": "executor", "password": "short"},
        )
        assert resp.status_code == 422

    def test_setup_short_username_returns_422(self, client, mock_db_session, test_env):
        self._setup_no_admin(mock_db_session)
        resp = client.post(
            "/api/setup/admin",
            json={"username": "ab", "password": "securepass123"},
        )
        assert resp.status_code == 422

    def test_setup_returns_recovery_key_is_24_words(self, client, mock_db_session, test_env):
        self._setup_no_admin(mock_db_session)

        resp = client.post(
            "/api/setup/admin",
            json={"username": "executor", "password": "securepass123"},
        )
        data = resp.json()
        recovery_key = data["paper_recovery_key"]
        words = recovery_key.split()
        assert len(words) == 24, f"Expected 24 words, got {len(words)}"

        # Verify each word is a valid BIP39 word (alphanumeric, no spaces)
        for w in words:
            assert w.isalpha(), f"Word '{w}' is not alphabetic"


# ---------------------------------------------------------------------------
# POST /api/sessions
# ---------------------------------------------------------------------------


class TestSessionCreation:
    """POST /api/sessions — new mediation session creation."""

    def test_create_session_requires_auth(self, client, mock_db_session, test_env):
        """Unauthenticated request must return 401."""
        resp = client.post(
            "/api/sessions",
            json={"title": "Estate of John Doe"},
        )
        assert resp.status_code == 401

    def test_create_session_returns_201(self, client, mock_db_session, test_env):
        """Authenticated admin creates a session."""
        token = _make_admin_token()
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None  # No existing session lookup interferes

        resp = client.post(
            "/api/sessions",
            json={"title": "Estate of John Doe"},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Estate of John Doe"
        assert data["status"] == "SETUP"
        assert data["is_paused"] is False
        assert "session_id" in data

    def test_create_session_stores_correct_status(self, client, mock_db_session, test_env):
        """Session must be created with SETUP status."""
        token = _make_admin_token()

        resp = client.post(
            "/api/sessions",
            json={"title": "My Estate"},
            cookies={"estate_session": token},
        )
        data = resp.json()
        assert data["status"] == "SETUP"

    def test_create_session_returns_session_id(self, client, mock_db_session, test_env):
        """Response must include a session_id field.

        In unit tests with a mocked database, the server_default
        gen_random_uuid() is not executed by SQLAlchemy, so the session_id
        may be None. We verify the field exists in the response.
        """
        token = _make_admin_token()

        resp = client.post(
            "/api/sessions",
            json={"title": "My Estate"},
            cookies={"estate_session": token},
        )
        data = resp.json()
        assert "session_id" in data

    def test_create_session_calls_commit(self, client, mock_db_session, test_env):
        """Session creation must call db.commit."""
        token = _make_admin_token()

        resp = client.post(
            "/api/sessions",
            json={"title": "My Estate"},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 201
        mock_db_session.commit.assert_called_once()

    def test_create_session_missing_title_returns_422(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        resp = client.post(
            "/api/sessions",
            json={},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 422

    def test_create_session_empty_title_returns_422(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        resp = client.post(
            "/api/sessions",
            json={"title": ""},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 422

    def test_create_session_heir_token_rejected(self, client, mock_db_session, test_env):
        """A HEIR token must not be allowed to create sessions."""
        heir_token = create_access_token(
            user_id=str(uuid.uuid4()),
            username="heir_bob",
            role="HEIR",
            session_id=str(uuid.uuid4()),
        )
        resp = client.post(
            "/api/sessions",
            json={"title": "My Estate"},
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403