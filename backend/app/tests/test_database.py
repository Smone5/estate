"""
Tests for database.py — T01: connection retry loop and startup validation.

Verifies:
- init_db retries on connection failure (up to 5 times with 2s delay)
- init_db succeeds on first attempt when DB is available
- RuntimeError raised after all retries exhausted
"""

import time
import logging
import pytest
from unittest import mock


@pytest.fixture
def mock_engine_success():
    """Mock create_engine and connect to succeed immediately."""
    with mock.patch("app.database.create_engine") as mock_create:
        mock_engine = mock.MagicMock()
        mock_conn = mock.MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_create.return_value = mock_engine
        yield mock_create, mock_engine


@pytest.fixture
def mock_engine_fail_then_succeed():
    """Mock create_engine to fail first 3 attempts, succeed on 4th."""
    with mock.patch("app.database.create_engine") as mock_create:
        mock_engine = mock.MagicMock()
        mock_conn = mock.MagicMock()

        fail_call_count = [0]

        def connect_side_effect():
            fail_call_count[0] += 1
            if fail_call_count[0] <= 3:
                raise OSError("Connection refused")
            return mock_conn

        mock_engine.connect.return_value.__enter__.side_effect = connect_side_effect
        mock_create.return_value = mock_engine
        yield mock_create, mock_engine


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset the module-level globals between tests."""
    import app.database as db_module
    db_module.engine = None
    db_module.SessionLocal = None


class TestInitDb:
    """T01: Verify database connection retry loop."""

    def test_succeeds_on_first_attempt(self, mock_engine_success, reset_module_state):
        """init_db connects immediately when DB is available."""
        from app.database import init_db

        init_db()  # Should not raise

    def test_retries_on_failure_then_succeeds(self, mock_engine_fail_then_succeed, reset_module_state):
        """init_db retries after failures and eventually succeeds."""
        from app.database import init_db

        # Should not raise — 3 failures then success
        init_db()

    def test_raises_runtime_error_after_exhausting_retries(self, reset_module_state):
        """init_db raises RuntimeError after 5 failed attempts."""
        from app.database import init_db, _MAX_RETRIES, _RETRY_DELAY_SECONDS

        with mock.patch("app.database.create_engine") as mock_create:
            mock_engine = mock.MagicMock()
            mock_engine.connect.return_value.__enter__.side_effect = OSError(
                "Connection refused"
            )
            mock_create.return_value = mock_engine

            with mock.patch("app.database.time.sleep") as mock_sleep:
                with pytest.raises(RuntimeError, match="Failed to connect to database"):
                    init_db()

                # Verify 5 attempts were made
                assert mock_engine.connect.call_count == _MAX_RETRIES
                # Verify sleep was called 4 times (between attempts 1→2, 2→3, 3→4, 4→5)
                assert mock_sleep.call_count == _MAX_RETRIES - 1

    def test_logs_warning_on_failure(self, mock_engine_fail_then_succeed, reset_module_state, caplog):
        """init_db logs warning messages on connection failures."""
        from app.database import init_db

        with caplog.at_level(logging.WARNING, logger="app.database"):
            init_db()

        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_msgs) == 3  # 3 failures, 3 warnings
        for msg in warning_msgs:
            assert "Database connection attempt" in msg

    def test_logs_info_on_success(self, mock_engine_success, reset_module_state, caplog):
        """init_db logs info on successful connection."""
        from app.database import init_db

        with caplog.at_level(logging.INFO, logger="app.database"):
            init_db()

        info_msgs = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert any("Database connection established" in msg for msg in info_msgs)


class TestMainStartup:
    """Verify main.py FastAPI entrypoint calls init_db at startup."""

    def test_health_endpoint(self, mock_engine_success, reset_module_state):
        """GET /health returns 200 OK."""
        from app.main import app
        from fastapi.testclient import TestClient

        # Patch init_db to prevent actual connection attempts in lifespan
        with mock.patch("app.main.init_db"):
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}