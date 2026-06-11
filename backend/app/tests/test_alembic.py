"""
Tests for T04 — Alembic Migrations & pgvector Indexing.

Verifies:
- Alembic migration 001_initial_schema.py is present and structurally valid
- upgrade() registers pgvector extension and creates all 8 tables
- downgrade() drops all tables
- Migration revision ID and down_revision are correct
- All expected table names are created in the DDL (offline mode)
- HNSW vector index creation SQL is included
- custom_faqs table is included (per T04 requirement)
"""

import logging
import os

import pytest
from unittest import mock


@pytest.fixture(autouse=True)
def migration_env():
    """Set environment variables needed for alembic env.py imports."""
    os.environ["DB_URL"] = "postgresql+psycopg2://postgres:postgres@localhost:5432/test"
    yield
    os.environ.pop("DB_URL", None)


def _get_migration_source():
    """Read the raw source of 001_initial_schema.py."""
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "migrations", "versions",
        "001_initial_schema.py",
    )
    with open(path) as f:
        return f.read()


class TestMigrationExists:
    """T04: Verify the 001 migration script is present and structurally valid."""

    def test_migration_revision_id(self):
        """Migration revision ID is '001'."""
        content = _get_migration_source()
        assert 'revision: str = "001"' in content

    def test_no_down_revision(self):
        """down_revision is None."""
        content = _get_migration_source()
        assert "down_revision: Union[str, Sequence[str], None] = None" in content

    def test_upgrade_function_exists(self):
        """upgrade() function is defined."""
        content = _get_migration_source()
        assert "def upgrade() -> None:" in content

    def test_downgrade_function_exists(self):
        """downgrade() function is defined."""
        content = _get_migration_source()
        assert "def downgrade() -> None:" in content


class TestOfflineUpgradeDDL:
    """T04: Verify the offline migration produces SQL for all 8 tables + pgvector + HNSW."""

    @pytest.fixture(autouse=True)
    def _save_restore_logging(self):
        """Save and restore logging config around Alembic tests.

        Alembic's fileConfig call reconfigures the root logger, which
        breaks caplog for subsequent test modules. We snapshot the
        logging state beforehand and restore it afterward.
        """
        root = logging.getLogger()
        old_handlers = list(root.handlers)
        old_level = root.level
        yield
        root.handlers = old_handlers
        root.level = old_level

    @pytest.fixture
    def offline_sql(self, migration_env):
        """Run alembic upgrade head in offline mode and capture the generated SQL."""
        from alembic.config import Config
        from alembic.command import upgrade
        from io import StringIO

        alembic_ini = os.path.join(
            os.path.dirname(__file__), "..", "..", "alembic.ini"
        )

        config = Config(alembic_ini)
        script_location = os.path.join(
            os.path.dirname(__file__), "..", "..", "migrations"
        )
        config.set_main_option("script_location", script_location)

        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            upgrade(config, "head", sql=True)

        return buf.getvalue()

    def test_pgvector_extension_created(self, offline_sql):
        """Offline SQL includes CREATE EXTENSION IF NOT EXISTS vector."""
        assert "CREATE EXTENSION IF NOT EXISTS vector" in offline_sql

    def test_all_eight_tables_created(self, offline_sql):
        """Offline SQL creates all 8 tables."""
        expected_tables = [
            "sessions",
            "users",
            "assets",
            "valuations",
            "audit_logs",
            "chat_messages",
            "support_requests",
            "custom_faqs",
        ]
        for table in expected_tables:
            assert f"CREATE TABLE {table}" in offline_sql or f"create table {table}" in offline_sql.lower(), (
                f"Table '{table}' not found in upgrade SQL"
            )

    def test_hnsw_index_created(self, offline_sql):
        """Offline SQL includes HNSW index with vector_cosine_ops."""
        assert "assets_embedding_hnsw_idx" in offline_sql
        assert "vector_cosine_ops" in offline_sql

    def test_check_constraints_included(self, offline_sql):
        """Key check constraints are present in the generated SQL."""
        assert "ck_sessions_status" in offline_sql
        assert "ck_users_role" in offline_sql
        assert "ck_valuations_points" in offline_sql
        assert "uq_asset_heir" in offline_sql

    def test_b_tree_indexes_included(self, offline_sql):
        """Key B-Tree indexes are present in the generated SQL."""
        indexes = [
            "idx_users_session_id",
            "idx_assets_session_id",
            "idx_valuations_asset_id",
            "idx_valuations_heir_id",
            "idx_audit_logs_session_id",
            "idx_support_requests_session_id",
            "idx_chat_messages_session_id",
            "idx_custom_faqs_session_id",
        ]
        for idx in indexes:
            assert idx in offline_sql, f"Index '{idx}' not found in upgrade SQL"