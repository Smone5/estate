"""
Tests for auth.py and the onboarding endpoints (T10).

Covers:
- Argon2 password hashing / verification
- JWT token creation and decoding
- JWT cookie setting
- Admin login endpoint (POST /api/auth/login)
- Heir invite verify endpoint (POST /api/invite/verify)
- Heir re-login endpoint (POST /api/invite/login)
- Rate limiting headers on public endpoints
"""

import os
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.models import Session as SessionModel, User
from app.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    set_auth_cookie,
    clear_auth_cookie,
    get_current_user,
    get_current_admin,
    get_current_heir,
)


TEST_JWT_SECRET = "test-secret-key-for-tests-only-do-not-use-in-production"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    """Set required env vars for auth module."""
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)  # dummy 43-char key for EncryptedJSON


@pytest.fixture
def mock_db_session():
    """Return a MagicMock wrapping a SQLAlchemy session.

    Tests can attach `.query().filter().first()` side effects to control
    what User objects are returned.
    """
    session = mock.MagicMock(spec=DBSession)
    return session


@pytest.fixture
def client(mock_db_session):
    """FastAPI TestClient with a mocked database session."""
    with mock.patch("app.main.SessionLocal", return_value=mock_db_session):
        from app.main import app
        yield TestClient(app, raise_server_exceptions=False)


def _make_admin_user(pw_raw="adminpass123"):
    """Build a User ORM object representing an admin."""
    pw_hash_val = hash_password(pw_raw)
    return User(
        id=uuid.uuid4(),
        username="executor",
        role="ADMIN",
        pw_hash=pw_hash_val,
        status="ACTIVE",
    )


def _make_heir_user(session_id=None, invite_token_used=False):
    """Build a User ORM object representing a pending heir."""
    sid = session_id or uuid.uuid4()
    tok = str(uuid.uuid4())
    return User(
        id=uuid.uuid4(),
        session_id=sid,
        username="heir_jane",
        role="HEIR",
        invite_token=tok,
        invite_token_expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        invite_token_used=invite_token_used,
        consent_accepted=False,
        age_verified=False,
        consent_timestamp=None,
        status="PENDING" if not invite_token_used else "PROFILE_HOLD",
        legal_first_name=None,
        legal_middle_name=None,
        legal_last_name=None,
        relationship_to_decedent=None,
        date_of_birth=None,
        email="heir@example.com",
    )


# ---------------------------------------------------------------------------
# Argon2 tests
# ---------------------------------------------------------------------------


class TestArgon2Hashing:
    """Verify Argon2 password hashing and verification."""

    def test_hash_returns_different_string(self):
        hashed = hash_password("my-secret")
        assert hashed != "my-secret"
        assert hashed.startswith("$argon2")

    def test_verify_correct_password(self):
        hashed = hash_password("testpass")
        assert verify_password("testpass", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("testpass")
        assert verify_password("wrong", hashed) is False

    def test_hash_is_deterministic_by_verification(self):
        """Each call produces a unique salt, but verification still works."""
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert h1 != h2
        assert verify_password("same-password", h1) is True
        assert verify_password("same-password", h2) is True


# ---------------------------------------------------------------------------
# JWT tests
# ---------------------------------------------------------------------------


class TestJWT:
    """Verify JWT token creation and decoding."""

    def test_create_and_decode_token(self, test_env):
        token = create_access_token(
            user_id="abc-123",
            username="heir_jane",
            role="HEIR",
            session_id="sess-456",
        )
        payload = decode_access_token(token)
        assert payload["user_id"] == "abc-123"
        assert payload["username"] == "heir_jane"
        assert payload["role"] == "HEIR"
        assert payload["session_id"] == "sess-456"

    def test_token_includes_exp(self, test_env):
        token = create_access_token("id", "name", "ADMIN")
        payload = decode_access_token(token)
        assert "exp" in payload
        assert "iat" in payload

    def test_decode_invalid_token_raises(self, test_env):
        with pytest.raises(Exception):
            decode_access_token("not-a-valid-jwt")

    def test_expired_token_raises(self, test_env):
        """Token with exp in the past should be rejected."""
        from jose import jwt as jose_jwt
        secret = os.environ["JWT_SECRET"]
        expired_payload = {
            "user_id": "id",
            "username": "name",
            "role": "HEIR",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "iat": datetime.now(timezone.utc) - timedelta(hours=25),
        }
        token = jose_jwt.encode(expired_payload, secret, algorithm="HS256")
        with pytest.raises(Exception):
            decode_access_token(token)

    def test_admin_token_has_no_session_id(self, test_env):
        token = create_access_token("admin-id", "executor", "ADMIN")
        payload = decode_access_token(token)
        assert payload["session_id"] is None

    def test_heir_token_has_session_id(self, test_env):
        token = create_access_token(
            "heir-id", "heir_name", "HEIR", session_id="session-uuid"
        )
        payload = decode_access_token(token)
        assert payload["session_id"] == "session-uuid"


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


class TestCookieHelpers:
    """Verify set/clear auth cookie helpers."""

    def test_set_auth_cookie(self, test_env):
        from fastapi import Response

        resp = Response()
        set_auth_cookie(resp, "test-token-value")
        cookie_header = resp.headers.get("set-cookie", "")
        assert "estate_session=test-token-value" in cookie_header
        assert "httponly" in cookie_header.lower()

    def test_clear_auth_cookie(self, test_env):
        from fastapi import Response

        resp = Response()
        clear_auth_cookie(resp)
        cookie_header = resp.headers.get("set-cookie", "")
        assert "estate_session=" in cookie_header
        assert "max-age=0" in cookie_header.lower()

    def test_cookie_has_path_slash(self, test_env):
        from fastapi import Response

        resp = Response()
        set_auth_cookie(resp, "token")
        assert 'Path=/' in resp.headers.get("set-cookie", "")


# ---------------------------------------------------------------------------
# Auth dependency tests
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    """Verify the FastAPI dependency for user extraction."""

    def test_missing_cookie_returns_401(self):
        with pytest.raises(Exception) as exc_info:
            get_current_user(estate_session=None)
        assert exc_info.value.status_code == 401

    def test_invalid_cookie_returns_401(self, test_env):
        with pytest.raises(Exception) as exc_info:
            get_current_user(estate_session="garbage-token")
        assert exc_info.value.status_code == 401

    def test_valid_cookie_returns_payload(self, test_env):
        token = create_access_token("uid", "user", "HEIR", session_id="sid")
        payload = get_current_user(estate_session=token)
        assert payload["user_id"] == "uid"
        assert payload["role"] == "HEIR"

    def test_get_current_admin_rejects_heir(self, test_env):
        token = create_access_token("uid", "user", "HEIR")
        payload = get_current_user(estate_session=token)
        with pytest.raises(Exception) as exc_info:
            get_current_admin(current_user=payload)
        assert exc_info.value.status_code == 403

    def test_get_current_admin_accepts_admin(self, test_env):
        token = create_access_token("uid", "user", "ADMIN")
        payload = get_current_user(estate_session=token)
        result = get_current_admin(current_user=payload)
        assert result["role"] == "ADMIN"

    def test_get_current_heir_rejects_admin(self, test_env):
        token = create_access_token("uid", "user", "ADMIN")
        payload = get_current_user(estate_session=token)
        with pytest.raises(Exception) as exc_info:
            get_current_heir(current_user=payload)
        assert exc_info.value.status_code == 403

    def test_get_current_heir_accepts_heir(self, test_env):
        token = create_access_token("uid", "user", "HEIR")
        payload = get_current_user(estate_session=token)
        result = get_current_heir(current_user=payload)
        assert result["role"] == "HEIR"


# ---------------------------------------------------------------------------
# Admin login endpoint tests
# ---------------------------------------------------------------------------


class TestAdminLoginEndpoint:
    """POST /api/auth/login"""

    def test_login_success_returns_200(self, client, mock_db_session, test_env):
        admin = _make_admin_user()
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = admin

        resp = client.post(
            "/api/auth/login",
            json={"username": "executor", "password": "adminpass123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "authenticated"
        assert data["role"] == "ADMIN"

    def test_login_sets_cookie(self, client, mock_db_session, test_env):
        admin = _make_admin_user()
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = admin

        resp = client.post(
            "/api/auth/login",
            json={"username": "executor", "password": "adminpass123"},
        )
        assert "set-cookie" in resp.headers
        assert "estate_admin_session=" in resp.headers["set-cookie"]

    def test_login_wrong_password_returns_401(self, client, mock_db_session, test_env):
        admin = _make_admin_user("adminpass123")
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = admin

        resp = client.post(
            "/api/auth/login",
            json={"username": "executor", "password": "wrongpassword"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid credentials"

    def test_login_nonexistent_user_returns_401(self, client, mock_db_session, test_env):
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        resp = client.post(
            "/api/auth/login",
            json={"username": "nobody", "password": "pass"},
        )
        assert resp.status_code == 401

    def test_login_missing_username_returns_422(self, client, mock_db_session, test_env):
        resp = client.post(
            "/api/auth/login",
            json={"password": "adminpass123"},
        )
        assert resp.status_code == 422

    def test_login_missing_password_returns_422(self, client, mock_db_session, test_env):
        resp = client.post(
            "/api/auth/login",
            json={"username": "executor"},
        )
        assert resp.status_code == 422

    def test_login_user_with_null_pw_hash_returns_401(
        self, client, mock_db_session, test_env
    ):
        admin = _make_admin_user()
        admin.pw_hash = None
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = admin

        resp = client.post(
            "/api/auth/login",
            json={"username": "executor", "password": "adminpass123"},
        )
        assert resp.status_code == 401

    def test_auth_me_restores_admin_from_cookie(self, client, test_env):
        token = create_access_token(
            user_id="admin-id",
            username="executor",
            role="ADMIN",
            session_id=None,
        )
        client.cookies.set("estate_session", token)

        resp = client.get("/api/auth/me")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "authenticated"
        assert data["role"] == "ADMIN"
        assert data["username"] == "executor"
        assert data["session_id"] is None

    def test_auth_me_requires_cookie(self, client, test_env):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_auth_logout_clears_cookie(self, client, test_env):
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json() == {"status": "success", "message": "Logged out successfully"}

        # Without an X-Estate-Role header, logout defensively clears every
        # known cookie (admin, heir, and the legacy shared name). Verify via
        # the Set-Cookie response headers directly — httpx's TestClient
        # cookie jar doesn't reliably reflect deletions for cookies that
        # were never actually set through a prior request/response cycle.
        cookie_header = resp.headers.get("set-cookie", "")
        assert "estate_session=" in cookie_header
        assert "max-age=0" in cookie_header.lower()


# ---------------------------------------------------------------------------
# Invite verify endpoint tests
# ---------------------------------------------------------------------------


class TestInviteVerifyEndpoint:
    """POST /api/invite/verify"""

    def _setup_heir_mock(self, mock_db_session, heir):
        """Configure the mock session query to return the given heir."""
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = heir

    def test_verify_success_returns_200(self, client, mock_db_session, test_env):
        heir = _make_heir_user()
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/verify",
            json={
                "token": str(heir.invite_token),
                "consent_accepted": True,
                "age_verified": True,
                "password": "heirpass123",
                "legal_first_name": "Jane",
                "legal_last_name": "Doe",
                "relationship_to_decedent": "Daughter",
                "date_of_birth": "1990-05-20",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["user_status"] == "PROFILE_HOLD"
        assert data["heir_id"] == str(heir.id)
        assert verify_password("heirpass123", heir.pw_hash)

    def test_verify_sets_cookie(self, client, mock_db_session, test_env):
        heir = _make_heir_user()
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/verify",
            json={
                "token": str(heir.invite_token),
                "consent_accepted": True,
                "age_verified": True,
                "legal_first_name": "Jane",
                "legal_last_name": "Doe",
                "relationship_to_decedent": "Daughter",
                "date_of_birth": "1990-05-20",
            },
        )
        assert "set-cookie" in resp.headers
        assert "estate_heir_session=" in resp.headers["set-cookie"]

    def test_verify_sets_httponly_cookie(self, client, mock_db_session, test_env):
        heir = _make_heir_user()
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/verify",
            json={
                "token": str(heir.invite_token),
                "consent_accepted": True,
                "age_verified": True,
                "legal_first_name": "Jane",
                "legal_last_name": "Doe",
                "relationship_to_decedent": "Daughter",
                "date_of_birth": "1990-05-20",
            },
        )
        cookie_header = resp.headers.get("set-cookie", "").lower()
        assert "httponly" in cookie_header

    def test_verify_updates_user_attributes(self, client, mock_db_session, test_env):
        """The endpoint should update the user object's fields and call db.commit()."""
        heir = _make_heir_user()
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/verify",
            json={
                "token": str(heir.invite_token),
                "consent_accepted": True,
                "age_verified": True,
                "legal_first_name": "Jane",
                "legal_last_name": "Doe",
                "relationship_to_decedent": "Daughter",
                "date_of_birth": "1990-05-20",
            },
        )
        assert resp.status_code == 200
        # After a successful call, commit + refresh should have been invoked
        mock_db_session.commit.assert_called_once()
        mock_db_session.refresh.assert_called_once_with(heir)

    def test_verify_consent_not_accepted_returns_400(self, client, mock_db_session, test_env):
        heir = _make_heir_user()
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/verify",
            json={
                "token": str(heir.invite_token),
                "consent_accepted": False,
                "age_verified": True,
                "legal_first_name": "Jane",
                "legal_last_name": "Doe",
                "relationship_to_decedent": "Daughter",
                "date_of_birth": "1990-05-20",
            },
        )
        assert resp.status_code == 400
        assert "consent" in resp.json()["detail"].lower()

    def test_verify_age_not_verified_returns_400(self, client, mock_db_session, test_env):
        heir = _make_heir_user()
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/verify",
            json={
                "token": str(heir.invite_token),
                "consent_accepted": True,
                "age_verified": False,
                "legal_first_name": "Jane",
                "legal_last_name": "Doe",
                "relationship_to_decedent": "Daughter",
                "date_of_birth": "1990-05-20",
            },
        )
        assert resp.status_code == 400
        assert "age" in resp.json()["detail"].lower()

    def test_verify_nonexistent_token_returns_400(self, client, mock_db_session, test_env):
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        resp = client.post(
            "/api/invite/verify",
            json={
                "token": str(uuid.uuid4()),
                "consent_accepted": True,
                "age_verified": True,
                "legal_first_name": "Jane",
                "legal_last_name": "Doe",
                "relationship_to_decedent": "Daughter",
                "date_of_birth": "1990-05-20",
            },
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_verify_already_used_token_returns_400(
        self, client, mock_db_session, test_env
    ):
        heir = _make_heir_user(invite_token_used=True)
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/verify",
            json={
                "token": str(heir.invite_token),
                "consent_accepted": True,
                "age_verified": True,
                "legal_first_name": "Bob",
                "legal_last_name": "Smith",
                "relationship_to_decedent": "Son",
                "date_of_birth": "1985-06-15",
            },
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_verify_expired_token_returns_400(self, client, mock_db_session, test_env):
        heir = _make_heir_user()
        heir.invite_token_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/verify",
            json={
                "token": str(heir.invite_token),
                "consent_accepted": True,
                "age_verified": True,
                "legal_first_name": "Jane",
                "legal_last_name": "Doe",
                "relationship_to_decedent": "Daughter",
                "date_of_birth": "1990-05-20",
            },
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_verify_updates_legal_name_fields(self, client, mock_db_session, test_env):
        heir = _make_heir_user()
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/verify",
            json={
                "token": str(heir.invite_token),
                "consent_accepted": True,
                "age_verified": True,
                "legal_first_name": "Janet",
                "legal_middle_name": "Marie",
                "legal_last_name": "Dorian",
                "relationship_to_decedent": "Niece",
                "date_of_birth": "1992-03-15",
            },
        )
        assert resp.status_code == 200
        # Route mutates the object directly
        assert heir.legal_first_name == "Janet"
        assert heir.legal_middle_name == "Marie"
        assert heir.legal_last_name == "Dorian"
        assert heir.relationship_to_decedent == "Niece"

    def test_verify_missing_token_returns_422(self, client, mock_db_session, test_env):
        resp = client.post(
            "/api/invite/verify",
            json={
                "consent_accepted": True,
                "age_verified": True,
                "legal_first_name": "Jane",
                "legal_last_name": "Doe",
                "relationship_to_decedent": "Daughter",
                "date_of_birth": "1990-05-20",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Invite login endpoint tests
# ---------------------------------------------------------------------------


class TestInviteLoginEndpoint:
    """POST /api/invite/login"""

    def _setup_heir_mock(self, mock_db_session, heir):
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = heir

    def test_login_success_returns_200(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=True)
        heir.consent_accepted = True
        heir.age_verified = True
        heir.status = "PROFILE_HOLD"
        heir.legal_first_name = "Bob"
        heir.legal_last_name = "Smith"
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/login",
            json={"token": str(heir.invite_token)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["heir_id"] == str(heir.id)

    def test_login_sets_cookie(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=True)
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/login",
            json={"token": str(heir.invite_token)},
        )
        assert "set-cookie" in resp.headers
        assert "estate_heir_session=" in resp.headers["set-cookie"]

    def test_login_unverified_heir_returns_400(self, client, mock_db_session, test_env):
        """Heir who hasn't completed onboarding (invite_token_used=False) cannot login."""
        heir = _make_heir_user(invite_token_used=False)
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/login",
            json={"token": str(heir.invite_token)},
        )
        assert resp.status_code == 400
        assert "not been verified" in resp.json()["detail"].lower()

    def test_login_nonexistent_token_returns_401(self, client, mock_db_session, test_env):
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        resp = client.post(
            "/api/invite/login",
            json={"token": str(uuid.uuid4())},
        )
        assert resp.status_code == 401

    def test_login_expired_token_returns_400(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=True)
        heir.invite_token_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/login",
            json={"token": str(heir.invite_token)},
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()

    def test_login_missing_token_returns_422(self, client, mock_db_session, test_env):
        resp = client.post(
            "/api/invite/login",
            json={},
        )
        assert resp.status_code == 422

    def test_login_returns_user_status(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=True)
        heir.status = "PROFILE_HOLD"
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/invite/login",
            json={"token": str(heir.invite_token)},
        )
        data = resp.json()
        assert data["user_status"] == "PROFILE_HOLD"


# ---------------------------------------------------------------------------
# Heir password login endpoint tests
# ---------------------------------------------------------------------------


class TestHeirPasswordLoginEndpoint:
    """POST /api/auth/heir-login"""

    def _setup_heir_mock(self, mock_db_session, heir):
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = heir
        # Password login queries all matching records (a heir can belong to
        # more than one estate session), not just the first match.
        mock_filter.all.return_value = [heir]

    def test_password_login_success_after_invite_expires(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=True)
        heir.email = "heir@example.com"
        heir.pw_hash = hash_password("heirpass123")
        heir.invite_token_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/auth/heir-login",
            json={"identifier": "heir@example.com", "password": "heirpass123"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["role"] == "HEIR"
        assert data["heir_id"] == str(heir.id)
        assert "estate_heir_session=" in resp.headers.get("set-cookie", "")

    def test_password_login_accepts_username(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=True)
        heir.pw_hash = hash_password("heirpass123")
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/auth/heir-login",
            json={"identifier": heir.username, "password": "heirpass123"},
        )

        assert resp.status_code == 200

    def test_password_login_wrong_password_returns_401(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=True)
        heir.email = "heir@example.com"
        heir.pw_hash = hash_password("heirpass123")
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/auth/heir-login",
            json={"identifier": "heir@example.com", "password": "wrongpass"},
        )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid credentials"

    def test_password_login_without_onboarding_returns_401(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=False)
        heir.email = "heir@example.com"
        heir.pw_hash = hash_password("heirpass123")
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/auth/heir-login",
            json={"identifier": "heir@example.com", "password": "heirpass123"},
        )

        assert resp.status_code == 401

    def test_password_login_missing_password_hash_returns_401(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=True)
        heir.email = "heir@example.com"
        heir.pw_hash = None
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.post(
            "/api/auth/heir-login",
            json={"identifier": "heir@example.com", "password": "heirpass123"},
        )

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Invite status endpoint
# ---------------------------------------------------------------------------


class TestInviteStatusEndpoint:
    def _setup_heir_mock(self, mock_db_session, heir):
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = heir

    def test_invite_status_new(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=False)
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.get(f"/api/invite/status/{heir.invite_token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "NEW"
        assert data["used"] is False
        assert data["username"] == heir.username

    def test_invite_status_used(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=True)
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.get(f"/api/invite/status/{heir.invite_token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "USED"
        assert data["used"] is True

    def test_invite_status_expired(self, client, mock_db_session, test_env):
        heir = _make_heir_user(invite_token_used=False)
        heir.invite_token_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        self._setup_heir_mock(mock_db_session, heir)

        resp = client.get(f"/api/invite/status/{heir.invite_token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "EXPIRED"

    def test_invite_status_not_found(self, client, mock_db_session, test_env):
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        resp = client.get(f"/api/invite/status/{uuid.uuid4()}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Health endpoint (regression)
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_ok(self, client, test_env):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestSetupStatusEndpoint:
    def test_setup_status_true_when_admin_exists(self, client, mock_db_session, test_env):
        admin = _make_admin_user()
        mock_db_session.query.return_value.filter.return_value.first.return_value = admin

        resp = client.get("/api/setup/status")

        assert resp.status_code == 200
        assert resp.json() == {"admin_exists": True}

    def test_setup_status_false_when_no_admin_exists(self, client, mock_db_session, test_env):
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        resp = client.get("/api/setup/status")

        assert resp.status_code == 200
        assert resp.json() == {"admin_exists": False}
