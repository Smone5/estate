"""
Tests for T43: Custom FAQ CRUD API.

Covers:
- POST /api/sessions/{session_id}/faqs  (Admin create FAQ)
- PUT /api/sessions/{session_id}/faqs/{faq_id}  (Admin update FAQ)
- DELETE /api/sessions/{session_id}/faqs/{faq_id}  (Admin delete FAQ)
- GET /api/sessions/{session_id}/faqs  (Heir/Admin list FAQs)
"""

import os
import uuid
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token
from app.models import CustomFAQ


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


def _make_heir_token():
    """Return a valid JWT token for an Heir user."""
    return create_access_token(
        user_id=str(uuid.uuid4()),
        username="heir_test",
        role="HEIR",
        session_id=str(uuid.uuid4()),
    )


def _make_faq(faq_id=None, session_id=None):
    """Build a CustomFAQ ORM object."""
    return CustomFAQ(
        id=faq_id or uuid.uuid4(),
        session_id=session_id or uuid.uuid4(),
        question="What is the process?",
        answer="The mediation process involves...",
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# POST /api/sessions/{session_id}/faqs   (Admin create)
# ---------------------------------------------------------------------------


class TestCreateFAQ:
    """POST /api/sessions/{session_id}/faqs — Admin creates FAQ."""

    def test_create_requires_auth(self, client, mock_db_session, test_env):
        resp = client.post(
            f"/api/sessions/{uuid.uuid4()}/faqs",
            json={"question": "What is this?", "answer": "This is a test."},
        )
        assert resp.status_code == 401

    def test_create_requires_admin(self, client, mock_db_session, test_env):
        heir_token = _make_heir_token()
        resp = client.post(
            f"/api/sessions/{uuid.uuid4()}/faqs",
            json={"question": "What is this?", "answer": "This is a test."},
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_create_success_returns_201(self, client, mock_db_session, test_env):
        """Admin creates a FAQ successfully."""
        token = _make_admin_token()
        from app.models import Session as SessionModel
        session = SessionModel(
            id=uuid.uuid4(),
            title="Test",
            status="SETUP",
            is_paused=False,
            is_deadlocked=False,
        )

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = session

        resp = client.post(
            f"/api/sessions/{session.id}/faqs",
            json={"question": "What is the process?", "answer": "It involves steps."},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["question"] == "What is the process?"
        assert data["answer"] == "It involves steps."
        assert "id" in data
        mock_db_session.commit.assert_called_once()

    def test_create_short_question_returns_422(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        resp = client.post(
            f"/api/sessions/{uuid.uuid4()}/faqs",
            json={"question": "Hi", "answer": "Short"},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 422

    def test_create_short_answer_returns_422(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        resp = client.post(
            f"/api/sessions/{uuid.uuid4()}/faqs",
            json={"question": "A valid question", "answer": "xx"},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /api/sessions/{session_id}/faqs/{faq_id}   (Admin update)
# ---------------------------------------------------------------------------


class TestUpdateFAQ:
    """PUT /api/sessions/{session_id}/faqs/{faq_id} — Admin updates FAQ."""

    def test_update_requires_auth(self, client, mock_db_session, test_env):
        resp = client.put(
            f"/api/sessions/{uuid.uuid4()}/faqs/{uuid.uuid4()}",
            json={"question": "Updated?", "answer": "Updated answer."},
        )
        assert resp.status_code == 401

    def test_update_requires_admin(self, client, mock_db_session, test_env):
        heir_token = _make_heir_token()
        resp = client.put(
            f"/api/sessions/{uuid.uuid4()}/faqs/{uuid.uuid4()}",
            json={"question": "Updated?", "answer": "Updated answer."},
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_update_success_returns_200(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        session_id = uuid.uuid4()
        faq = _make_faq(session_id=session_id)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = faq

        resp = client.put(
            f"/api/sessions/{session_id}/faqs/{faq.id}",
            json={"question": "Updated question?", "answer": "Updated answer."},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["question"] == "Updated question?"
        assert data["answer"] == "Updated answer."
        assert faq.question == "Updated question?"
        assert faq.answer == "Updated answer."

    def test_update_nonexistent_returns_404(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        resp = client.put(
            f"/api/sessions/{uuid.uuid4()}/faqs/{uuid.uuid4()}",
            json={"question": "Updated?", "answer": "Updated answer."},
            cookies={"estate_session": token},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/sessions/{session_id}/faqs/{faq_id}   (Admin delete)
# ---------------------------------------------------------------------------


class TestDeleteFAQ:
    """DELETE /api/sessions/{session_id}/faqs/{faq_id} — Admin deletes FAQ."""

    def test_delete_requires_auth(self, client, mock_db_session, test_env):
        resp = client.delete(f"/api/sessions/{uuid.uuid4()}/faqs/{uuid.uuid4()}")
        assert resp.status_code == 401

    def test_delete_requires_admin(self, client, mock_db_session, test_env):
        heir_token = _make_heir_token()
        resp = client.delete(
            f"/api/sessions/{uuid.uuid4()}/faqs/{uuid.uuid4()}",
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 403

    def test_delete_success_returns_200(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        session_id = uuid.uuid4()
        faq = _make_faq(session_id=session_id)

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = faq

        resp = client.delete(
            f"/api/sessions/{session_id}/faqs/{faq.id}",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "deleted" in data["message"].lower()
        mock_db_session.commit.assert_called_once()

    def test_delete_nonexistent_returns_404(self, client, mock_db_session, test_env):
        token = _make_admin_token()
        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = None

        resp = client.delete(
            f"/api/sessions/{uuid.uuid4()}/faqs/{uuid.uuid4()}",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/sessions/{session_id}/faqs   (Heir/Admin list)
# ---------------------------------------------------------------------------


class TestListFAQs:
    """GET /api/sessions/{session_id}/faqs — Heir/Admin lists FAQs."""

    def test_list_requires_auth(self, client, mock_db_session, test_env):
        resp = client.get(f"/api/sessions/{uuid.uuid4()}/faqs")
        assert resp.status_code == 401

    def test_list_allows_heir(self, client, mock_db_session, test_env):
        """Heir should be able to read FAQs."""
        heir_token = _make_heir_token()

        from app.models import Session as SessionModel
        session = SessionModel(
            id=uuid.uuid4(),
            title="Test",
            status="ACTIVE",
            is_paused=False,
            is_deadlocked=False,
        )

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = session

        # Mock the FAQ query
        mock_faq_query = mock.MagicMock()
        mock_faq_filter = mock_faq_query.filter.return_value
        mock_faq_order = mock_faq_filter.order_by.return_value
        mock_faq_order.all.return_value = []

        # First query for session, second for FAQs
        mock_db_session.query.side_effect = [mock_query, mock_faq_query]

        resp = client.get(
            f"/api/sessions/{session.id}/faqs",
            cookies={"estate_session": heir_token},
        )
        assert resp.status_code == 200

    def test_list_allows_admin(self, client, mock_db_session, test_env):
        """Admin should be able to read FAQs."""
        token = _make_admin_token()

        from app.models import Session as SessionModel
        session = SessionModel(
            id=uuid.uuid4(),
            title="Test",
            status="SETUP",
            is_paused=False,
            is_deadlocked=False,
        )

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = session

        mock_faq_query = mock.MagicMock()
        mock_faq_filter = mock_faq_query.filter.return_value
        mock_faq_order = mock_faq_filter.order_by.return_value
        mock_faq_order.all.return_value = []

        mock_db_session.query.side_effect = [mock_query, mock_faq_query]

        resp = client.get(
            f"/api/sessions/{session.id}/faqs",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200

    def test_list_returns_faqs(self, client, mock_db_session, test_env):
        """List endpoint returns FAQ data."""
        token = _make_admin_token()
        faq = _make_faq()

        from app.models import Session as SessionModel
        session = SessionModel(
            id=uuid.uuid4(),
            title="Test",
            status="SETUP",
            is_paused=False,
            is_deadlocked=False,
        )

        mock_query = mock_db_session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_filter.first.return_value = session

        mock_faq_query = mock.MagicMock()
        mock_faq_filter = mock_faq_query.filter.return_value
        mock_faq_order = mock_faq_filter.order_by.return_value
        mock_faq_order.all.return_value = [faq]

        mock_db_session.query.side_effect = [mock_query, mock_faq_query]

        resp = client.get(
            f"/api/sessions/{session.id}/faqs",
            cookies={"estate_session": token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["question"] == faq.question
        assert data[0]["answer"] == faq.answer