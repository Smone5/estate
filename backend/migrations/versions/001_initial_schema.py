"""Initial schema — pgvector extension, all 8 tables, constraints, indexes, and HNSW embedding index.

Revision ID: 001
Revises:
Create Date: 2026-06-10 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables, constraints, and indexes."""

    # -- pgvector extension -------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # -- sessions -----------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="SETUP"),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deadlocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("announcement", sa.Text(), nullable=True),
        sa.Column("announcement_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc'::text, now())"),
        ),
    )
    op.create_check_constraint(
        "ck_sessions_status",
        "sessions",
        "status IN ('SETUP', 'ACTIVE', 'LOCKED', 'FINALIZED')",
    )

    # -- users --------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("legal_first_name", sa.String(50), nullable=True),
        sa.Column("legal_middle_name", sa.String(50), nullable=True),
        sa.Column("legal_last_name", sa.String(100), nullable=True),
        sa.Column("relationship_to_decedent", sa.String(50), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("identity_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id_scan_uri", sa.String(255), nullable=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("pw_hash", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("physical_address", sa.Text(), nullable=True),
        sa.Column(
            "invite_token", postgresql.UUID(as_uuid=True), nullable=True, unique=True
        ),
        sa.Column("invite_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invite_token_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consent_accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("age_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consent_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_submitted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("draft_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc'::text, now())"),
        ),
        sa.Column("invitation_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("waiver_email_failed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('ADMIN', 'HEIR')",
    )
    op.create_check_constraint(
        "ck_users_status",
        "users",
        "status IN ('PENDING', 'PROFILE_HOLD', 'ACTIVE', 'SUBMITTED', 'ABSTAINED', 'EXPIRED_NON_PARTICIPATING')",
    )
    op.create_unique_constraint(
        "uq_users_session_username", "users", ["session_id", "username"]
    )
    op.create_index("idx_users_session_id", "users", ["session_id"])

    # -- assets -------------------------------------------------------------
    op.create_table(
        "assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(150), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(20), nullable=True),
        sa.Column("valuation_min", sa.Float(), nullable=True),
        sa.Column("valuation_max", sa.Float(), nullable=True),
        sa.Column("valuation_source", sa.String(150), nullable=True),
        sa.Column("sentiment_tag", sa.String(255), nullable=True),
        sa.Column("description_json", sa.Text(), nullable=True),
        sa.Column("image_uri", sa.String(255), nullable=False),
        sa.Column("audio_uri", sa.String(255), nullable=True),
        sa.Column("ocr_status", sa.String(15), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="STAGED"),
        sa.Column(
            "allocated_to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("embedding", Vector(768), nullable=True),
    )
    op.create_check_constraint(
        "ck_assets_category",
        "assets",
        "category IN ('Jewelry', 'Furniture', 'Art', 'Other') OR category IS NULL",
    )
    op.create_check_constraint(
        "ck_assets_status",
        "assets",
        "status IN ('STAGED', 'LIVE', 'PRE_ALLOCATED', 'DISTRIBUTED')",
    )
    op.create_check_constraint(
        "ck_assets_ocr_status",
        "assets",
        "ocr_status IN ('PROCESSING', 'COMPLETED', 'FAILED') OR ocr_status IS NULL",
    )
    op.create_check_constraint(
        "ck_assets_allocated_to_required",
        "assets",
        "(status NOT IN ('PRE_ALLOCATED', 'DISTRIBUTED')) OR (allocated_to_id IS NOT NULL)",
    )
    op.create_index("idx_assets_session_id", "assets", ["session_id"])
    op.create_index("idx_assets_allocated_to_id", "assets", ["allocated_to_id"])

    # -- valuations ---------------------------------------------------------
    op.create_table(
        "valuations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "heir_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("is_reasoning_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_valuations_points",
        "valuations",
        "points >= 0 AND points <= 1000",
    )
    op.create_unique_constraint(
        "uq_asset_heir", "valuations", ["asset_id", "heir_id"]
    )
    op.create_index("idx_valuations_asset_id", "valuations", ["asset_id"])
    op.create_index("idx_valuations_heir_id", "valuations", ["heir_id"])

    # -- audit_logs ---------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("state_snapshot", sa.Text(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc'::text, now())"),
        ),
    )
    op.create_index("idx_audit_logs_session_id", "audit_logs", ["session_id"])

    # -- support_requests ---------------------------------------------------
    op.create_table(
        "support_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "heir_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc'::text, now())"),
        ),
    )
    op.create_check_constraint(
        "ck_support_requests_status",
        "support_requests",
        "status IN ('OPEN', 'RESOLVED')",
    )
    op.create_index("idx_support_requests_session_id", "support_requests", ["session_id"])
    op.create_index("idx_support_requests_heir_id", "support_requests", ["heir_id"])

    # -- chat_messages ------------------------------------------------------
    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "heir_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender", sa.String(10), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("scrubbed_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc'::text, now())"),
        ),
    )
    op.create_check_constraint(
        "ck_chat_messages_sender",
        "chat_messages",
        "sender IN ('heir', 'agent')",
    )
    op.create_index("idx_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("idx_chat_messages_heir_id", "chat_messages", ["heir_id"])

    # -- custom_faqs --------------------------------------------------------
    op.create_table(
        "custom_faqs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc'::text, now())"),
        ),
    )
    op.create_index("idx_custom_faqs_session_id", "custom_faqs", ["session_id"])

    # -- HNSW vector index (cosine distance) --------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS assets_embedding_hnsw_idx "
        "ON assets USING hnsw (embedding vector_cosine_ops);"
    )


def downgrade() -> None:
    """Drop all tables and the pgvector extension."""
    op.execute("DROP INDEX IF EXISTS assets_embedding_hnsw_idx;")
    op.drop_table("custom_faqs")
    op.drop_table("chat_messages")
    op.drop_table("support_requests")
    op.drop_table("audit_logs")
    op.drop_table("valuations")
    op.drop_table("assets")
    op.drop_table("users")
    op.drop_table("sessions")
    op.execute("DROP EXTENSION IF EXISTS vector;")