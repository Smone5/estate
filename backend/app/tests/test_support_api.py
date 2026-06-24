"""
Tests for T42: Support Request & Help CRUD API.

Covers:
- POST /api/sessions/{session_id}/help  (Heir submits help request)
- GET /api/sessions/{session_id}/help   (Admin lists help requests)
- POST /api/help/{ticket_id}/reply      (Admin replies to ticket)
- POST /api/help/{ticket_id}/resolve    (Admin resolves ticket)
"""

import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token
from app.models import User, SupportRequest


TEST_JWT_SECRET = "test-secret-key-for-tests-only-do-not-use-in-production"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    """Set required env vars for auth and encryption modules."""
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("ENCRYPTION_KEY", "x" * 43)
    monkeypatch.setenv("STORAGE_DRIVER", "MOCK")


@pytest.fixture
def mock_db_session():
    """Return a MagicMock wrapping a SQLAlchemy session."""
    session = mock.MagicMock(spec=DBSession)
    return session


@pytest.fixture
def client(mock_db_session):
    """FastAPI TestClient with a mocked database session.
    
    The real websocket_manager singleton is used — since no WebSocket
    connections are active in tests, broadcast operations are safe no-ops.
    """
    with mock.patch("app.main.SessionLocal", return_value=mock_db_session):
        from app.main import app
        yield TestClient(app, raise_server_exceptions=False)


def _make_heir_token(heir_id=None, session_id=None):
    """Return a valid JWT token for an Heir user."""
    return create_access_token(
        user_id=heir_id or str(uuid.uuid4()),
        username="heir_test",
        role="HEIR",
        session_id=session_id or str(uuid.uuid4()),
    )


def _make_admin_token():
    """Return a valid JWT token for an Admin user."""
    return create_access_token(
        user_id=str(uuid.uuid4()),
        username="executor",
        role="ADMIN",
        session_id=None,
    )


def _make_support_request(ticket_id=None, status="OPEN"):
    """Build a SupportRequest ORM object."""
    return SupportRequest(
        id=ticket_id or uuid.uuid4(),
        session_id=uuid.uuid4(),
        heir_id=uuid.uuid4(),
        message="I need help with my points allocation",
        status=status,
        admin_response=None,
        responded_at=None,
        resolved_at=None,
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/help
# ---------------------------------------------------------------------------


class TestCreateHelpRequest:
    """POST /api/sessions/{session_id}/help — Heir submits help."""

    def test_create_requires_auth(self, client, mock_db_session, test_env):
        resp = client.post(
            f"/api/sessions/{uuid.uuid4()}/help",
            json={"message": "I need help with valuation"},
        )
        assert resp.status_code == 401

    def test_create_requires_heir_role(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        resp = client.post(
            f"/api/sessions/{uuid.uuid4()}/help",
            json={"message": "I need help"},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 403

    def test_create_success_returns_201(self, client, mock_db_session, test_env):
        # Mock session lookup
        from app.models import Session as SessionModel
        session = SessionModel(
            id=uuid.uuid4(),
            title="Test",
            status="ACTIVE",
            is_paused=False,
            is_deadlocked=False,
        )
        heir_token = _make_heir_token(session_id=str(session.id))
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = session

        resp = client.post(
            f"/api/sessions/{session.id}/help",
            json={"message": "I need help with my points"},
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "submitted"
        mock_db_session.commit.assert_called_once()

    def test_create_short_message_returns_422(self, client, mock_db_session, test_env):
        heir_token = _make_heir_token()

        resp = client.post(
            f"/api/sessions/{uuid.uuid4()}/help",
            json={"message": "hi"},
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 422

    def test_create_message_too_long_returns_422(self, client, mock_db_session, test_env):
        heir_token = _make_heir_token()
        resp = client.post(
            f"/api/sessions/{uuid.uuid4()}/help",
            json={"message": "x" * 1001},
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id}/help
# ---------------------------------------------------------------------------


class TestListHelpRequests:
    """GET /api/sessions/{session_id}/help — Admin lists help."""

    def test_list_requires_auth(self, client, mock_db_session, test_env):
        resp = client.get(f"/api/sessions/{uuid.uuid4()}/help")
        assert resp.status_code == 401

    def test_list_requires_admin(self, client, mock_db_session, test_env):
        heir_token = _make_heir_token()
        resp = client.get(
            f"/api/sessions/{uuid.uuid4()}/help",
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_list_returns_empty_list(self, client, mock_db_session, test_env):
        token = _make_admin_token()

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_order = mock_filter.order_by.return_value
        mock_order.all.return_value = []

        resp = client.get(
            f"/api/sessions/{uuid.uuid4()}/help",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_returns_tickets(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        ticket = _make_support_request()

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_order = mock_filter.order_by.return_value
        mock_order.all.return_value = [ticket]

        # Mock the User query for resolving heir usernames
        heir = User(
            id=uuid.uuid4(),
            username="heir_test",
            role="HEIR",
        )

        # Side effect: first query returns session, second query (for User.name) returns heir
        def query_side_effect(model):
            if model == User:
                m = mock.MagicMock()
                m.filter.return_value.first.return_value = heir
                return m
            return mock_query

        mock_db_session.query.side_effect = query_side_effect

        resp = client.get(
            f"/api/sessions/{uuid.uuid4()}/help",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "OPEN"
        assert data[0]["username"] == "heir_test"
        assert "admin_response" in data[0]
        assert "responded_at" in data[0]


# ---------------------------------------------------------------------------
# POST /api/help/{ticket_id}/reply
# ---------------------------------------------------------------------------


class TestReplyToHelpRequest:
    """POST /api/help/{ticket_id}/reply — Admin replies to a ticket."""

    def test_reply_requires_auth(self, client, mock_db_session, test_env):
        resp = client.post(
            f"/api/help/{uuid.uuid4()}/reply",
            json={"response": "Thanks, I will review this."},
        )
        assert resp.status_code == 401

    def test_reply_requires_admin(self, client, mock_db_session, test_env):
        heir_token = _make_heir_token()
        resp = client.post(
            f"/api/help/{uuid.uuid4()}/reply",
            json={"response": "Thanks, I will review this."},
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_reply_success_returns_ticket_record(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        ticket = _make_support_request(status="OPEN")

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = ticket

        resp = client.post(
            f"/api/help/{ticket.id}/reply",
            json={"response": "I adjusted the catalog note for that item."},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "RESPONDED"
        assert data["admin_response"] == "I adjusted the catalog note for that item."
        assert ticket.status == "RESPONDED"
        assert ticket.admin_response == "I adjusted the catalog note for that item."
        assert ticket.responded_at is not None
        mock_db_session.commit.assert_called_once()

    def test_reply_to_resolved_ticket_returns_400(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        ticket = _make_support_request(status="RESOLVED")

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = ticket

        resp = client.post(
            f"/api/help/{ticket.id}/reply",
            json={"response": "Follow-up"},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/help/{ticket_id}/resolve
# ---------------------------------------------------------------------------


class TestResolveHelpRequest:
    """POST /api/help/{ticket_id}/resolve — Admin resolves ticket."""

    def test_resolve_requires_auth(self, client, mock_db_session, test_env):
        resp = client.post(f"/api/help/{uuid.uuid4()}/resolve")
        assert resp.status_code == 401

    def test_resolve_requires_admin(self, client, mock_db_session, test_env):
        heir_token = _make_heir_token()
        resp = client.post(
            f"/api/help/{uuid.uuid4()}/resolve",
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_resolve_success_returns_200(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        ticket = _make_support_request(status="OPEN")

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = ticket

        resp = client.post(
            f"/api/help/{ticket.id}/resolve",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert ticket.status == "RESOLVED"
        mock_db_session.commit.assert_called_once()

    def test_resolve_nonexistent_returns_404(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        resp = client.post(
            f"/api/help/{uuid.uuid4()}/resolve",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/help/direct
# ---------------------------------------------------------------------------


class TestCreateDirectHelpMessage:
    """POST /api/sessions/{session_id}/help/direct — Admin sends direct message."""

    def test_direct_requires_auth(self, client, mock_db_session, test_env):
        resp = client.post(
            f"/api/sessions/{uuid.uuid4()}/help/direct",
            json={"heir_id": str(uuid.uuid4()), "message": "Direct message"},
        )
        assert resp.status_code == 401

    def test_direct_requires_admin(self, client, mock_db_session, test_env):
        heir_token = _make_heir_token()
        resp = client.post(
            f"/api/sessions/{uuid.uuid4()}/help/direct",
            json={"heir_id": str(uuid.uuid4()), "message": "Direct message"},
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_direct_success_returns_201(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        session_id = uuid.uuid4()
        heir_id = uuid.uuid4()

        # Mock Session lookup
        from app.models import Session as SessionModel
        session_mock = SessionModel(
            id=session_id,
            title="Test Session",
            status="ACTIVE",
        )
        
        # Mock Heir lookup
        heir_mock = User(
            id=heir_id,
            username="heir_test",
            role="HEIR",
            session_id=session_id,
        )

        mock_query = mock_db_session.query.return_value
        
        def query_side_effect(model):
            m = mock.MagicMock()
            if model == SessionModel:
                m.filter.return_value.first.return_value = session_mock
            elif model == User:
                m.filter.return_value.first.return_value = heir_mock
            else:
                m.filter.return_value.first.return_value = None
            return m

        mock_db_session.query.side_effect = query_side_effect

        resp = client.post(
            f"/api/sessions/{session_id}/help/direct",
            json={"heir_id": str(heir_id), "message": "Please confirm details"},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "RESPONDED"
        assert data["admin_response"] == "Please confirm details"
        mock_db_session.commit.assert_called_once()

