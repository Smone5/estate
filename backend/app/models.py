"""
SQLAlchemy ORM models for The Estate Steward.

Defines all 8 tables per DB Spec §2:
  sessions, users, assets, valuations, audit_logs,
  chat_messages, support_requests, custom_faqs

Enforces native CheckConstraints, UniqueConstraints, B-Tree indexes,
foreign-key cascades, and relationship back-references.
"""

import uuid as _uuid
from sqlalchemy import (
    Column, String, Integer, Boolean, Date, DateTime,
    Text, Float, BigInteger, ForeignKey,
    UniqueConstraint, CheckConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import text as sa_text
from pgvector.sqlalchemy import Vector

from .database import Base
from .encryption import EncryptedJSON


# ---------------------------------------------------------------------------
# 1. Session
# ---------------------------------------------------------------------------

class Session(Base):
    __tablename__ = "sessions"

    id = Column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )
    title = Column(String(100), nullable=False)
    status = Column(
        String(20), nullable=False, default="SETUP",
    )
    is_paused = Column(Boolean, nullable=False, default=False)
    paused_at = Column(DateTime(timezone=True), nullable=True)
    is_deadlocked = Column(Boolean, nullable=False, default=False)
    announcement = Column(Text, nullable=True)
    announcement_updated_at = Column(DateTime(timezone=True), nullable=True)
    deadline = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=sa_text("timezone('utc'::text, now())"),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('SETUP', 'ACTIVE', 'LOCKED', 'FINALIZED')",
            name="ck_sessions_status",
        ),
    )

    # Relationships
    users = relationship("User", back_populates="session", cascade="all, delete-orphan")
    assets = relationship("Asset", back_populates="session", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="session", cascade="all, delete-orphan")
    support_requests = relationship("SupportRequest", back_populates="session", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    custom_faqs = relationship("CustomFAQ", back_populates="session", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# 2. User
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    username = Column(String(100), nullable=False)
    legal_first_name = Column(String(50), nullable=True)
    legal_middle_name = Column(String(50), nullable=True)
    legal_last_name = Column(String(100), nullable=True)
    relationship_to_decedent = Column(String(50), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    identity_verified = Column(Boolean, nullable=False, default=False)
    id_scan_uri = Column(String(255), nullable=True)
    role = Column(String(10), nullable=False)
    pw_hash = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    physical_address = Column(Text, nullable=True)
    invite_token = Column(UUID(as_uuid=True), nullable=True, unique=True)
    invite_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    invite_token_used = Column(Boolean, nullable=False, default=False)
    consent_accepted = Column(Boolean, nullable=False, default=False)
    age_verified = Column(Boolean, nullable=False, default=False)
    consent_timestamp = Column(DateTime(timezone=True), nullable=True)
    is_submitted = Column(Boolean, nullable=False, default=False)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    draft_version = Column(Integer, nullable=False, default=0)
    status = Column(
        String(30), nullable=False, default="PENDING",
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=sa_text("timezone('utc'::text, now())"),
    )
    invitation_dispatched_at = Column(DateTime(timezone=True), nullable=True)
    waiver_email_failed = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint(
            "role IN ('ADMIN', 'HEIR')",
            name="ck_users_role",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PROFILE_HOLD', 'ACTIVE', 'SUBMITTED', "
            "'ABSTAINED', 'EXPIRED_NON_PARTICIPATING')",
            name="ck_users_status",
        ),
        UniqueConstraint("session_id", "username", name="uq_users_session_username"),
        Index("idx_users_session_id", "session_id"),
    )

    # Relationships
    session = relationship("Session", back_populates="users")
    valuations = relationship("Valuation", back_populates="heir", cascade="all, delete-orphan")
    support_requests = relationship("SupportRequest", back_populates="heir", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="heir", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# 3. Asset
# ---------------------------------------------------------------------------

class Asset(Base):
    __tablename__ = "assets"

    id = Column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(150), nullable=True)
    description = Column(Text, nullable=True)
    category = Column(String(20), nullable=True)
    valuation_min = Column(Float, nullable=True)
    valuation_max = Column(Float, nullable=True)
    valuation_source = Column(String(150), nullable=True)
    sentiment_tag = Column(String(255), nullable=True)
    description_json = Column(Text, nullable=True)  # JSONB mapped via Text for portability
    image_uri = Column(String(255), nullable=False)
    audio_uri = Column(String(255), nullable=True)
    ocr_status = Column(String(15), nullable=True)
    status = Column(
        String(20), nullable=False, default="STAGED",
    )
    allocated_to_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    embedding = Column(Vector(768), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "category IN ('Jewelry', 'Furniture', 'Art', 'Other') OR category IS NULL",
            name="ck_assets_category",
        ),
        CheckConstraint(
            "status IN ('STAGED', 'LIVE', 'PRE_ALLOCATED', 'DISTRIBUTED')",
            name="ck_assets_status",
        ),
        CheckConstraint(
            "ocr_status IN ('PROCESSING', 'COMPLETED', 'FAILED') OR ocr_status IS NULL",
            name="ck_assets_ocr_status",
        ),
        CheckConstraint(
            "(status NOT IN ('PRE_ALLOCATED', 'DISTRIBUTED')) OR (allocated_to_id IS NOT NULL)",
            name="ck_assets_allocated_to_required",
        ),
        Index("idx_assets_session_id", "session_id"),
        Index("idx_assets_allocated_to_id", "allocated_to_id"),
    )

    # Relationships
    session = relationship("Session", back_populates="assets")
    valuations = relationship("Valuation", back_populates="asset", cascade="all, delete-orphan")
    allocated_to = relationship("User", foreign_keys=[allocated_to_id])


# ---------------------------------------------------------------------------
# 4. Valuation
# ---------------------------------------------------------------------------

class Valuation(Base):
    __tablename__ = "valuations"

    id = Column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )
    asset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    heir_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    points = Column(Integer, nullable=False)
    reasoning = Column(EncryptedJSON, nullable=True)
    is_reasoning_shared = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint(
            "points >= 0 AND points <= 1000",
            name="ck_valuations_points",
        ),
        UniqueConstraint("asset_id", "heir_id", name="uq_asset_heir"),
        Index("idx_valuations_asset_id", "asset_id"),
        Index("idx_valuations_heir_id", "heir_id"),
    )

    # Relationships
    asset = relationship("Asset", back_populates="valuations")
    heir = relationship("User", back_populates="valuations")


# ---------------------------------------------------------------------------
# 5. AuditLog
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String(50), nullable=False)
    state_snapshot = Column(EncryptedJSON, nullable=False)
    prev_hash = Column(String(64), nullable=False)
    sha256_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=sa_text("timezone('utc'::text, now())"),
    )

    __table_args__ = (
        Index("idx_audit_logs_session_id", "session_id"),
    )

    # Relationships
    session = relationship("Session", back_populates="audit_logs")


# ---------------------------------------------------------------------------
# 6. SupportRequest
# ---------------------------------------------------------------------------

class SupportRequest(Base):
    __tablename__ = "support_requests"

    id = Column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    heir_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    message = Column(Text, nullable=False)
    status = Column(
        String(10), nullable=False, default="OPEN",
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=sa_text("timezone('utc'::text, now())"),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'RESOLVED')",
            name="ck_support_requests_status",
        ),
        Index("idx_support_requests_session_id", "session_id"),
        Index("idx_support_requests_heir_id", "heir_id"),
    )

    # Relationships
    session = relationship("Session", back_populates="support_requests")
    heir = relationship("User", back_populates="support_requests")


# ---------------------------------------------------------------------------
# 7. ChatMessage
# ---------------------------------------------------------------------------

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    heir_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender = Column(String(10), nullable=False)
    message_text = Column(EncryptedJSON, nullable=False)
    scrubbed_text = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=sa_text("timezone('utc'::text, now())"),
    )

    __table_args__ = (
        CheckConstraint(
            "sender IN ('heir', 'agent')",
            name="ck_chat_messages_sender",
        ),
        Index("idx_chat_messages_session_id", "session_id"),
        Index("idx_chat_messages_heir_id", "heir_id"),
    )

    # Relationships
    session = relationship("Session", back_populates="chat_messages")
    heir = relationship("User", back_populates="chat_messages")


# ---------------------------------------------------------------------------
# 8. CustomFAQ
# ---------------------------------------------------------------------------

class CustomFAQ(Base):
    __tablename__ = "custom_faqs"

    id = Column(
        UUID(as_uuid=True), primary_key=True,
        server_default=sa_text("gen_random_uuid()"),
    )
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        server_default=sa_text("timezone('utc'::text, now())"),
    )

    __table_args__ = (
        Index("idx_custom_faqs_session_id", "session_id"),
    )

    # Relationships
    session = relationship("Session", back_populates="custom_faqs")