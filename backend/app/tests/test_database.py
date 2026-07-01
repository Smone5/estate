"""
Tests for database.py — T01: connection retry loop and startup validation.
Tests for models.py  — T02: SQLAlchemy models, constraints, and relationships.

T01 verifies:
- init_db retries on connection failure (up to 5 times with 2s delay)
- init_db succeeds on first attempt when DB is available
- RuntimeError raised after all retries exhausted

T02 verifies (metadata-level — no PostgreSQL DDL required):
- All 8 models importable and registered in Base.metadata
- CheckConstraints declared with correct names
- UniqueConstraints declared with correct names
- B-Tree indexes declared on foreign-key columns
- Relationship back-references correctly wired
- Cascade delete-orphan configured on session children
"""

import logging

import pytest
from unittest import mock

from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
    Index,
)
from app.database import Base
from app.models import (
    Session,
    User,
    Asset,
    Valuation,
    AuditLog,
    SupportRequest,
    ChatMessage,
    CustomFAQ,
    AssetImage,
    Category,
)


# ═════════════════════════════════════════════════════════════════════
# T01 fixtures and tests
# ═════════════════════════════════════════════════════════════════════

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
        init_db()

    def test_retries_on_failure_then_succeeds(
        self, mock_engine_fail_then_succeed, reset_module_state
    ):
        """init_db retries after failures and eventually succeeds."""
        from app.database import init_db
        init_db()

    def test_raises_runtime_error_after_exhausting_retries(self, reset_module_state):
        """init_db raises RuntimeError after 5 failed attempts."""
        from app.database import init_db

        with mock.patch("app.database.create_engine") as mock_create:
            mock_engine = mock.MagicMock()
            mock_engine.connect.return_value.__enter__.side_effect = OSError(
                "Connection refused"
            )
            mock_create.return_value = mock_engine

            with mock.patch("app.database.time.sleep") as mock_sleep:
                with pytest.raises(RuntimeError, match="Failed to connect to database"):
                    init_db()

                from app.database import _MAX_RETRIES

                assert mock_engine.connect.call_count == _MAX_RETRIES
                assert mock_sleep.call_count == _MAX_RETRIES - 1

    def test_logs_warning_on_failure(
        self, mock_engine_fail_then_succeed, reset_module_state, caplog
    ):
        """init_db logs warning messages on connection failures."""
        from app.database import init_db

        with caplog.at_level(logging.WARNING, logger="app.database"):
            init_db()

        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert len(warning_msgs) == 3
        for msg in warning_msgs:
            assert "Database connection attempt" in msg

    def test_logs_info_on_success(
        self, mock_engine_success, reset_module_state, caplog
    ):
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

        with mock.patch("app.main.init_db"):
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}


# ═════════════════════════════════════════════════════════════════════
# T02: SQLAlchemy Models & Relations (metadata-level verification)
# ═════════════════════════════════════════════════════════════════════


class TestAllTenTablesExist:
    """T02: Confirm all tables are registered with SQLAlchemy metadata."""

    def test_all_tables_present(self):
        table_names = sorted(Base.metadata.tables.keys())
        expected = sorted([
            "sessions",
            "users",
            "assets",
            "valuations",
            "audit_logs",
            "chat_messages",
            "support_requests",
            "custom_faqs",
            "asset_images",
            "categories",
            "app_settings",
        ])
        assert table_names == expected


class TestSessionsModel:
    """T02: sessions table schema verification."""

    def test_columns_present(self):
        table = Base.metadata.tables["sessions"]
        expected_cols = {
            "id", "title", "status", "is_paused", "paused_at",
            "is_deadlocked", "announcement", "announcement_updated_at",
            "deadline", "practice_required", "simulation_published_at",
            "created_at",
        }
        assert set(table.columns.keys()) == expected_cols

    def test_status_check_constraint(self):
        table = Base.metadata.tables["sessions"]
        checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_sessions_status" in names


class TestUsersModel:
    """T02: users table schema verification."""

    def test_columns_present(self):
        table = Base.metadata.tables["users"]
        expected_cols = {
            "id", "session_id", "username",
            "legal_first_name", "legal_middle_name", "legal_last_name",
            "relationship_to_decedent", "date_of_birth",
            "identity_verified", "id_scan_uri",
            "role", "pw_hash", "email", "phone", "physical_address",
            "address_line1", "address_line2", "address_city",
            "address_region", "address_postal_code", "address_country",
            "invite_token", "invite_token_expires_at", "invite_token_used",
            "consent_accepted", "age_verified", "consent_timestamp",
            "is_submitted", "submitted_at", "practice_completed_at",
            "draft_version", "status", "created_at",
            "invitation_dispatched_at", "waiver_email_failed",
        }
        assert set(table.columns.keys()) == expected_cols

    def test_role_check_constraint(self):
        table = Base.metadata.tables["users"]
        checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_users_role" in names

    def test_status_check_constraint(self):
        table = Base.metadata.tables["users"]
        checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_users_status" in names

    def test_unique_session_username(self):
        table = Base.metadata.tables["users"]
        uniques = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
        names = {c.name for c in uniques}
        assert "uq_users_session_username" in names

    def test_session_id_index(self):
        table = Base.metadata.tables["users"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_users_session_id" in idx_names


class TestAssetsModel:
    """T02: assets table schema verification."""

    def test_columns_present(self):
        table = Base.metadata.tables["assets"]
        expected_cols = {
            "id", "session_id", "title", "description", "category",
            "valuation_min", "valuation_max", "valuation_source",
            "length_in", "width_in", "height_in", "weight_lb",
            "dimension_source", "dimension_confidence", "dimension_notes",
            "sentiment_tag", "description_json",
            "image_uri", "audio_uri", "ocr_status",
            "status", "allocated_to_id", "embedding", "ai_feedback",
        }
        assert set(table.columns.keys()) == expected_cols

    def test_status_check_constraint(self):
        table = Base.metadata.tables["assets"]
        checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_assets_status" in names


    def test_allocated_to_required_check_constraint(self):
        table = Base.metadata.tables["assets"]
        checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_assets_allocated_to_required" in names

    def test_ocr_status_check_constraint(self):
        table = Base.metadata.tables["assets"]
        checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_assets_ocr_status" in names

    def test_session_id_index(self):
        table = Base.metadata.tables["assets"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_assets_session_id" in idx_names

    def test_allocated_to_id_index(self):
        table = Base.metadata.tables["assets"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_assets_allocated_to_id" in idx_names


class TestValuationsModel:
    """T02: valuations table schema verification."""

    def test_columns_present(self):
        table = Base.metadata.tables["valuations"]
        expected_cols = {
            "id", "asset_id", "heir_id", "points",
            "reasoning", "is_reasoning_shared",
        }
        assert set(table.columns.keys()) == expected_cols

    def test_points_check_constraint(self):
        table = Base.metadata.tables["valuations"]
        checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_valuations_points" in names

    def test_unique_asset_heir(self):
        table = Base.metadata.tables["valuations"]
        uniques = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
        names = {c.name for c in uniques}
        assert "uq_asset_heir" in names

    def test_asset_id_index(self):
        table = Base.metadata.tables["valuations"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_valuations_asset_id" in idx_names

    def test_heir_id_index(self):
        table = Base.metadata.tables["valuations"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_valuations_heir_id" in idx_names


class TestAuditLogsModel:
    """T02: audit_logs table schema verification."""

    def test_columns_present(self):
        table = Base.metadata.tables["audit_logs"]
        expected_cols = {
            "id", "session_id", "event_type", "state_snapshot",
            "prev_hash", "sha256_hash", "created_at",
        }
        assert set(table.columns.keys()) == expected_cols

    def test_session_id_index(self):
        table = Base.metadata.tables["audit_logs"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_audit_logs_session_id" in idx_names


class TestSupportRequestsModel:
    """T02: support_requests table schema verification."""

    def test_columns_present(self):
        table = Base.metadata.tables["support_requests"]
        expected_cols = {
            "id", "session_id", "heir_id", "responded_by_id",
            "message", "admin_response", "heir_image_uri", "admin_image_uri",
            "initiator_role", "status",
            "responded_at", "resolved_at", "created_at",
        }
        assert set(table.columns.keys()) == expected_cols

    def test_status_check_constraint(self):
        table = Base.metadata.tables["support_requests"]
        checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_support_requests_status" in names
        assert "ck_support_requests_initiator_role" in names

    def test_session_id_index(self):
        table = Base.metadata.tables["support_requests"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_support_requests_session_id" in idx_names

    def test_heir_id_index(self):
        table = Base.metadata.tables["support_requests"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_support_requests_heir_id" in idx_names

    def test_responded_by_id_index(self):
        table = Base.metadata.tables["support_requests"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_support_requests_responded_by_id" in idx_names


class TestChatMessagesModel:
    """T02: chat_messages table schema verification."""

    def test_columns_present(self):
        table = Base.metadata.tables["chat_messages"]
        expected_cols = {
            "id", "session_id", "heir_id", "sender",
            "message_text", "scrubbed_text", "created_at",
        }
        assert set(table.columns.keys()) == expected_cols

    def test_sender_check_constraint(self):
        table = Base.metadata.tables["chat_messages"]
        checks = [c for c in table.constraints if isinstance(c, CheckConstraint)]
        names = {c.name for c in checks}
        assert "ck_chat_messages_sender" in names

    def test_session_id_index(self):
        table = Base.metadata.tables["chat_messages"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_chat_messages_session_id" in idx_names

    def test_heir_id_index(self):
        table = Base.metadata.tables["chat_messages"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_chat_messages_heir_id" in idx_names


class TestCustomFAQsModel:
    """T02: custom_faqs table schema verification."""

    def test_columns_present(self):
        table = Base.metadata.tables["custom_faqs"]
        expected_cols = {
            "id", "session_id", "question", "answer", "created_at",
        }
        assert set(table.columns.keys()) == expected_cols

    def test_session_id_index(self):
        table = Base.metadata.tables["custom_faqs"]
        idx_names = {idx.name for idx in table.indexes}
        assert "idx_custom_faqs_session_id" in idx_names


class TestRelationships:
    """T02: Verify relationship attributes and cascade deletes."""

    def test_session_relationships(self):
        assert hasattr(Session, "users")
        assert hasattr(Session, "assets")
        assert hasattr(Session, "audit_logs")
        assert hasattr(Session, "support_requests")
        assert hasattr(Session, "chat_messages")
        assert hasattr(Session, "custom_faqs")
        assert hasattr(Session, "categories")

    def test_user_relationships(self):
        assert hasattr(User, "session")
        assert hasattr(User, "valuations")
        assert hasattr(User, "support_requests")
        assert hasattr(User, "chat_messages")

    def test_asset_relationships(self):
        assert hasattr(Asset, "session")
        assert hasattr(Asset, "valuations")
        assert hasattr(Asset, "allocated_to")
        assert hasattr(Asset, "images")

    def test_asset_image_relationships(self):
        assert hasattr(AssetImage, "asset")

    def test_category_relationships(self):
        assert hasattr(Category, "session")

    def test_valuation_relationships(self):
        assert hasattr(Valuation, "asset")
        assert hasattr(Valuation, "heir")

    def test_audit_log_relationships(self):
        assert hasattr(AuditLog, "session")

    def test_support_request_relationships(self):
        assert hasattr(SupportRequest, "session")
        assert hasattr(SupportRequest, "heir")

    def test_chat_message_relationships(self):
        assert hasattr(ChatMessage, "session")
        assert hasattr(ChatMessage, "heir")

    def test_custom_faq_relationships(self):
        assert hasattr(CustomFAQ, "session")

    def test_session_users_cascade_delete_orphan(self):
        """Session.users relationship configured with cascade='all, delete-orphan'."""
        rel = Session.__mapper__.relationships["users"]
        assert "delete-orphan" in rel.cascade

    def test_session_assets_cascade_delete_orphan(self):
        rel = Session.__mapper__.relationships["assets"]
        assert "delete-orphan" in rel.cascade

    def test_session_audit_logs_cascade_delete_orphan(self):
        rel = Session.__mapper__.relationships["audit_logs"]
        assert "delete-orphan" in rel.cascade

    def test_session_support_requests_cascade_delete_orphan(self):
        rel = Session.__mapper__.relationships["support_requests"]
        assert "delete-orphan" in rel.cascade

    def test_session_chat_messages_cascade_delete_orphan(self):
        rel = Session.__mapper__.relationships["chat_messages"]
        assert "delete-orphan" in rel.cascade

    def test_session_custom_faqs_cascade_delete_orphan(self):
        rel = Session.__mapper__.relationships["custom_faqs"]
        assert "delete-orphan" in rel.cascade

    def test_user_valuations_cascade_delete_orphan(self):
        rel = User.__mapper__.relationships["valuations"]
        assert "delete-orphan" in rel.cascade

    def test_user_support_requests_cascade_delete_orphan(self):
        rel = User.__mapper__.relationships["support_requests"]
        assert "delete-orphan" in rel.cascade

    def test_user_chat_messages_cascade_delete_orphan(self):
        rel = User.__mapper__.relationships["chat_messages"]
        assert "delete-orphan" in rel.cascade

    def test_asset_valuations_cascade_delete_orphan(self):
        rel = Asset.__mapper__.relationships["valuations"]
        assert "delete-orphan" in rel.cascade

    def test_asset_images_cascade_delete_orphan(self):
        rel = Asset.__mapper__.relationships["images"]
        assert "delete-orphan" in rel.cascade

    def test_session_categories_cascade_delete_orphan(self):
        rel = Session.__mapper__.relationships["categories"]
        assert "delete-orphan" in rel.cascade
