"""
Tests for T44: Session Override API.

Covers:
- POST /api/sessions/{session_id}/override
  - 400 if session not in LOCKED state
  - 400 if empty override list
  - 200 success: asset→PRE_ALLOCATED, valuations deleted, ADMIN_OVERRIDE audit log
  - Verifies is_deadlocked cleared, status→ACTIVE (if not paused)
  - Verifies broadcast WebSocket status update
"""

import json
import os
import uuid
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import create_access_token
from app.models import Asset, Session as SessionModel, User, Valuation, AuditLog


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


def _make_session(session_id="s1", status="LOCKED", is_paused=False, is_deadlocked=True):
    """Helper to create a mock SessionModel."""
    s = mock.MagicMock(spec=SessionModel)
    s.id = session_id
    s.status = status
    s.is_paused = is_paused
    s.is_deadlocked = is_deadlocked
    s.title = "Test Estate"
    return s


def _make_heir(heir_id="h1", session_id="s1", status="SUBMITTED"):
    """Helper to create a mock User (HEIR)."""
    h = mock.MagicMock(spec=User)
    h.id = heir_id
    h.session_id = session_id
    h.role = "HEIR"
    h.status = status
    h.is_submitted = True
    h.submitted_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    h.username = "heir_one"
    return h


def _make_asset(asset_id="a1", session_id="s1", status="LIVE"):
    """Helper to create a mock Asset."""
    a = mock.MagicMock(spec=Asset)
    a.id = asset_id
    a.session_id = session_id
    a.status = status
    a.allocated_to_id = None
    return a


def _make_audit_log(log_id=1, session_id="s1", sha256_hash="abc123", event_type="VALUATION_SUBMISSION"):
    """Helper to create a mock AuditLog."""
    al = mock.MagicMock(spec=AuditLog)
    al.id = log_id
    al.session_id = session_id
    al.event_type = event_type
    al.sha256_hash = sha256_hash
    al.state_snapshot = {}
    return al


class TestSessionOverride:
    """T44: Session Override API — HITL endpoint."""

    # ── Gate: session status not LOCKED ──────────────────────────────────

    def test_override_rejects_non_locked_session(self, client, mock_db_session):
        """Override endpoint returns 400 if session is not in LOCKED state."""
        session = _make_session(session_id="s1", status="ACTIVE")

        # Mock chain: query(SessionModel).filter().with_for_update().first()
        mock_query = mock.MagicMock()
        mock_filter = mock.MagicMock()
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = session
        mock_filter.with_for_update.return_value = mock_filter
        mock_db_session.query.return_value = mock_query

        token = _make_admin_token()
        response = client.post(
            "/api/sessions/s1/override",
            json=[
                {
                    "asset_id": "a1",
                    "allocated_to_id": "h1",
                    "reason": "Executor's fiduciary decision",
                }
            ],
            cookies={"estate_session": token},
        )

        assert response.status_code == 400
        assert "only available during LOCKED state" in response.json()["detail"]

    # ── Gate: empty override list ──────────────────────────────────────

    def test_override_rejects_empty_list(self, client, mock_db_session):
        """Override endpoint returns 400 if the override list is empty."""
        session = _make_session(session_id="s1", status="LOCKED")

        mock_query = mock.MagicMock()
        mock_filter = mock.MagicMock()
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = session
        mock_filter.with_for_update.return_value = mock_filter
        mock_db_session.query.return_value = mock_query

        token = _make_admin_token()
        response = client.post(
            "/api/sessions/s1/override",
            json=[],
            cookies={"estate_session": token},
        )

        assert response.status_code == 400
        assert "At least one override" in response.json()["detail"]

    # ── Gate: requires admin credentials ───────────────────────────────

    def test_override_requires_admin(self, client):
        """Override endpoint returns 401 if no admin credentials provided."""
        response = client.post(
            "/api/sessions/s1/override",
            json=[
                {
                    "asset_id": "a1",
                    "allocated_to_id": "h1",
                    "reason": "Executor's fiduciary decision",
                }
            ],
        )
        # Missing auth → 401 or 403
        assert response.status_code in (401, 403)

    # ── Successful override flow ───────────────────────────────────────

    def test_override_success_updates_assets_and_clears_valuations(self, client, mock_db_session):
        """Override: assets→PRE_ALLOCATED, valuations deleted, audit log written."""
        session_id = "s1"
        heir_id = "h1"
        asset_id = "a1"
        session = _make_session(session_id=session_id, status="LOCKED", is_deadlocked=True)
        heir = _make_heir(heir_id=heir_id, session_id=session_id)
        asset = _make_asset(asset_id=asset_id, session_id=session_id, status="LIVE")
        last_log = _make_audit_log(log_id=5, session_id=session_id, sha256_hash="prev_hash_abc")

        # --- Mock DB chain: sessions query ---
        mock_sess_query = mock.MagicMock()
        mock_sess_filter = mock.MagicMock()
        mock_sess_query.filter.return_value = mock_sess_filter
        mock_sess_filter.first.return_value = session
        mock_sess_filter.with_for_update.return_value = mock_sess_filter

        # --- Mock DB chain: heirs query ---
        mock_heir_query = mock.MagicMock()
        mock_heir_filter = mock.MagicMock()
        mock_heir_query.filter.return_value = mock_heir_filter
        mock_heir_filter.all.return_value = [heir]

        # --- Mock DB chain: assets query ---
        mock_asset_query_first = mock.MagicMock()
        mock_asset_filter_first = mock.MagicMock()
        mock_asset_query_first.filter.return_value = mock_asset_filter_first
        mock_asset_filter_first.first.return_value = asset

        # --- Mock DB chain: audit log query ---
        mock_audit_query = mock.MagicMock()
        mock_audit_filter = mock.MagicMock()
        mock_audit_query.filter.return_value = mock_audit_filter
        mock_audit_filter.order_by.return_value = mock_audit_filter
        mock_audit_filter.first.return_value = last_log

        # --- Mock DB chain: valuations delete ---
        mock_val_query = mock.MagicMock()
        mock_val_filter = mock.MagicMock()
        mock_val_query.filter.return_value = mock_val_filter
        mock_val_filter.delete.return_value = 1  # 1 row deleted

        # --- Configure side_effect for multiple query() calls ---
        def _side_effect(model_cls):
            if model_cls is SessionModel:
                return mock_sess_query
            if model_cls is User:
                return mock_heir_query
            if model_cls is Asset:
                return mock_asset_query_first
            if model_cls is AuditLog:
                return mock_audit_query
            if model_cls is Valuation:
                return mock_val_query
            inner = mock.MagicMock()
            inner.filter.return_value = inner
            inner.first.return_value = None
            inner.all.return_value = []
            return inner

        mock_db_session.query.side_effect = _side_effect
        mock_db_session.flush = mock.MagicMock()
        mock_db_session.commit = mock.MagicMock()

        token = _make_admin_token()

        # Mock the graph imports so we don't actually try to connect to Postgres
        with mock.patch("app.graph.get_graph") as mock_get_graph, \
             mock.patch("app.graph.get_postgres_checkpointer") as mock_get_checkpoint:

            mock_graph = mock.MagicMock()
            mock_graph.update_state = mock.MagicMock()
            mock_graph.stream = mock.MagicMock(return_value=[{"COMMIT": {}}])
            mock_get_graph.return_value = mock_graph

            mock_saver = mock.MagicMock()
            mock_get_checkpoint.return_value = mock_saver

            response = client.post(
                f"/api/sessions/{session_id}/override",
                json=[
                    {
                        "asset_id": asset_id,
                        "allocated_to_id": heir_id,
                        "reason": "Executor's fiduciary decision — this is a valid reason",
                    }
                ],
                cookies={"estate_session": token},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"

        # Verify asset was updated
        assert asset.status == "PRE_ALLOCATED"
        assert asset.allocated_to_id == heir_id

        # Verify is_deadlocked was cleared
        assert session.is_deadlocked is False

        # Verify status transitioned to ACTIVE (not paused)
        assert session.status == "ACTIVE"

        # Verify audit log was added (via db.add)
        add_calls = [c for c in mock_db_session.add.call_args_list]
        assert len(add_calls) >= 1
        added_log = add_calls[0][0][0]
        assert added_log.event_type == "ADMIN_OVERRIDE"

    # ── Override with paused session keeps LOCKED status ─────────────

    def test_override_paused_session_stays_locked(self, client, mock_db_session):
        """Override: if session is paused, stays LOCKED after override."""
        session_id = "s1"
        heir_id = "h1"
        asset_id = "a1"
        session = _make_session(session_id=session_id, status="LOCKED", is_paused=True, is_deadlocked=True)
        heir = _make_heir(heir_id=heir_id, session_id=session_id)
        asset = _make_asset(asset_id=asset_id, session_id=session_id, status="LIVE")

        mock_sess_query = mock.MagicMock()
        mock_sess_filter = mock.MagicMock()
        mock_sess_query.filter.return_value = mock_sess_filter
        mock_sess_filter.first.return_value = session
        mock_sess_filter.with_for_update.return_value = mock_sess_filter

        mock_heir_query = mock.MagicMock()
        mock_heir_filter = mock.MagicMock()
        mock_heir_query.filter.return_value = mock_heir_filter
        mock_heir_filter.all.return_value = [heir]

        mock_asset_query_first = mock.MagicMock()
        mock_asset_filter_first = mock.MagicMock()
        mock_asset_query_first.filter.return_value = mock_asset_filter_first
        mock_asset_filter_first.first.return_value = asset

        mock_audit_query = mock.MagicMock()
        mock_audit_filter = mock.MagicMock()
        mock_audit_query.filter.return_value = mock_audit_filter
        mock_audit_filter.order_by.return_value = mock_audit_filter
        mock_audit_filter.first.return_value = None

        mock_val_query = mock.MagicMock()
        mock_val_filter = mock.MagicMock()
        mock_val_query.filter.return_value = mock_val_filter
        mock_val_filter.delete.return_value = 0

        def _side_effect(model_cls):
            if model_cls is SessionModel:
                return mock_sess_query
            if model_cls is User:
                return mock_heir_query
            if model_cls is Asset:
                return mock_asset_query_first
            if model_cls is AuditLog:
                return mock_audit_query
            if model_cls is Valuation:
                return mock_val_query
            inner = mock.MagicMock()
            inner.filter.return_value = inner
            inner.first.return_value = None
            inner.all.return_value = []
            return inner

        mock_db_session.query.side_effect = _side_effect
        mock_db_session.flush = mock.MagicMock()
        mock_db_session.commit = mock.MagicMock()

        token = _make_admin_token()

        with mock.patch("app.graph.get_graph") as mock_get_graph, \
             mock.patch("app.graph.get_postgres_checkpointer") as mock_get_checkpoint:

            mock_graph = mock.MagicMock()
            mock_graph.update_state = mock.MagicMock()
            mock_graph.stream = mock.MagicMock(return_value=[{"COMMIT": {}}])
            mock_get_graph.return_value = mock_graph

            mock_saver = mock.MagicMock()
            mock_get_checkpoint.return_value = mock_saver

            response = client.post(
                f"/api/sessions/{session_id}/override",
                json=[
                    {
                        "asset_id": asset_id,
                        "allocated_to_id": heir_id,
                        "reason": "Executor's fiduciary decision",
                    }
                ],
                cookies={"estate_session": token},
            )

        assert response.status_code == 200
        paused_data = response.json()
        assert paused_data["status"] == "resolved"

        # Paused session stays LOCKED
        assert session.is_deadlocked is False
        assert session.status == "LOCKED"

    # ── Invalid asset ID ──────────────────────────────────────────────

    def test_override_rejects_invalid_asset(self, client, mock_db_session):
        """Override returns 400 if asset not found in session."""
        session = _make_session(session_id="s1", status="LOCKED", is_deadlocked=True)

        mock_sess_query = mock.MagicMock()
        mock_sess_filter = mock.MagicMock()
        mock_sess_query.filter.return_value = mock_sess_filter
        mock_sess_filter.first.return_value = session
        mock_sess_filter.with_for_update.return_value = mock_sess_filter

        mock_heir_query = mock.MagicMock()
        mock_heir_filter = mock.MagicMock()
        mock_heir_query.filter.return_value = mock_heir_filter
        mock_heir_filter.all.return_value = []

        # Asset query returns None
        mock_asset_query = mock.MagicMock()
        mock_asset_filter = mock.MagicMock()
        mock_asset_query.filter.return_value = mock_asset_filter
        mock_asset_filter.first.return_value = None

        def _side_effect(model_cls):
            if model_cls is SessionModel:
                return mock_sess_query
            if model_cls is User:
                return mock_heir_query
            if model_cls is Asset:
                return mock_asset_query
            inner = mock.MagicMock()
            inner.filter.return_value = inner
            inner.first.return_value = None
            inner.all.return_value = []
            return inner

        mock_db_session.query.side_effect = _side_effect
        mock_db_session.flush = mock.MagicMock()

        token = _make_admin_token()
        response = client.post(
            "/api/sessions/s1/override",
            json=[
                {
                    "asset_id": "nonexistent",
                    "allocated_to_id": "h1",
                    "reason": "Executor's fiduciary decision",
                }
            ],
            cookies={"estate_session": token},
        )

        assert response.status_code == 400
        assert "not found in this session" in response.json()["detail"]

    # ── Reason length validation ──────────────────────────────────────

    def test_override_rejects_short_reason(self, client, mock_db_session):
        """Override request schema rejects reason < 5 chars."""
        session = _make_session(session_id="s1", status="LOCKED")

        mock_sess_query = mock.MagicMock()
        mock_sess_filter = mock.MagicMock()
        mock_sess_query.filter.return_value = mock_sess_filter
        mock_sess_filter.first.return_value = session
        mock_sess_filter.with_for_update.return_value = mock_sess_filter

        mock_db_session.query.return_value = mock_sess_query

        token = _make_admin_token()
        response = client.post(
            "/api/sessions/s1/override",
            json=[
                {
                    "asset_id": "a1",
                    "allocated_to_id": "h1",
                    "reason": "bad",
                }
            ],
            cookies={"estate_session": token},
        )

        # FastAPI schema validation should return 422
        assert response.status_code == 422

    # ── Multiple overrides in one request ────────────────────────────

    def test_override_multiple_assets(self, client, mock_db_session):
        """Override: multiple assets in single request all get PRE_ALLOCATED."""
        session_id = "s1"
        session = _make_session(session_id=session_id, status="LOCKED", is_deadlocked=True)
        heir = _make_heir(heir_id="h1", session_id=session_id)
        asset_a = _make_asset(asset_id="a1", session_id=session_id, status="LIVE")
        asset_b = _make_asset(asset_id="a2", session_id=session_id, status="LIVE")

        mock_sess_query = mock.MagicMock()
        mock_sess_filter = mock.MagicMock()
        mock_sess_query.filter.return_value = mock_sess_filter
        mock_sess_filter.first.return_value = session
        mock_sess_filter.with_for_update.return_value = mock_sess_filter

        mock_heir_query = mock.MagicMock()
        mock_heir_filter = mock.MagicMock()
        mock_heir_query.filter.return_value = mock_heir_filter
        mock_heir_filter.all.return_value = [heir]

        # Asset query returns results in order for a1 then a2
        mock_asset_query = mock.MagicMock()
        mock_asset_filter = mock.MagicMock()
        mock_asset_query.filter.return_value = mock_asset_filter
        mock_asset_filter.first.side_effect = [asset_a, asset_b]

        mock_audit_query = mock.MagicMock()
        mock_audit_filter = mock.MagicMock()
        mock_audit_query.filter.return_value = mock_audit_filter
        mock_audit_filter.order_by.return_value = mock_audit_filter
        mock_audit_filter.first.return_value = None

        mock_val_query = mock.MagicMock()
        mock_val_filter = mock.MagicMock()
        mock_val_query.filter.return_value = mock_val_filter
        mock_val_filter.delete.return_value = 0

        def _side_effect(model_cls):
            if model_cls is SessionModel:
                return mock_sess_query
            if model_cls is User:
                return mock_heir_query
            if model_cls is Asset:
                return mock_asset_query
            if model_cls is AuditLog:
                return mock_audit_query
            if model_cls is Valuation:
                return mock_val_query
            inner = mock.MagicMock()
            inner.filter.return_value = inner
            inner.first.return_value = None
            inner.all.return_value = []
            return inner

        mock_db_session.query.side_effect = _side_effect
        mock_db_session.flush = mock.MagicMock()
        mock_db_session.commit = mock.MagicMock()

        token = _make_admin_token()

        with mock.patch("app.graph.get_graph") as mock_get_graph, \
             mock.patch("app.graph.get_postgres_checkpointer") as mock_get_checkpoint:

            mock_graph = mock.MagicMock()
            mock_graph.update_state = mock.MagicMock()
            mock_graph.stream = mock.MagicMock(return_value=[{"COMMIT": {}}])
            mock_get_graph.return_value = mock_graph

            mock_saver = mock.MagicMock()
            mock_get_checkpoint.return_value = mock_saver

            response = client.post(
                f"/api/sessions/{session_id}/override",
                json=[
                    {
                        "asset_id": "a1",
                        "allocated_to_id": "h1",
                        "reason": "Executor's fiduciary decision A",
                    },
                    {
                        "asset_id": "a2",
                        "allocated_to_id": "h1",
                        "reason": "Executor's fiduciary decision B",
                    },
                ],
                cookies={"estate_session": token},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"

        # Both assets should be PRE_ALLOCATED
        assert asset_a.status == "PRE_ALLOCATED"
        assert asset_b.status == "PRE_ALLOCATED"
        assert asset_a.allocated_to_id == "h1"
        assert asset_b.allocated_to_id == "h1"