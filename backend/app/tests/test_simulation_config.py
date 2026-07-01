"""Allocation rehearsal configuration and registered-heir completion tests."""

from datetime import datetime, timezone
from unittest import mock
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DBSession

from app.auth import get_current_user
from app.main import (
    SimulationConfigRequest,
    _default_simulation_config,
    _validate_simulation_config,
    app,
)
from app.models import Session as SessionModel, User


def test_default_simulation_has_six_items_and_balanced_companions():
    config = _default_simulation_config()
    assert len(config["items"]) == 6
    assert config["required_for_launch"] is True
    assert all(item["image"].endswith(".webp") for item in config["items"])
    assert sum(item["companion_points"]["jordan"] for item in config["items"]) == 1000
    assert sum(item["companion_points"]["casey"] for item in config["items"]) == 1000


def test_simulation_config_accepts_default_template():
    request = SimulationConfigRequest(**_default_simulation_config())
    validated = _validate_simulation_config(request)
    assert validated["title"] == "The Hartwell Family Practice Estate"


def test_simulation_config_rejects_fewer_than_five_enabled_items():
    config = _default_simulation_config()
    config["items"][4]["enabled"] = False
    config["items"][5]["enabled"] = False
    request = SimulationConfigRequest(**config)

    with pytest.raises(HTTPException) as exc:
        _validate_simulation_config(request)
    assert "between 5 and 10" in exc.value.detail


def test_simulation_config_rejects_unbalanced_companion_points():
    config = _default_simulation_config()
    config["items"][0]["companion_points"]["jordan"] -= 10
    request = SimulationConfigRequest(**config)

    with pytest.raises(HTTPException) as exc:
        _validate_simulation_config(request)
    assert "Jordan" in exc.value.detail


def test_registered_heir_completion_is_recorded(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "simulation-test-secret")
    mock_db = mock.MagicMock(spec=DBSession)
    session_id = uuid.uuid4()
    heir_id = uuid.uuid4()
    heir = User(
        id=heir_id,
        session_id=session_id,
        username="Alex",
        role="HEIR",
        status="PENDING",
        practice_completed_at=None,
    )
    session = SessionModel(
        id=session_id,
        title="Practice Estate",
        status="SETUP",
        is_paused=False,
        is_deadlocked=False,
        practice_required=True,
        simulation_published_at=datetime.now(timezone.utc),
    )
    mock_db.query.return_value.filter.return_value.first.side_effect = [heir, session]
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": str(heir_id),
        "role": "HEIR",
        "session_id": str(session_id),
    }

    with mock.patch("app.main.SessionLocal", return_value=mock_db):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/api/heirs/me/simulation/complete")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert heir.practice_completed_at is not None
    mock_db.commit.assert_called_once()
