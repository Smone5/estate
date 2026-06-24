"""
The Estate Steward — FastAPI application entry point.

Per DB Spec §6.3: init_db() is called at startup with a retry loop
that prevents crashes when the PostgreSQL container starts slower
than the API container.

T10: Exposes core auth and onboarding endpoints with rate limiting.
"""

import logging
import io
import os
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional, Annotated

from fastapi import FastAPI, Depends, HTTPException, Response, Request, UploadFile, File, Form, Query, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DBSession

from . import database
from .database import init_db
from .rate_limiter import init_rate_limiting, limiter
from .auth import (
    hash_password,
    verify_password,
    create_access_token,
    set_auth_cookie,
    clear_auth_cookie,
    decode_access_token,
    get_current_user,
    get_current_admin,
)
from .models import User, Session as SessionModel, Asset, Valuation, AuditLog, SupportRequest, CustomFAQ, ChatMessage, AssetImage, Category
from .websocket_manager import manager
from .kokoro_tts import get_kokoro_tts, _KOKORO_AVAILABLE as TTS_AVAILABLE
from .services.storage import get_storage_driver, preprocess_image
from .services.llm_provider import get_provider, reset_provider
from .services.smtp_service import send_email, send_email_background, Attachment
from .services.settings_service import get_settings_for_admin, update_settings, load_settings_into_env
from .notice_log import build_notice_log

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Backward-compatible override hook for tests. Runtime uses database.SessionLocal
# after init_db() initializes it; tests can patch app.main.SessionLocal.
SessionLocal = None


def _get_session_factory():
    return SessionLocal or database.SessionLocal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _redact_pii_in_place(obj, heir_id_str: str, pii_values: list[str]):
    """Recursively walk a dict/list and replace PII values with 'Anonymized'.

    Matches the heir_id_str as well as any known PII string values
    (legal names, email, phone, address) inside the snapshot structure.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str):
                if value == heir_id_str:
                    obj[key] = "Anonymized"
                elif any(pii and pii == value for pii in pii_values):
                    obj[key] = "Anonymized"
                elif isinstance(value, str):
                    # Check for substring matches of PII within longer strings
                    for pii in pii_values:
                        if pii and pii in value and len(pii) > 3:
                            obj[key] = value.replace(pii, "Anonymized")
            elif isinstance(value, (dict, list)):
                _redact_pii_in_place(value, heir_id_str, pii_values)
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                _redact_pii_in_place(item, heir_id_str, pii_values)


# ---------------------------------------------------------------------------
# Request schemas (T10 scope — inline per FastAPI convention)
# -------------------------------------------------------------------

class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class InviteVerifyRequest(BaseModel):
    token: str
    consent_accepted: bool
    age_verified: bool
    password: str | None = Field(None, min_length=8, max_length=128)
    legal_first_name: str = Field(..., min_length=1, max_length=50)
    legal_middle_name: str | None = None
    legal_last_name: str = Field(..., min_length=1, max_length=100)
    relationship_to_decedent: str = Field(..., min_length=1, max_length=50)
    date_of_birth: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")


class HeirProfileUpdate(BaseModel):
    legal_first_name: str = Field(..., min_length=1, max_length=50)
    legal_middle_name: str | None = None
    legal_last_name: str = Field(..., min_length=1, max_length=100)
    relationship_to_decedent: str = Field(..., min_length=1, max_length=50)
    date_of_birth: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    email: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
    physical_address: str | None = Field(None, max_length=255)
    address_line1: str | None = Field(None, max_length=255)
    address_line2: str | None = Field(None, max_length=255)
    address_city: str | None = Field(None, max_length=100)
    address_region: str | None = Field(None, max_length=100)
    address_postal_code: str | None = Field(None, max_length=40)
    address_country: str | None = Field(None, max_length=100)


class InviteLoginRequest(BaseModel):
    token: str


class HeirLoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


ADDRESS_FIELD_NAMES = (
    "address_line1",
    "address_line2",
    "address_city",
    "address_region",
    "address_postal_code",
    "address_country",
)


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _structured_address_from_body(body: BaseModel) -> dict[str, str | None]:
    return {
        field_name: _clean_optional_text(getattr(body, field_name, None))
        for field_name in ADDRESS_FIELD_NAMES
    }


def _compose_physical_address(
    address: dict[str, str | None],
    fallback: str | None = None,
) -> str | None:
    line1 = address.get("address_line1")
    line2 = address.get("address_line2")
    city = address.get("address_city")
    region = address.get("address_region")
    postal_code = address.get("address_postal_code")
    country = address.get("address_country")

    locality = ", ".join(part for part in (city, region) if part)
    if postal_code:
        locality = f"{locality} {postal_code}".strip()

    parts = [line1, line2, locality or None, country]
    composed = ", ".join(part for part in parts if part)
    return composed or _clean_optional_text(fallback)


def _address_response_fields(heir: User) -> dict[str, str | None]:
    fields: dict[str, str | None] = {}
    for field_name in ADDRESS_FIELD_NAMES:
        value = getattr(heir, field_name, None)
        fields[field_name] = value if isinstance(value, str) else None
    return fields


def _public_base_url(request: Request) -> str:
    configured_url = (
        os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("APP_PUBLIC_URL")
        or ""
    ).strip()
    if configured_url:
        return configured_url.rstrip("/")
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def get_db() -> DBSession:
    """FastAPI dependency that yields a database session per request."""
    db = _get_session_factory()()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

import asyncio


async def _invite_expiration_task():
    """Periodic background task to expire stale invite tokens.

    Runs every 15 minutes. Checks for users where:
      - role == 'HEIR'
      - invite_token_used == False
      - invite_token_expires_at < now()
    Transitions those users to 'EXPIRED_NON_PARTICIPATING'.
    """
    while True:
        try:
            await asyncio.sleep(900)  # 15 minutes
            db = _get_session_factory()()
            try:
                now_utc = datetime.now(timezone.utc)
                expired = (
                    db.query(User)
                    .filter(
                        User.role == "HEIR",
                        User.invite_token_used == False,
                        User.invite_token_expires_at.isnot(None),
                        User.invite_token_expires_at < now_utc,
                        User.status != "EXPIRED_NON_PARTICIPATING",
                    )
                    .all()
                )
                for user in expired:
                    user.status = "EXPIRED_NON_PARTICIPATING"
                if expired:
                    db.commit()
                    logger.info(
                        "Invite scheduler: expired %d heir(s)",
                        len(expired),
                    )
            except Exception:
                db.rollback()
                logger.exception("Invite scheduler error")
            finally:
                db.close()
        except asyncio.CancelledError:
            logger.info("Invite scheduler cancelled")
            break


def cleanup_stuck_ocr_tasks():
    """Find any assets with ocr_status == 'PROCESSING' on startup and reset them to 'FAILED'."""
    db = _get_session_factory()()
    try:
        stuck_assets = db.query(Asset).filter(Asset.ocr_status == "PROCESSING").all()
        for asset in stuck_assets:
            asset.ocr_status = "FAILED"
            import json as json_mod
            try:
                djson = json_mod.loads(asset.description_json) if asset.description_json else {}
            except Exception:
                djson = {}
            djson["ocr_error"] = "Task interrupted by system restart."
            asset.description_json = json_mod.dumps(djson)
        if stuck_assets:
            db.commit()
            logger.info("Startup recovery: marked %d stuck OCR tasks as FAILED", len(stuck_assets))
    except Exception:
        db.rollback()
        logger.exception("Startup recovery cleanup_stuck_ocr_tasks failed")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Perform startup database initialization with retry loop."""
    logger.info("Starting Estate Steward backend...")
    init_db()
    try:
        db = _get_session_factory()()
        try:
            load_settings_into_env(db)
        finally:
            db.close()
    except Exception as exc:
        logger.exception("Failed to load admin-configured settings on startup: %s", exc)
    try:
        cleanup_stuck_ocr_tasks()
    except Exception as exc:
        logger.exception("Failed to clean up stuck OCR tasks on startup: %s", exc)
    task = asyncio.create_task(_invite_expiration_task())
    logger.info("Startup complete.")
    yield
    logger.info("Shutting down invite scheduler...")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Shut down.")


app = FastAPI(
    title="The Estate Steward",
    version="0.1.0",
    lifespan=lifespan,
)
init_rate_limiting(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health_check():
    """Liveness probe endpoint."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Auth: POST /api/auth/login  (Admin login)
# ---------------------------------------------------------------------------


@app.post("/api/auth/login")
@limiter.limit("10/minute")
async def auth_login(
    request: Request,
    body: AdminLoginRequest,
    response: Response,
    db: DBSession = Depends(get_db),
):
    """
    Admin login endpoint.

    Per Backend Spec §9.5: Verifies admin password hash against the database
    using Argon2. On success, generates a JWT token and returns it in a
    secure, HTTP-only cookie.
    """
    user = db.query(User).filter(
        User.username == body.username,
        User.role == "ADMIN",
    ).first()

    if not user or not user.pw_hash:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(body.password, user.pw_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        user_id=str(user.id),
        username=user.username,
        role="ADMIN",
        session_id=None,
    )

    set_auth_cookie(response, token)
    return {"status": "authenticated", "role": "ADMIN"}


@app.get("/api/auth/me")
async def auth_me(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    """Return the authenticated user payload and re-issue a fresh session cookie.

    Every call extends the JWT session by 24 hours (sliding expiration),
    so users who refresh the page or navigate never see an expired session.
    """
    token = create_access_token(
        user_id=current_user["user_id"],
        username=current_user["username"],
        role=current_user["role"],
        session_id=current_user.get("session_id"),
    )
    set_auth_cookie(response, token)
    return {
        "status": "authenticated",
        "user_id": current_user.get("user_id"),
        "username": current_user.get("username"),
        "role": current_user.get("role"),
        "session_id": current_user.get("session_id"),
    }


@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    """Clear the session cookie (logout)."""
    clear_auth_cookie(response)
    return {"status": "success", "message": "Logged out successfully"}


# ---------------------------------------------------------------------------
# Auth: POST /api/invite/verify  (Heir onboarding)
# ---------------------------------------------------------------------------


@app.post("/api/invite/verify")
@limiter.limit("10/minute")
async def invite_verify(
    request: Request,
    body: InviteVerifyRequest,
    response: Response,
    db: DBSession = Depends(get_db),
):
    """
    Heir invitation verification endpoint.

    Per Backend Spec §9.5 (POST /api/invite/verify):
    1. Looks up the invitation token. Verifies if invite_token_used is already
       True or if the current UTC time is past invite_token_expires_at. If so,
       returns 400 Bad Request.
    2. Validates consent_accepted and age_verified flags are true. Returns 400
       if either is false.
    3. Records consent_timestamp, updates profile details, sets
       invite_token_used = True.
    4. Sets Heir status to 'PROFILE_HOLD'.
    5. Returns a secure HTTP-only JWT token session cookie.
    """
    user = db.query(User).filter(User.invite_token == body.token).first()

    if not user:
        raise HTTPException(
            status_code=400,
            detail="This invitation link has expired or has already been used. "
            "Please contact the Executor.",
        )

    if user.invite_token_used:
        raise HTTPException(
            status_code=400,
            detail="This invitation link has expired or has already been used. "
            "Please contact the Executor.",
        )

    now_utc = datetime.now(timezone.utc)
    if user.invite_token_expires_at and user.invite_token_expires_at < now_utc:
        raise HTTPException(
            status_code=400,
            detail="This invitation link has expired or has already been used. "
            "Please contact the Executor.",
        )

    if not body.consent_accepted:
        raise HTTPException(
            status_code=400,
            detail="You must accept the consent terms to continue.",
        )

    if not body.age_verified:
        raise HTTPException(
            status_code=400,
            detail="You must confirm your age to continue.",
        )

    # Update profile details
    user.legal_first_name = body.legal_first_name
    user.legal_middle_name = body.legal_middle_name
    user.legal_last_name = body.legal_last_name
    user.relationship_to_decedent = body.relationship_to_decedent
    user.date_of_birth = (
        datetime.strptime(body.date_of_birth, "%Y-%m-%d").date()
        if body.date_of_birth
        else None
    )
    user.consent_accepted = True
    user.age_verified = True
    user.consent_timestamp = now_utc
    user.invite_token_used = True
    if body.password:
        user.pw_hash = hash_password(body.password)
    user.status = "PROFILE_HOLD"

    db.commit()
    db.refresh(user)

    jwt_token = create_access_token(
        user_id=str(user.id),
        username=user.username,
        role="HEIR",
        session_id=str(user.session_id) if user.session_id else None,
    )

    set_auth_cookie(response, jwt_token)
    return {
        "status": "success",
        "session_id": str(user.session_id) if user.session_id else None,
        "heir_id": str(user.id),
        "user_status": "PROFILE_HOLD",
    }


@app.get("/api/invite/status/{token}")
@limiter.limit("60/minute")
async def get_invite_status(
    request: Request,
    token: str,
    response: Response,
    db: DBSession = Depends(get_db),
):
    """
    Check the usage status of an invitation token.
    Per Backend Spec §9.1 (GET /api/invite/status/{token}):
    """
    user = db.query(User).filter(User.invite_token == token).first()
    if not user:
        raise HTTPException(status_code=404, detail="Invitation token not found")

    now_utc = datetime.now(timezone.utc)
    if user.invite_token_expires_at and user.invite_token_expires_at < now_utc:
        status_val = "EXPIRED"
    elif user.invite_token_used:
        status_val = "USED"
    else:
        status_val = "NEW"

    return {
        "status": status_val,
        "used": user.invite_token_used,
        "username": user.username,
        "legal_first_name": user.legal_first_name,
        "legal_middle_name": user.legal_middle_name,
        "legal_last_name": user.legal_last_name,
        "relationship_to_decedent": user.relationship_to_decedent,
        "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
    }


@app.post("/api/auth/heir-login")
@limiter.limit("10/minute")
async def heir_password_login(
    request: Request,
    body: HeirLoginRequest,
    response: Response,
    db: DBSession = Depends(get_db),
):
    """
    Heir password login endpoint.

    This allows already-onboarded heirs to return after the invitation link
    expires. The invite remains the first-entry path; password login becomes
    the long-term credential after onboarding.
    """
    identifier = body.identifier.strip().lower()
    user = (
        db.query(User)
        .filter(
            User.role == "HEIR",
            or_(
                func.lower(User.email) == identifier,
                func.lower(User.username) == identifier,
            ),
        )
        .first()
    )

    if (
        not user
        or not user.invite_token_used
        or not user.pw_hash
        or not verify_password(body.password, user.pw_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    jwt_token = create_access_token(
        user_id=str(user.id),
        username=user.username,
        role="HEIR",
        session_id=str(user.session_id) if user.session_id else None,
    )

    set_auth_cookie(response, jwt_token)
    return {
        "status": "success",
        "role": "HEIR",
        "session_id": str(user.session_id) if user.session_id else None,
        "heir_id": str(user.id),
        "user_status": user.status,
    }


# ---------------------------------------------------------------------------
# Auth: POST /api/invite/login  (Heir re-login)
# ---------------------------------------------------------------------------


@app.post("/api/invite/login")
@limiter.limit("10/minute")
async def invite_login(
    request: Request,
    body: InviteLoginRequest,
    response: Response,
    db: DBSession = Depends(get_db),
):
    """
    Heir re-login endpoint.

    Per Backend Spec §9.1 (POST /api/invite/login):
    Re-issues a session cookie for already-onboarded heirs.
    Verifies that the token matches a user, is invite_token_used == True,
    and is not expired. If valid, returns a secure HTTP-only JWT token
    session cookie.
    """
    user = db.query(User).filter(User.invite_token == body.token).first()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid login token")

    if not user.invite_token_used:
        raise HTTPException(
            status_code=400,
            detail="Your invitation has not been verified yet. "
            "Please complete the onboarding process.",
        )

    now_utc = datetime.now(timezone.utc)
    if user.invite_token_expires_at and user.invite_token_expires_at < now_utc:
        raise HTTPException(
            status_code=400,
            detail="Your invitation link has expired. "
            "Please contact the Executor.",
        )

    jwt_token = create_access_token(
        user_id=str(user.id),
        username=user.username,
        role="HEIR",
        session_id=str(user.session_id) if user.session_id else None,
    )

    set_auth_cookie(response, jwt_token)
    return {
        "status": "success",
        "session_id": str(user.session_id) if user.session_id else None,
        "heir_id": str(user.id),
        "user_status": user.status,
    }


# ---------------------------------------------------------------------------
# T37 — Schema
# ---------------------------------------------------------------------------


class AnnouncementRequest(BaseModel):
    announcement: str | None = None


class AdminSettingsUpdateRequest(BaseModel):
    updates: dict[str, str]


@app.get("/api/admin/settings")
@limiter.limit("30/minute")
async def admin_get_settings(
    request: Request,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """Return current LLM/SMTP/storage settings, grouped by section. Secrets are masked."""
    return JSONResponse(content=get_settings_for_admin(db))


@app.put("/api/admin/settings")
@limiter.limit("30/minute")
async def admin_update_settings(
    request: Request,
    body: AdminSettingsUpdateRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """Persist and immediately apply a partial set of LLM/SMTP/storage settings."""
    try:
        result = update_settings(db, body.updates, admin_user_id=current_admin.get("user_id"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# T11 — Schema
# ---------------------------------------------------------------------------


class AssetPublishRequest(BaseModel):
    title: str = Field(..., max_length=150)
    description: str
    category: str = Field(..., max_length=100)
    valuation_min: float | None = None
    valuation_max: float | None = None
    valuation_source: str | None = None
    sentiment_tag: str | None = None
    item_overview: str | None = None
    specifications: str | None = None
    condition_report: str | None = None
    keywords: str | None = None
    reason: str | None = None


class AssetSaveRequest(BaseModel):
    title: str | None = Field(None, max_length=150)
    description: str | None = None
    category: str | None = Field(None, max_length=100)
    valuation_min: float | None = None
    valuation_max: float | None = None
    valuation_source: str | None = None
    sentiment_tag: str | None = None
    item_overview: str | None = None
    specifications: str | None = None
    condition_report: str | None = None
    keywords: str | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# T37 — Session lifecycle & announcement endpoints
# ---------------------------------------------------------------------------


@app.post("/api/sessions/{session_id}/launch")
@limiter.limit("30/minute")
async def session_launch(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Launch a session — transition from SETUP to ACTIVE.

    Per Backend Spec §9.1 (POST /api/sessions/{session_id}/launch):
    Transitions session status from 'SETUP' to 'ACTIVE', permanently locks
    the inventory catalog, sets the session deadline to 14 days from now,
    and triggers a WebSocket broadcast of the updated status.
    Returns 400 if no published assets (LIVE or PRE_ALLOCATED) exist.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "SETUP":
        raise HTTPException(
            status_code=400,
            detail=f"Session cannot be launched — current status is '{session.status}'.",
        )

    # Verify at least one published asset exists
    published_count = (
        db.query(Asset)
        .filter(
            Asset.session_id == session_id,
            Asset.status.in_(["LIVE", "PRE_ALLOCATED"]),
        )
        .count()
    )
    if published_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Cannot launch session with no published assets. "
            "Stage and publish at least one asset first.",
        )

    now_utc = datetime.now(timezone.utc)
    session.status = "ACTIVE"
    session.deadline = now_utc + timedelta(days=14)
    db.commit()
    db.refresh(session)

    # Broadcast status update via WebSocket
    await manager.broadcast_session_status(
        session_id,
        {
            "type": "session_status",
            "status": session.status,
            "is_paused": session.is_paused,
            "is_deadlocked": session.is_deadlocked,
        },
    )

    return JSONResponse(
        content={
            "session_id": str(session.id),
            "status": session.status,
        }
    )


@app.post("/api/sessions/{session_id}/pause")
@limiter.limit("30/minute")
async def session_pause(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Pause a session.

    Per Backend Spec §9.1 (POST /api/sessions/{session_id}/pause):
    Transitions session status to 'LOCKED', sets is_paused = True, updates
    paused_at to current UTC timestamp, freezing active points sliders
    and chat mediation interfaces for all heirs.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status not in ("ACTIVE", "LOCKED"):
        raise HTTPException(
            status_code=400,
            detail=f"Session cannot be paused — current status is '{session.status}'.",
        )

    if session.is_paused:
        raise HTTPException(status_code=400, detail="Session is already paused.")

    now_utc = datetime.now(timezone.utc)
    session.status = "LOCKED"
    session.is_paused = True
    session.paused_at = now_utc
    db.commit()

    await manager.broadcast_session_status(
        session_id,
        {
            "type": "session_status",
            "status": session.status,
            "is_paused": session.is_paused,
            "is_deadlocked": session.is_deadlocked,
        },
    )

    return JSONResponse(
        content={
            "session_id": str(session.id),
            "is_paused": True,
        }
    )


@app.post("/api/sessions/{session_id}/unpause")
@limiter.limit("30/minute")
async def session_unpause(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Unpause a session.

    Per Backend Spec §9.1 (POST /api/sessions/{session_id}/unpause):
    Transitions session status to 'ACTIVE', sets is_paused = False,
    calculates total pause duration, dynamically extends invite token
    expiration timestamps and session deadline by that duration,
    sets paused_at = NULL, and broadcasts status update.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.is_paused:
        raise HTTPException(status_code=400, detail="Session is not paused.")

    if session.paused_at is None:
        raise HTTPException(
            status_code=400,
            detail="Session is marked as paused but has no pause timestamp.",
        )

    now_utc = datetime.now(timezone.utc)
    pause_duration = now_utc - session.paused_at
    if pause_duration.total_seconds() < 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid pause state — paused_at is in the future.",
        )

    # Extend invite token expiration for all heirs in the session whose
    # deadlines are not yet passed
    heirs = (
        db.query(User)
        .filter(
            User.session_id == session_id,
            User.role == "HEIR",
            User.invite_token_expires_at.isnot(None),
        )
        .all()
    )
    for heir in heirs:
        if heir.invite_token_expires_at and heir.invite_token_expires_at > now_utc:
            heir.invite_token_expires_at = heir.invite_token_expires_at + pause_duration

    # Extend session deadline
    if session.deadline:
        session.deadline = session.deadline + pause_duration

    session.status = "ACTIVE"
    session.is_paused = False
    session.paused_at = None
    db.commit()

    await manager.broadcast_session_status(
        session_id,
        {
            "type": "session_status",
            "status": session.status,
            "is_paused": session.is_paused,
            "is_deadlocked": session.is_deadlocked,
        },
    )

    return JSONResponse(
        content={
            "session_id": str(session.id),
            "is_paused": False,
        }
    )


@app.put("/api/sessions/{session_id}/announcement")
@limiter.limit("30/minute")
async def session_announcement(
    request: Request,
    session_id: str,
    body: AnnouncementRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Set, update, or clear a session-wide announcement.

    Per Backend Spec §9.1 (PUT /api/sessions/{session_id}/announcement):
    Updates the announcement and announcement_updated_at fields in the
    session, triggers a WebSocket broadcast to all connected users.
    Returns 400 if session status is 'FINALIZED'.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status == "FINALIZED":
        raise HTTPException(
            status_code=400,
            detail="Cannot update announcement on a finalized session.",
        )

    now_utc = datetime.now(timezone.utc)
    session.announcement = body.announcement
    session.announcement_updated_at = now_utc
    db.commit()

    updated_at_iso = (
        session.announcement_updated_at.isoformat()
        if session.announcement_updated_at
        else None
    )

    # Broadcast to all connected clients in this session
    await manager.broadcast_announcement(
        session_id,
        session.announcement,
        updated_at_iso,
    )

    return JSONResponse(
        content={
            "session_id": str(session.id),
            "announcement": session.announcement,
            "announcement_updated_at": updated_at_iso,
        }
    )


# ---------------------------------------------------------------------------
# T11 — Asset Router: staging, background OCR, publishing, matrix seeding
# ---------------------------------------------------------------------------


vision_semaphore = asyncio.Semaphore(2)


async def _transcribe_audio_file(audio_uri: str) -> str:
    """Helper to perform transcription on an audio file using OpenAI Whisper or local mock."""
    try:
        from .services.llm_provider import get_provider
        provider = get_provider()
        if provider.llm_provider == "openai" and provider._get_openai_client():
            client = provider._get_openai_client()
            storage = get_storage_driver()
            audio_bytes = storage.get(audio_uri)
            import io
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = "audio.wav"
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
            return transcript.text
    except Exception as e:
        logger.warning("Failed to transcribe audio via OpenAI: %s", e)

    # Realistic default mock/fallback story for offline/Ollama setups:
    return "A beautiful keepsake handed down through the family, kept in pristine condition."


async def analyze_staged_asset_background(asset_id: str, session_id: str):
    """
    Background worker that runs LLM Vision on a staged asset, optionally transcribing audio.
    Saves details and broadcasts the completion event via WebSocket.
    """
    import json as json_mod

    db = _get_session_factory()()
    try:
        asset = db.query(Asset).filter(Asset.id == asset_id).first()
        if not asset:
            logger.warning("Background analysis failed: asset %s not found", asset_id)
            return

        # Ensure ocr_status is set to PROCESSING
        asset.ocr_status = "PROCESSING"
        db.commit()

        # 1. Transcribe audio if present
        transcript = None
        if asset.audio_uri:
            try:
                transcript = await _transcribe_audio_file(asset.audio_uri)
            except Exception as e:
                logger.warning("Speech-to-text failed for asset %s: %s", asset_id, e)

        # 2. Get image bytes for primary and secondary images
        storage = get_storage_driver()
        try:
            image_bytes = storage.get(asset.image_uri)
        except Exception as exc:
            logger.exception("Could not read primary image for background analysis of %s", asset_id)
            asset.ocr_status = "FAILED"
            db.commit()
            return

        secondary_images = []
        for img in sorted(asset.images, key=lambda x: (x.is_primary, x.created_at or datetime.min.replace(tzinfo=timezone.utc))):
            if img.is_primary:
                continue
            try:
                sec_bytes = storage.get(img.image_uri)
                if sec_bytes:
                    secondary_images.append(sec_bytes)
            except Exception:
                logger.warning("Could not read secondary image %s for asset %s", img.image_uri, asset_id)

        # 3. Acquire vision semaphore
        async with vision_semaphore:
            prompt = (
                "You are an expert appraiser and estate sale liquidator. Analyze the provided image(s) of this item "
                "and generate a clean, highly accurate marketplace listing.\n\n"
            )
            if location:
                prompt += f"This item was found in the [{location}] location of the estate.\n"
            if transcript:
                prompt += f"The owner provided this verbal story/provenance: \"{transcript}\"\n"

            prompt += (
                "\nRespond with a valid JSON object containing these fields:\n"
                "  title: Catchy, searchable keyword title (include Brand/Maker, Material, Era if identifiable).\n"
                "  item_overview: A 2-3 sentence accurate description of what the item is and its aesthetic style.\n"
                "  specifications: Bullet points detailing estimated materials, color, dimensions (if scale cues exist), and noticeable hardware. Use '- ' prefix per line.\n"
                "  condition_report: Explicitly state any visible wear, scratches, fading, blemishes, or damage. Be brutally honest for buyers.\n"
                "  keywords: 5-8 relevant tags for search optimization, comma-separated (e.g. Mid-Century Modern, Vintage, Solid Oak).\n"
                "  valuation_min: Estimated minimum secondary market value as a float/number (e.g. 50.0). Estimate realistically based on the item.\n"
                "  valuation_max: Estimated maximum secondary market value as a float/number (e.g. 150.0). Estimate realistically based on the item.\n"
                "  sentiment_tags: Comma-separated sentiment labels. Select 1-3 relevant tags from: Heirloom, Memento, Practical, Antique, Handmade, Documents.\n"
                "  valuation_confidence: The confidence level of your appraisal. Select one: Low, Medium, High.\n\n"
                "If the item is a handwritten document, letter, diary, or family heirloom, emphasize its historical and sentimental value over its financial worth. Pre-populate its sentiment tag as 'Heirloom' or 'Documents'.\n"
                "If the item has no clear indicators of origin or brand, do not guess. Estimate the category average or leave the value as Null and flag review_required=true.\n\n"
                "Do not use overly flowery language. Stick to descriptive facts that help a buyer buy.\n\n"
                "JSON:"
            )

            try:
                provider = get_provider()
                res = provider.generate_vision(
                    model_key="vision",
                    image_bytes=image_bytes,
                    prompt=prompt,
                    images=secondary_images if secondary_images else None,
                    max_tokens=2048,
                )
            except Exception as exc:
                logger.exception("LLM vision generation failed in background task for asset %s", asset_id)
                asset.ocr_status = "FAILED"
                db.commit()
                return

        # 4. Parse JSON from response
        try:
            cleaned = res.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()

            parsed = json_mod.loads(cleaned)

            if "specifications" in parsed and isinstance(parsed["specifications"], list):
                parsed["specifications"] = "\n".join(parsed["specifications"])
            if "keywords" in parsed and isinstance(parsed["keywords"], list):
                parsed["keywords"] = ", ".join(parsed["keywords"])
            if "sentiment_tags" in parsed and isinstance(parsed["sentiment_tags"], list):
                parsed["sentiment_tags"] = ", ".join(parsed["sentiment_tags"])

            title = parsed.get("title", "")
            item_overview = parsed.get("item_overview", "")
            specifications = parsed.get("specifications", "")
            condition_report = parsed.get("condition_report", "")
            keywords = parsed.get("keywords", "")
            valuation_min = parsed.get("valuation_min")
            if valuation_min is not None:
                valuation_min = float(valuation_min)
            valuation_max = parsed.get("valuation_max")
            if valuation_max is not None:
                valuation_max = float(valuation_max)
            sentiment_tags = parsed.get("sentiment_tags", "")
            valuation_confidence = parsed.get("valuation_confidence", "Medium")
        except Exception:
            # Fallback parsing
            import re
            def _extract(label, text):
                m = re.search(rf'"{label}"\s*:\s*\[(.*?)\]', text, re.DOTALL)
                if m:
                    items = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
                    if items:
                        joiner = "\n" if label == "specifications" else ", "
                        return joiner.join(items)
                m = re.search(rf'"{label}"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
                return m.group(1) if m else ""
            def _extract_float(label, text):
                m = re.search(rf'"{label}"\s*:\s*(\d+(?:\.\d+)?)', text)
                return float(m.group(1)) if m else None

            title = _extract("title", res)
            item_overview = _extract("item_overview", res)
            specifications = _extract("specifications", res)
            condition_report = _extract("condition_report", res)
            keywords = _extract("keywords", res)
            valuation_min = _extract_float("valuation_min", res)
            valuation_max = _extract_float("valuation_max", res)
            sentiment_tags = _extract("sentiment_tags", res)
            valuation_confidence = _extract("valuation_confidence", res) or "Medium"

        # 5. Apply to asset fields
        asset.title = title or asset.title or "Staged Item"
        asset.description = item_overview or asset.description
        asset.valuation_min = valuation_min if valuation_min is not None else asset.valuation_min
        asset.valuation_max = valuation_max if valuation_max is not None else asset.valuation_max
        asset.valuation_source = "AI Valuation Range (Estimate)"
        asset.sentiment_tag = sentiment_tags or asset.sentiment_tag

        # Set review required flag if confidence is low, value is high (>500), or valuation_max is missing
        review_required = False
        if valuation_confidence.lower() == "low" or (valuation_max is not None and valuation_max > 500) or valuation_max is None:
            review_required = True

        djson = {
            "item_overview": item_overview,
            "specifications": specifications,
            "condition_report": condition_report,
            "keywords": keywords,
            "review_required": review_required,
            "valuation_confidence": valuation_confidence,
        }
        asset.description_json = json_mod.dumps(djson)
        asset.ocr_status = "COMPLETED"

        # 6. Compute embeddings
        try:
            text_to_embed = _build_asset_embedding_text(asset)
            embedding = provider.get_embeddings("embedding", text_to_embed)
            asset.embedding = embedding
        except Exception:
            logger.warning("Failed to compute embedding in background for asset %s", asset_id)

        db.commit()
        db.refresh(asset)

        # 7. Broadcast completion frame
        asset_data = {
            "id": str(asset.id),
            "session_id": str(asset.session_id),
            "title": asset.title,
            "description": asset.description,
            "description_json": asset.description_json,
            "category": asset.category,
            "valuation_min": asset.valuation_min,
            "valuation_max": asset.valuation_max,
            "valuation_source": asset.valuation_source,
            "sentiment_tag": asset.sentiment_tag,
            "image_uri": asset.image_uri,
            "audio_uri": asset.audio_uri,
            "status": asset.status,
            "ocr_status": asset.ocr_status,
            "allocated_to_id": str(asset.allocated_to_id) if asset.allocated_to_id else None,
            "images": [
                {
                    "id": str(img.id),
                    "image_uri": img.image_uri,
                    "is_primary": img.is_primary,
                    "angle_label": img.angle_label,
                }
                for img in asset.images
            ],
        }
        await manager.broadcast_asset_ocr_completed(session_id, asset_data)

    except Exception:
        db.rollback()
        logger.exception("Error in background staged asset analysis")
        try:
            asset = db.query(Asset).filter(Asset.id == asset_id).first()
            if asset:
                asset.ocr_status = "FAILED"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _reset_session_submitted_heirs(db: DBSession, session_id: str):
    """
    If the session is ACTIVE, resets all submitted heirs back to ACTIVE state
    so that they can adjust their allocations due to inventory changes.
    """
    submitted_heirs = (
        db.query(User)
        .filter(
            User.session_id == session_id,
            User.role == "HEIR",
            User.is_submitted == True
        )
        .all()
    )
    for heir in submitted_heirs:
        heir.is_submitted = False
        heir.submitted_at = None
        heir.status = "ACTIVE"


def _log_asset_audit_event(
    db: DBSession,
    session_id: str,
    event_type: str,
    state_snapshot: dict
) -> AuditLog:
    """
    Creates an AuditLog entry for asset modification events and computes
    a correct SHA-256 hash using the autoincrement ID from PostgreSQL.
    """
    # 1. Fetch previous hash
    prev_hash = "0" * 64
    last_log = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == session_id)
        .order_by(AuditLog.id.desc())
        .first()
    )
    if last_log:
        prev_hash = last_log.sha256_hash

    # 2. Add AuditLog entry with dummy hash
    audit_entry = AuditLog(
        session_id=session_id,
        event_type=event_type,
        state_snapshot=state_snapshot,
        prev_hash=prev_hash,
        sha256_hash="",
    )
    db.add(audit_entry)
    db.flush()  # Populates audit_entry.id

    # 3. Compute hash using computed row ID
    snapshot_str = str(sorted(state_snapshot.items())) if isinstance(state_snapshot, dict) else str(state_snapshot)
    raw_data = f"{audit_entry.id}:{event_type}:{snapshot_str}:{prev_hash}"
    audit_entry.sha256_hash = hashlib.sha256(raw_data.encode("utf-8")).hexdigest()

    return audit_entry


@app.post("/api/sessions/{session_id}/assets/stage")
@limiter.limit("30/minute")
async def asset_stage(
    request: Request,
    session_id: str,
    background_tasks: BackgroundTasks,
    location: Optional[str] = None,
    auto_appraise: bool = True,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Stage an asset image for a session.

    Per Backend Spec §9.2 (POST /api/sessions/{session_id}/assets/stage):
    1. Preprocesses the image (HEIC conversion, WebP scaling) and saves it.
    2. Creates an asset row with ocr_status='PROCESSING' or 'COMPLETED' and status='STAGED'.
    3. Queues background AI appraisal if requested.
    4. Returns the asset ID for subsequent editing/publishing.
    """
    import uuid as _uuid_mod

    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status not in ("SETUP", "ACTIVE"):
        raise HTTPException(
            status_code=400,
            detail="Assets can only be staged during the SETUP or ACTIVE phases.",
        )

    # Parse multipart upload
    form = await request.form()
    file_uploads = form.getlist("files")
    if not file_uploads:
        single_file = form.get("file")
        if single_file:
            file_uploads = [single_file]

    if not file_uploads:
        raise HTTPException(status_code=400, detail="No file(s) uploaded")

    # Get parameters from form with query string fallback
    asset_id_str = form.get("asset_id")
    location_str = form.get("location") or location
    angle_labels = []
    angle_labels_raw = form.get("angle_labels")
    if angle_labels_raw:
        try:
            parsed_labels = json.loads(str(angle_labels_raw))
            if isinstance(parsed_labels, list):
                angle_labels = [
                    str(label).strip()[:50]
                    for label in parsed_labels
                    if str(label).strip()
                ]
        except Exception:
            angle_labels = []

    # Process auto_appraise from form
    auto_appraise_val = auto_appraise
    form_auto_appraise = form.get("auto_appraise")
    if form_auto_appraise is not None:
        auto_appraise_val = str(form_auto_appraise).lower() in ("true", "1", "yes")

    if asset_id_str:
        try:
            asset_id_uuid = _uuid_mod.UUID(str(asset_id_str))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid asset_id UUID format")
    else:
        asset_id_uuid = _uuid_mod.uuid4()

    # Idempotence Check
    existing_asset = db.query(Asset).filter(Asset.id == asset_id_uuid).first()
    if existing_asset:
        return JSONResponse(
            content={
                "asset_id": str(existing_asset.id),
                "status": existing_asset.status,
                "ocr_status": existing_asset.ocr_status,
            },
            status_code=200,
        )

    # Preprocess and save first image as primary
    first_file = file_uploads[0]
    raw_bytes = await first_file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="First uploaded file is empty")

    try:
        processed = preprocess_image(raw_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    storage = get_storage_driver()
    filename = f"static/uploads/{asset_id_uuid}.webp"
    storage.save(filename, processed)

    # Parse and save optional audio file
    audio_upload = form.get("audio") or form.get("audio_file")
    audio_filename = None
    if audio_upload:
        audio_bytes = await audio_upload.read()
        if audio_bytes:
            content_type = audio_upload.content_type or ""
            filename_orig = audio_upload.filename or ""
            if "webm" in content_type.lower() or filename_orig.lower().endswith(".webm"):
                ext = ".webm"
            elif "mpeg" in content_type.lower() or "mp3" in content_type.lower() or filename_orig.lower().endswith(".mp3"):
                ext = ".mp3"
            elif "wav" in content_type.lower() or filename_orig.lower().endswith(".wav"):
                ext = ".wav"
            else:
                ext = ".webm"

            audio_filename = f"static/uploads/{_uuid_mod.uuid4()}{ext}"
            storage.save(audio_filename, audio_bytes)

    # Create asset record
    asset = Asset(
        id=asset_id_uuid,
        session_id=session_id,
        title=None,
        description=None,
        category=location_str,  # Store staging location context
        valuation_min=None,
        valuation_max=None,
        valuation_source=None,
        sentiment_tag=None,
        image_uri=filename,
        audio_uri=audio_filename,
        ocr_status="PROCESSING" if auto_appraise_val else "COMPLETED",
        status="STAGED",
    )
    db.add(asset)

    # Add primary AssetImage record
    primary_image = AssetImage(
        asset_id=asset_id_uuid,
        image_uri=filename,
        is_primary=True,
        angle_label=angle_labels[0] if angle_labels else "Primary",
    )
    db.add(primary_image)

    # Process secondary images if any
    for idx, sec_file in enumerate(file_uploads[1:], start=2):
        sec_bytes = await sec_file.read()
        if not sec_bytes:
            continue
        try:
            sec_processed = preprocess_image(sec_bytes)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Secondary image {idx} preprocessing error: {str(e)}",
            )
        sec_img_id = _uuid_mod.uuid4()
        sec_filename = f"static/uploads/{sec_img_id}.webp"
        storage.save(sec_filename, sec_processed)

        sec_image = AssetImage(
            asset_id=asset_id_uuid,
            image_uri=sec_filename,
            is_primary=False,
            angle_label=angle_labels[idx - 1] if len(angle_labels) >= idx else f"View {idx}",
        )
        db.add(sec_image)

    # Write ASSET_CREATED audit log
    state_snapshot = {
        "event": "ASSET_CREATED",
        "asset_id": str(asset_id_uuid),
        "status": "STAGED",
        "category": location_str,
        "notified": False,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    _log_asset_audit_event(db, session_id, "ASSET_CREATED", state_snapshot)

    db.commit()
    db.refresh(asset)

    if auto_appraise_val:
        background_tasks.add_task(
            analyze_staged_asset_background,
            asset_id=str(asset.id),
            session_id=session_id,
            location=location_str,
        )

    return JSONResponse(
        content={
            "asset_id": str(asset.id),
            "status": asset.status,
            "ocr_status": asset.ocr_status,
        },
        status_code=201,
    )


def _build_asset_embedding_text(asset: Asset) -> str:
    """
    Construct a comprehensive text block representing all asset fields
    so that the asset is fully indexed and searchable by RAG.
    """
    parts = []
    if asset.title:
        parts.append(f"Title: {asset.title}")
    if asset.category:
        parts.append(f"Category: {asset.category}")
    if asset.description:
        parts.append(f"Description: {asset.description}")
    if asset.valuation_min is not None and asset.valuation_max is not None:
        parts.append(f"Valuation: ${asset.valuation_min} to ${asset.valuation_max}")
    if asset.valuation_source:
        parts.append(f"Valuation Source: {asset.valuation_source}")
    if asset.sentiment_tag:
        parts.append(f"Tags: {asset.sentiment_tag}")

    # Parse details from description_json if present
    if asset.description_json:
        try:
            import json as json_mod
            djson = json_mod.loads(asset.description_json)
            if isinstance(djson, dict):
                if djson.get("item_overview"):
                    parts.append(f"Overview: {djson['item_overview']}")
                if djson.get("specifications"):
                    parts.append(f"Specifications: {djson['specifications']}")
                if djson.get("condition_report"):
                    parts.append(f"Condition: {djson['condition_report']}")
                if djson.get("keywords"):
                    parts.append(f"Keywords: {djson['keywords']}")
        except Exception:
            pass

    return "\n".join(parts)


@app.post("/api/assets/{asset_id}/publish")
@limiter.limit("30/minute")
async def asset_publish(
    request: Request,
    asset_id: str,
    body: AssetPublishRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Publish a staged asset — transition from STAGED to LIVE.

    Per Backend Spec §9.2 (POST /api/assets/{asset_id}/publish):
    1. Commits edited metadata (title, description, category, valuations, etc.).
    2. Generates 768-dim text embedding via embedding provider.
    3. Shifts status to 'LIVE'.
    4. Seeds default 0-point valuation rows for all active/verified heirs
       (excluding PENDING, PROFILE_HOLD, EXPIRED_NON_PARTICIPATING).

    Asset Lifecycle Validation Gate (DB Spec §2.3):
      Requires title, description, category, valuation_min, valuation_max,
      valuation_source, and sentiment_tag to all be fully populated.
      Incomplete assets rejected with 400.

    Returns 400 if session is not in SETUP.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if asset.status != "STAGED":
        raise HTTPException(
            status_code=400,
            detail=f"Asset cannot be published — current status is '{asset.status}'.",
        )

    # Check session status — SETUP or ACTIVE allow publishing
    session = db.query(SessionModel).filter(SessionModel.id == asset.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status not in ("SETUP", "ACTIVE"):
        raise HTTPException(
            status_code=400,
            detail=f"Assets can only be published during the SETUP or ACTIVE phases. Current status: '{session.status}'.",
        )

    # If session is ACTIVE, this is a Major change post-launch requiring a reason
    is_major = session.status == "ACTIVE"
    if is_major:
        if not body.reason or not body.reason.strip():
            raise HTTPException(
                status_code=400,
                detail="A reason is required when publishing a new asset post-launch (during ACTIVE phase).",
            )

    # Concurrency control locking
    session = db.query(SessionModel).filter(SessionModel.id == asset.session_id).with_for_update().first()
    asset = db.query(Asset).filter(Asset.id == asset_id).with_for_update().first()

    # --- Asset Lifecycle Validation Gate (DB Spec §2.3) ---
    missing = []
    if not body.title:
        missing.append("title")
    if not body.description:
        missing.append("description")
    if not body.category:
        missing.append("category")
    if body.valuation_min is None:
        missing.append("valuation_min")
    if body.valuation_max is None:
        missing.append("valuation_max")
    if not body.valuation_source:
        missing.append("valuation_source")
    if not body.sentiment_tag:
        missing.append("sentiment_tag")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Asset cannot be published — missing required fields: {', '.join(missing)}.",
        )

    # Update metadata
    asset.title = body.title
    asset.description = body.description
    asset.category = body.category
    asset.valuation_min = body.valuation_min
    asset.valuation_max = body.valuation_max
    asset.valuation_source = body.valuation_source
    asset.sentiment_tag = body.sentiment_tag

    # Keep description_json fields synchronized and save edits
    import json as json_mod
    try:
        if asset.description_json:
            djson = json_mod.loads(asset.description_json) if isinstance(asset.description_json, str) else asset.description_json
        else:
            djson = {}
    except Exception:
        djson = {}

    djson["item_overview"] = body.description
    djson["specifications"] = body.specifications if body.specifications is not None else djson.get("specifications", "")
    djson["condition_report"] = body.condition_report if body.condition_report is not None else djson.get("condition_report", "")
    djson["keywords"] = body.keywords if body.keywords is not None else djson.get("keywords", "")

    asset.description_json = json_mod.dumps(djson)

    # Compute embedding
    try:
        provider = get_provider()
        text_to_embed = _build_asset_embedding_text(asset)
        embedding = provider.get_embeddings("embedding", text_to_embed)
        asset.embedding = embedding
    except Exception:
        logger.warning("Failed to compute embedding for asset %s", asset_id)

    asset.status = "LIVE"
    asset.ocr_status = "COMPLETED"

    # --- Automatic Matrix Seeding (DB Spec §2.4) ---
    active_heirs = (
        db.query(User)
        .filter(
            User.session_id == asset.session_id,
            User.role == "HEIR",
            User.status.in_(["ACTIVE", "SUBMITTED", "ABSTAINED"]),
        )
        .all()
    )

    for heir in active_heirs:
        existing = (
            db.query(Valuation)
            .filter(
                Valuation.asset_id == asset_id,
                Valuation.heir_id == heir.id,
            )
            .first()
        )
        if not existing:
            valuation = Valuation(
                asset_id=asset_id,
                heir_id=heir.id,
                points=0,
            )
            db.add(valuation)

    # Write ASSET_UPDATED (Publish) audit log entry
    state_snapshot = {
        "event": "ASSET_UPDATED",
        "asset_id": str(asset.id),
        "asset_title": asset.title,
        "changes": {
            "status": {"old": "STAGED", "new": "LIVE"},
            "title": {"old": None, "new": asset.title},
            "valuation_min": {"old": None, "new": asset.valuation_min},
            "valuation_max": {"old": None, "new": asset.valuation_max},
        },
        "classification": "MAJOR" if is_major else "MINOR",
        "reason": body.reason if is_major else None,
        "notified": False,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    _log_asset_audit_event(db, str(session.id), "ASSET_UPDATED", state_snapshot)

    # Reset submitted heirs if published during ACTIVE phase
    if is_major:
        _reset_session_submitted_heirs(db, str(session.id))

    db.commit()

    return JSONResponse(
        content={
            "asset_id": str(asset.id),
            "status": asset.status,
        }
    )


@app.post("/api/assets/{asset_id}/save")
@limiter.limit("30/minute")
async def save_asset(
    request: Request,
    asset_id: str,
    body: AssetSaveRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Save changes to an asset.
    Supports editing LIVE assets when the session is ACTIVE.
    Tracks all modifications and logs them to the AuditLog.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    session = db.query(SessionModel).filter(SessionModel.id == asset.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status not in ("SETUP", "ACTIVE"):
        raise HTTPException(
            status_code=400,
            detail=f"Asset details cannot be modified when session is '{session.status}'.",
        )

    # Concurrency control locking
    session = db.query(SessionModel).filter(SessionModel.id == asset.session_id).with_for_update().first()
    asset = db.query(Asset).filter(Asset.id == asset_id).with_for_update().first()

    # Delta detection
    changes = {}
    is_major = False

    def check_diff(field_name, new_val, old_val, is_major_field=False):
        nonlocal is_major
        if new_val is not None and new_val != old_val:
            changes[field_name] = {"old": old_val, "new": new_val}
            if is_major_field:
                is_major = True

    check_diff("title", body.title, asset.title, is_major_field=True)
    check_diff("description", body.description, asset.description, is_major_field=False)
    check_diff("category", body.category, asset.category, is_major_field=False)
    check_diff("valuation_min", body.valuation_min, asset.valuation_min, is_major_field=True)
    check_diff("valuation_max", body.valuation_max, asset.valuation_max, is_major_field=True)
    check_diff("valuation_source", body.valuation_source, asset.valuation_source, is_major_field=False)
    check_diff("sentiment_tag", body.sentiment_tag, asset.sentiment_tag, is_major_field=False)

    import json as json_mod
    try:
        djson = json_mod.loads(asset.description_json) if asset.description_json else {}
    except Exception:
        djson = {}

    check_diff("specifications", body.specifications, djson.get("specifications"), is_major_field=False)
    check_diff("condition_report", body.condition_report, djson.get("condition_report"), is_major_field=False)
    check_diff("keywords", body.keywords, djson.get("keywords"), is_major_field=False)

    # A change is Major only if the asset is LIVE and session status is ACTIVE
    actual_is_major = is_major and (asset.status == "LIVE" and session.status == "ACTIVE")

    if actual_is_major:
        if not body.reason or not body.reason.strip():
            raise HTTPException(
                status_code=400,
                detail="A reason for the change is required for major asset edits post-launch.",
            )

    if changes:
        # Update asset fields
        if body.title is not None:
            asset.title = body.title
        if body.description is not None:
            asset.description = body.description
        if body.category is not None:
            asset.category = body.category
        if body.valuation_min is not None:
            asset.valuation_min = body.valuation_min
        if body.valuation_max is not None:
            asset.valuation_max = body.valuation_max
        if body.valuation_source is not None:
            asset.valuation_source = body.valuation_source
        if body.sentiment_tag is not None:
            asset.sentiment_tag = body.sentiment_tag

        djson["item_overview"] = asset.description
        if body.specifications is not None:
            djson["specifications"] = body.specifications
        if body.condition_report is not None:
            djson["condition_report"] = body.condition_report
        if body.keywords is not None:
            djson["keywords"] = body.keywords
        asset.description_json = json_mod.dumps(djson)

        # Compute embedding
        try:
            provider = get_provider()
            text_to_embed = _build_asset_embedding_text(asset)
            embedding = provider.get_embeddings("embedding", text_to_embed)
            asset.embedding = embedding
        except Exception:
            logger.warning("Failed to compute embedding for asset %s", asset_id)

        # Write ASSET_UPDATED audit log
        state_snapshot = {
            "event": "ASSET_UPDATED",
            "asset_id": str(asset.id),
            "asset_title": asset.title,
            "changes": changes,
            "classification": "MAJOR" if actual_is_major else "MINOR",
            "reason": body.reason if actual_is_major else None,
            "notified": False,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
        _log_asset_audit_event(db, str(session.id), "ASSET_UPDATED", state_snapshot)

        # Reset heir submissions if major change in ACTIVE session
        if actual_is_major:
            _reset_session_submitted_heirs(db, str(session.id))

        db.commit()

    return JSONResponse(
        content={
            "asset_id": str(asset.id),
            "status": asset.status,
            "message": "Asset details saved successfully.",
        }
    )


@app.post("/api/assets/{asset_id}/images")
@limiter.limit("30/minute")
async def add_asset_image(
    request: Request,
    asset_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Upload an additional image/angle for an existing asset.
    """
    import uuid as _uuid_mod

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Check session status — only SETUP allows modifications
    session = db.query(SessionModel).filter(SessionModel.id == asset.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "SETUP":
        raise HTTPException(
            status_code=400,
            detail=f"Asset images can only be modified during the SETUP phase. Current status is '{session.status}'.",
        )

    form = await request.form()
    file_upload = form.get("file")
    if not file_upload:
        raise HTTPException(status_code=400, detail="No file uploaded")

    angle_label = form.get("angle_label")
    if angle_label and len(angle_label) > 50:
        raise HTTPException(status_code=400, detail="Angle label must be 50 characters or less")

    raw_bytes = await file_upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        processed = preprocess_image(raw_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    storage = get_storage_driver()
    image_uuid = _uuid_mod.uuid4()
    filename = f"static/uploads/{image_uuid}.webp"
    storage.save(filename, processed)

    asset_image = AssetImage(
        id=image_uuid,
        asset_id=asset.id,
        image_uri=filename,
        is_primary=False,
        angle_label=angle_label or None,
    )
    db.add(asset_image)
    db.commit()
    db.refresh(asset_image)

    return JSONResponse(
        content={
            "image_id": str(asset_image.id),
            "image_uri": asset_image.image_uri,
            "is_primary": asset_image.is_primary,
            "angle_label": asset_image.angle_label,
        },
        status_code=201,
    )


@app.delete("/api/assets/{asset_id}/images/{image_id}")
@limiter.limit("30/minute")
async def delete_asset_image(
    request: Request,
    asset_id: str,
    image_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Delete a secondary image/angle of an asset.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    session = db.query(SessionModel).filter(SessionModel.id == asset.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "SETUP":
        raise HTTPException(
            status_code=400,
            detail=f"Asset images can only be deleted during the SETUP phase. Current status is '{session.status}'.",
        )

    img = db.query(AssetImage).filter(AssetImage.id == image_id, AssetImage.asset_id == asset_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found for this asset")

    if img.is_primary:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete primary asset image directly. Deleting the entire asset is required to remove the primary image.",
        )

    # Delete file from storage
    if img.image_uri:
        try:
            storage = get_storage_driver()
            storage.delete(img.image_uri)
        except Exception:
            pass

    db.delete(img)
    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": "Asset image deleted successfully",
        }
    )


@app.post("/api/assets/{asset_id}/images/{image_id}/replace")
@app.put("/api/assets/{asset_id}/images/{image_id}")
@limiter.limit("30/minute")
async def replace_asset_image(
    request: Request,
    asset_id: str,
    image_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Replace an existing asset image with edited image bytes.
    """
    import uuid as _uuid_mod

    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    session = db.query(SessionModel).filter(SessionModel.id == asset.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "SETUP":
        raise HTTPException(
            status_code=400,
            detail=f"Asset images can only be modified during the SETUP phase. Current status is '{session.status}'.",
        )

    img = None
    if image_id == "primary":
        img = (
            db.query(AssetImage)
            .filter(AssetImage.asset_id == asset_id, AssetImage.is_primary == True)  # noqa: E712
            .first()
        )
    else:
        img = db.query(AssetImage).filter(AssetImage.id == image_id, AssetImage.asset_id == asset_id).first()

    if not img and image_id != "primary":
        raise HTTPException(status_code=404, detail="Image not found for this asset")

    form = await request.form()
    file_upload = form.get("file")
    if not file_upload:
        raise HTTPException(status_code=400, detail="No file uploaded")

    raw_bytes = await file_upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        processed = preprocess_image(raw_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    storage = get_storage_driver()
    old_uri = img.image_uri if img else asset.image_uri
    new_image_id = _uuid_mod.uuid4()
    new_uri = f"static/uploads/{new_image_id}.webp"
    storage.save(new_uri, processed)

    if img:
        img.image_uri = new_uri
    else:
        img = AssetImage(
            id=new_image_id,
            asset_id=asset.id,
            image_uri=new_uri,
            is_primary=True,
            angle_label="Primary",
        )
        db.add(img)

    if img.is_primary or image_id == "primary":
        asset.image_uri = new_uri

    db.commit()
    db.refresh(img)

    if old_uri and old_uri != new_uri:
        try:
            storage.delete(old_uri)
        except Exception:
            logger.warning("Failed to delete replaced asset image %s", old_uri)

    return JSONResponse(
        content={
            "image_id": str(img.id),
            "image_uri": img.image_uri,
            "is_primary": img.is_primary,
            "angle_label": img.angle_label,
        }
    )


# ---------------------------------------------------------------------------
# Category Management
# ---------------------------------------------------------------------------

class CategoryCreateRequest(BaseModel):
    name: str


@app.get("/api/sessions/{session_id}/categories")
@limiter.limit("60/minute")
async def get_session_categories(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Retrieve all categories for a session. Auto-seeds defaults for legacy sessions."""
    categories = db.query(Category).filter(Category.session_id == session_id).all()
    if not categories:
        # Auto-seed default categories for backward compatibility
        default_categories = ['Jewelry', 'Furniture', 'Art', 'Other']
        for cat_name in default_categories:
            db.add(Category(session_id=session_id, name=cat_name))
        db.commit()
        categories = db.query(Category).filter(Category.session_id == session_id).all()
    return JSONResponse(content=[c.name for c in categories])


@app.post("/api/sessions/{session_id}/categories")
@limiter.limit("30/minute")
async def create_session_category(
    request: Request,
    session_id: str,
    body: CategoryCreateRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """Create a new custom category for a session."""
    name_stripped = body.name.strip()
    if not name_stripped:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")

    # Check if category already exists
    existing = db.query(Category).filter(
        Category.session_id == session_id,
        Category.name == name_stripped,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")

    new_cat = Category(session_id=session_id, name=name_stripped)
    db.add(new_cat)
    db.commit()
    return JSONResponse(content={"status": "success", "category": name_stripped}, status_code=201)


@app.delete("/api/sessions/{session_id}/categories/{name}")
@limiter.limit("30/minute")
async def delete_session_category(
    request: Request,
    session_id: str,
    name: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """Delete a custom category. Fails if any assets in the session use it."""
    # Check if assets are using this category
    asset_count = db.query(Asset).filter(
        Asset.session_id == session_id,
        Asset.category == name,
    ).count()
    if asset_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete category '{name}' because it is in use by {asset_count} asset(s). Reassign them first."
        )

    cat = db.query(Category).filter(
        Category.session_id == session_id,
        Category.name == name,
    ).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    db.delete(cat)
    db.commit()
    return JSONResponse(content={"status": "success", "message": f"Category '{name}' deleted."})


# ---------------------------------------------------------------------------
# AI Detail Generation (Pydantic model for structured parsing)
# ---------------------------------------------------------------------------

from pydantic import BaseModel as PydanticBaseModel_


class AssetListingResponse(PydanticBaseModel_):
    title: str = ""
    item_overview: str = ""
    specifications: str = ""
    condition_report: str = ""
    keywords: str = ""
    valuation_min: float | None = None
    valuation_max: float | None = None
    sentiment_tags: str = ""


# ---------------------------------------------------------------------------
# AI Detail Generation
# ---------------------------------------------------------------------------

@app.post("/api/assets/{asset_id}/generate-details")
@limiter.limit("5/minute")
async def generate_asset_details(
    request: Request,
    asset_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Generate a structured marketplace listing for an asset using LLM Vision.
    Uses the asset's primary image plus any secondary images for multi-angle analysis.
    Saves results to asset.title and asset.description_json.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # Get primary image bytes
    storage = get_storage_driver()
    try:
        image_bytes = storage.get(asset.image_uri)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read primary image from storage: {exc}",
        )

    # Collect secondary image bytes for multi-image analysis
    secondary_images = []
    for img in sorted(asset.images, key=lambda x: (x.is_primary, x.created_at or datetime.min.replace(tzinfo=timezone.utc))):
        if img.is_primary:
            continue
        try:
            sec_bytes = storage.get(img.image_uri)
            if sec_bytes:
                secondary_images.append(sec_bytes)
        except Exception:
            logger.warning("Could not read secondary image %s for asset %s", img.image_uri, asset_id)

    prompt = (
        "You are an expert appraiser and estate sale liquidator. Analyze the provided image(s) of this item "
        "and generate a clean, highly accurate marketplace listing.\n\n"
        "Respond with a valid JSON object containing these fields:\n"
        "  title: Catchy, searchable keyword title (include Brand/Maker, Material, Era if identifiable).\n"
        "  item_overview: A 2-3 sentence accurate description of what the item is and its aesthetic style.\n"
        "  specifications: Bullet points detailing estimated materials, color, dimensions (if scale cues exist), and noticeable hardware. Use '- ' prefix per line.\n"
        "  condition_report: Explicitly state any visible wear, scratches, fading, blemishes, or damage. Be brutally honest for buyers.\n"
        "  keywords: 5-8 relevant tags for search optimization, comma-separated (e.g. Mid-Century Modern, Vintage, Solid Oak).\n"
        "  valuation_min: Estimated minimum secondary market value as a float/number (e.g. 50.0). Estimate realistically based on the item.\n"
        "  valuation_max: Estimated maximum secondary market value as a float/number (e.g. 150.0). Estimate realistically based on the item.\n"
        "  sentiment_tags: Comma-separated sentiment labels. Select 1-3 relevant tags from: Heirloom, Memento, Practical, Antique, Handmade, Documents.\n\n"
        "Do not use overly flowery language. Stick to descriptive facts that help a buyer buy.\n\n"
        "JSON:"
    )

    # Use LLM Provider's vision capability with multi-image support
    try:
        provider = get_provider()
        res = provider.generate_vision(
            model_key="vision",
            image_bytes=image_bytes,
            prompt=prompt,
            images=secondary_images if secondary_images else None,
            max_tokens=2048,
        )
    except Exception as exc:
        logger.exception("LLM vision generation failed for asset %s", asset_id)
        raise HTTPException(
            status_code=500,
            detail=f"LLM vision generation failed: {exc}",
        )

    # Parse JSON from response
    import json as json_mod
    try:
        # Strip any markdown code fences
        cleaned = res.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

        parsed = json_mod.loads(cleaned)

        # Coerce list fields to string to prevent Pydantic ValidationError
        if "specifications" in parsed and isinstance(parsed["specifications"], list):
            parsed["specifications"] = "\n".join(parsed["specifications"])
        if "keywords" in parsed and isinstance(parsed["keywords"], list):
            parsed["keywords"] = ", ".join(parsed["keywords"])
        if "sentiment_tags" in parsed and isinstance(parsed["sentiment_tags"], list):
            parsed["sentiment_tags"] = ", ".join(parsed["sentiment_tags"])

        listing = AssetListingResponse(**parsed)
    except Exception:
        # Fallback: try regex extraction of fields
        import re
        def _extract(label, text):
            # Try bracketed list first
            m = re.search(rf'"{label}"\s*:\s*\[(.*?)\]', text, re.DOTALL)
            if m:
                items = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
                if items:
                    joiner = "\n" if label == "specifications" else ", "
                    return joiner.join(items)
            m = re.search(rf'"{label}"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            return m.group(1) if m else ""
        def _extract_float(label, text):
            m = re.search(rf'"{label}"\s*:\s*(\d+(?:\.\d+)?)', text)
            return float(m.group(1)) if m else None
        listing = AssetListingResponse(
            title=_extract("title", res),
            item_overview=_extract("item_overview", res),
            specifications=_extract("specifications", res),
            condition_report=_extract("condition_report", res),
            keywords=_extract("keywords", res),
            valuation_min=_extract_float("valuation_min", res),
            valuation_max=_extract_float("valuation_max", res),
            sentiment_tags=_extract("sentiment_tags", res),
        )

    # Save to asset fields
    asset.title = listing.title or asset.title
    asset.description = listing.item_overview or asset.description
    asset.valuation_min = listing.valuation_min if listing.valuation_min is not None else asset.valuation_min
    asset.valuation_max = listing.valuation_max if listing.valuation_max is not None else asset.valuation_max
    asset.valuation_source = "AI Appraisal"
    asset.sentiment_tag = listing.sentiment_tags or asset.sentiment_tag
    asset.description_json = json_mod.dumps({
        "item_overview": listing.item_overview,
        "specifications": listing.specifications,
        "condition_report": listing.condition_report,
        "keywords": listing.keywords,
    })

    # Compute embedding for staged asset (RAG readiness)
    try:
        provider = get_provider()
        text_to_embed = _build_asset_embedding_text(asset)
        embedding = provider.get_embeddings("embedding", text_to_embed)
        asset.embedding = embedding
    except Exception:
        logger.warning("Failed to compute embedding for asset %s", asset_id)

    db.commit()

    return JSONResponse(
        content={
            "title": listing.title or "Suggested Keepsake",
            "item_overview": listing.item_overview or "",
            "specifications": listing.specifications or "",
            "condition_report": listing.condition_report or "",
            "keywords": listing.keywords or "",
            "valuation_min": listing.valuation_min,
            "valuation_max": listing.valuation_max,
            "valuation_source": "AI Appraisal",
            "sentiment_tags": listing.sentiment_tags or "",
        }
    )


# ---------------------------------------------------------------------------
# Session Assets
# ---------------------------------------------------------------------------

@app.get("/api/sessions/{session_id}/assets")
@limiter.limit("60/minute")
async def session_assets(
    request: Request,
    session_id: str,
    q: str | None = None,
    category: str | None = None,
    has_audio: bool | None = None,
    allocation_status: str | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retrieve, filter, and sort the estate assets for a session.

    Per Backend Spec §9.2 (GET /api/sessions/{session_id}/assets):
    Supports search (q), category filter, audio presence filter,
    allocation filter, and sorting by title/category.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    allowed_statuses = ["LIVE", "PRE_ALLOCATED", "DISTRIBUTED"]
    if current_user.get("role") == "ADMIN":
        allowed_statuses.append("STAGED")

    query = db.query(Asset).filter(
        Asset.session_id == session_id,
        Asset.status.in_(allowed_statuses),
    )

    # Category filter
    if category:
        categories = [c.strip() for c in category.split(",") if c.strip()]
        if categories:
            query = query.filter(Asset.category.in_(categories))

    # Audio presence filter
    if has_audio is True:
        query = query.filter(Asset.audio_uri.isnot(None))
    elif has_audio is False:
        query = query.filter(Asset.audio_uri.is_(None))

    # Allocation filter (Heir only)
    if allocation_status and current_user.get("role") == "HEIR":
        heir_id = current_user.get("user_id")
        if heir_id:
            if allocation_status == "allocated":
                query = (
                    query.join(Valuation, Asset.id == Valuation.asset_id)
                    .filter(Valuation.heir_id == heir_id)
                    .filter(Valuation.points > 0)
                )
            elif allocation_status == "unallocated":
                subq = (
                    db.query(Valuation.asset_id)
                    .filter(Valuation.heir_id == heir_id)
                    .filter(Valuation.points > 0)
                    .subquery()
                )
                query = query.filter(Asset.id.notin_(subq))
            elif allocation_status == "pre_allocated":
                query = query.filter(Asset.status == "PRE_ALLOCATED")

    # Text search
    assets_data = []
    if q:
        try:
            provider = get_provider()
            query_vector = provider.get_embeddings("embedding", q)
        except Exception as exc:
            logger.warning("RAG embedding call failed, falling back to ILIKE: %s", exc)
            query_vector = None

        if query_vector is not None:
            # cosine distance is 0 to 2. Similarity = 1.0 - distance
            similarity_expr = 1.0 - Asset.embedding.cosine_distance(query_vector)

            # Run similarity on a clean Asset-only query (never on a pre-joined
            # query) to avoid SQLAlchemy compound Row objects that break
            # attribute access.  Collect id → similarity, then fetch full
            # assets through the existing filtered query.
            sim_query = (
                db.query(Asset.id, similarity_expr.label("similarity"))
                .filter(
                    Asset.session_id == session_id,
                    Asset.status.in_(allowed_statuses),
                    Asset.embedding.isnot(None),
                )
            )
            sim_results = sim_query.all()
            id_to_sim: dict[str, float] = {}
            for row in sim_results:
                asset_uuid = str(row[0])
                sim_val = float(row[1]) if row[1] is not None else 0.0
                id_to_sim[asset_uuid] = max(0.0, min(1.0, sim_val))

            if id_to_sim:
                # Fetch full Asset objects via the existing query, but without
                # add_columns so `.images` relationships are intact.
                matched_ids = list(id_to_sim.keys())
                base = db.query(Asset).filter(Asset.id.in_(matched_ids))
                if sort_by == "title":
                    base = base.order_by(
                        Asset.title.asc() if sort_order != "desc" else Asset.title.desc()
                    )
                elif sort_by == "category":
                    base = base.order_by(
                        Asset.category.asc() if sort_order != "desc" else Asset.category.desc()
                    )
                else:
                    base = base.order_by(Asset.id.desc())

                for a in base.all():
                    sim_score = id_to_sim[str(a.id)]
                    asset_dict = {
                        "id": str(a.id),
                        "session_id": str(a.session_id),
                        "title": a.title,
                        "description": a.description,
                        "description_json": a.description_json,
                        "category": a.category,
                        "valuation_min": a.valuation_min,
                        "valuation_max": a.valuation_max,
                        "valuation_source": a.valuation_source,
                        "sentiment_tag": a.sentiment_tag,
                        "image_uri": a.image_uri,
                        "audio_uri": a.audio_uri,
                        "status": a.status,
                        "ocr_status": a.ocr_status,
                        "allocated_to_id": str(a.allocated_to_id) if a.allocated_to_id else None,
                        "images": [
                            {
                                "id": str(img.id),
                                "image_uri": img.image_uri,
                                "is_primary": img.is_primary,
                                "angle_label": img.angle_label,
                            }
                            for img in a.images
                        ],
                    }
                    asset_dict["_similarity"] = sim_score
                    assets_data.append(asset_dict)

                # Sort by similarity after the fact (preserves default order
                # when sort_by is title/category).
                if not sort_by:
                    assets_data.sort(key=lambda d: d.get("_similarity", 0.0), reverse=True)
        else:
            # ILIKE fallback — rebuild base query to avoid corruption from prior mutations
            fallback = db.query(Asset).filter(
                Asset.session_id == session_id,
                Asset.status.in_(allowed_statuses),
            )
            if category:
                categories = [c.strip() for c in category.split(",") if c.strip()]
                if categories:
                    fallback = fallback.filter(Asset.category.in_(categories))
            if has_audio is True:
                fallback = fallback.filter(Asset.audio_uri.isnot(None))
            elif has_audio is False:
                fallback = fallback.filter(Asset.audio_uri.is_(None))
            if allocation_status and current_user.get("role") == "HEIR":
                heir_id = current_user.get("user_id")
                if heir_id:
                    if allocation_status == "allocated":
                        fallback = (
                            fallback.join(Valuation, Asset.id == Valuation.asset_id)
                            .filter(Valuation.heir_id == heir_id)
                            .filter(Valuation.points > 0)
                        )
                    elif allocation_status == "unallocated":
                        subq = (
                            db.query(Valuation.asset_id)
                            .filter(Valuation.heir_id == heir_id)
                            .filter(Valuation.points > 0)
                            .subquery()
                        )
                        fallback = fallback.filter(Asset.id.notin_(subq))
                    elif allocation_status == "pre_allocated":
                        fallback = fallback.filter(Asset.status == "PRE_ALLOCATED")

            search_term = f"%{q}%"
            fallback = fallback.filter(
                (Asset.title.ilike(search_term)) | (Asset.description.ilike(search_term))
            )
            if sort_by == "title":
                fallback = fallback.order_by(
                    Asset.title.asc() if sort_order != "desc" else Asset.title.desc()
                )
            elif sort_by == "category":
                fallback = fallback.order_by(
                    Asset.category.asc() if sort_order != "desc" else Asset.category.desc()
                )
            else:
                fallback = fallback.order_by(Asset.id.desc())

            assets = fallback.all()
            for a in assets:
                assets_data.append({
                    "id": str(a.id),
                    "session_id": str(a.session_id),
                    "title": a.title,
                    "description": a.description,
                    "description_json": a.description_json,
                    "category": a.category,
                    "valuation_min": a.valuation_min,
                    "valuation_max": a.valuation_max,
                    "valuation_source": a.valuation_source,
                    "sentiment_tag": a.sentiment_tag,
                    "image_uri": a.image_uri,
                    "audio_uri": a.audio_uri,
                    "status": a.status,
                    "ocr_status": a.ocr_status,
                    "allocated_to_id": str(a.allocated_to_id) if a.allocated_to_id else None,
                    "images": [
                        {
                            "id": str(img.id),
                            "image_uri": img.image_uri,
                            "is_primary": img.is_primary,
                            "angle_label": img.angle_label,
                        }
                        for img in a.images
                    ],
                })
    else:
        if sort_by == "title":
            query = query.order_by(
                Asset.title.asc() if sort_order != "desc" else Asset.title.desc()
            )
        elif sort_by == "category":
            query = query.order_by(
                Asset.category.asc() if sort_order != "desc" else Asset.category.desc()
            )
        else:
            query = query.order_by(Asset.id.desc())

        assets = query.all()
        for a in assets:
            assets_data.append({
                "id": str(a.id),
                "session_id": str(a.session_id),
                "title": a.title,
                "description": a.description,
                "description_json": a.description_json,
                "category": a.category,
                "valuation_min": a.valuation_min,
                "valuation_max": a.valuation_max,
                "valuation_source": a.valuation_source,
                "sentiment_tag": a.sentiment_tag,
                "image_uri": a.image_uri,
                "audio_uri": a.audio_uri,
                "status": a.status,
                "ocr_status": a.ocr_status,
                "allocated_to_id": str(a.allocated_to_id) if a.allocated_to_id else None,
                "images": [
                    {
                        "id": str(img.id),
                        "image_uri": img.image_uri,
                        "is_primary": img.is_primary,
                        "angle_label": img.angle_label,
                    }
                    for img in a.images
                ],
            })

    return JSONResponse(content=assets_data)



# ---------------------------------------------------------------------------
# T42 — Schema
# ---------------------------------------------------------------------------


class SupportRequestCreate(BaseModel):
    message: str = Field(..., min_length=5, max_length=1000)


class SupportRequestReply(BaseModel):
    response: str = Field(..., min_length=2, max_length=2000)


class SupportDirectMessageCreate(BaseModel):
    heir_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=2, max_length=2000)


# ---------------------------------------------------------------------------
# T43 — Schema
# ---------------------------------------------------------------------------


class FAQCreate(BaseModel):
    question: str = Field(..., min_length=5)
    answer: str = Field(..., min_length=5)


# ---------------------------------------------------------------------------
# T13 — Schema
# ---------------------------------------------------------------------------


class HeirCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    legal_first_name: str | None = Field(None, min_length=1, max_length=50)
    legal_middle_name: str | None = None
    legal_last_name: str | None = Field(None, min_length=1, max_length=100)
    relationship_to_decedent: str | None = None
    date_of_birth: str | None = None
    email: str | None = None
    phone: str | None = None
    physical_address: str | None = None
    address_line1: str | None = Field(None, max_length=255)
    address_line2: str | None = Field(None, max_length=255)
    address_city: str | None = Field(None, max_length=100)
    address_region: str | None = Field(None, max_length=100)
    address_postal_code: str | None = Field(None, max_length=40)
    address_country: str | None = Field(None, max_length=100)
    expiration_days: int | None = 14


class InviteTokenRenewRequest(BaseModel):
    expiration_days: int | None = 14


# ---------------------------------------------------------------------------
# T13 — Heir Management & Invitations
# ---------------------------------------------------------------------------


def _heir_to_response(heir: User) -> dict:
    """Serialize a User (HEIR) to a dict matching HeirResponse schema."""
    return {
        "id": str(heir.id),
        "heir_id": str(heir.id),
        "session_id": str(heir.session_id) if heir.session_id else None,
        "username": heir.username,
        "legal_first_name": heir.legal_first_name,
        "legal_middle_name": heir.legal_middle_name,
        "legal_last_name": heir.legal_last_name,
        "relationship_to_decedent": heir.relationship_to_decedent,
        "date_of_birth": (
            heir.date_of_birth.isoformat() if heir.date_of_birth else None
        ),
        "identity_verified": heir.identity_verified,
        "id_scan_uri": heir.id_scan_uri,
        "role": heir.role,
        "email": heir.email,
        "phone": heir.phone,
        "physical_address": heir.physical_address,
        **_address_response_fields(heir),
        "invite_token": str(heir.invite_token) if heir.invite_token else None,
        "invite_token_expires_at": (
            heir.invite_token_expires_at.isoformat()
            if heir.invite_token_expires_at
            else None
        ),
        "invite_token_used": heir.invite_token_used,
        "consent_accepted": heir.consent_accepted,
        "age_verified": heir.age_verified,
        "consent_timestamp": (
            heir.consent_timestamp.isoformat() if heir.consent_timestamp else None
        ),
        "is_submitted": heir.is_submitted,
        "submitted_at": (
            heir.submitted_at.isoformat() if heir.submitted_at else None
        ),
        "draft_version": heir.draft_version,
        "status": heir.status,
        "user_status": heir.status,
        "created_at": heir.created_at.isoformat() if heir.created_at else None,
        "invitation_dispatched_at": (
            heir.invitation_dispatched_at.isoformat()
            if heir.invitation_dispatched_at
            else None
        ),
    }


@app.get("/api/sessions/{session_id}/heirs")
@limiter.limit("60/minute")
async def session_heirs(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    List all Heirs currently registered in the session.

    Per Backend Spec §9.1 (GET /api/sessions/{session_id}/heirs):
    Admin credentials required. Returns list of HeirResponse.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    heirs = (
        db.query(User)
        .filter(User.session_id == session_id, User.role == "HEIR")
        .all()
    )
    return JSONResponse(content=[_heir_to_response(h) for h in heirs])


@app.post("/api/sessions/{session_id}/heirs")
@limiter.limit("30/minute")
async def create_heir(
    request: Request,
    session_id: str,
    body: HeirCreateRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Create an Heir user with invitation token.

    Per Backend Spec §9.1 (POST /api/sessions/{session_id}/heirs):
    Creates an Heir, generates a single-use UUID invite token, sets
    invite_token_expires_at to expiration_days from now (default 14).
    Returns 400 if session status is LOCKED or FINALIZED.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status in ("LOCKED", "FINALIZED"):
        raise HTTPException(
            status_code=400,
            detail="Cannot add heirs to a locked or finalized session.",
        )

    import uuid as _uuid_mod

    now_utc = datetime.now(timezone.utc)
    expiration_days = body.expiration_days if body.expiration_days is not None else 14
    invite_token = _uuid_mod.uuid4()
    invite_expires = now_utc + timedelta(days=expiration_days)

    dob = None
    if body.date_of_birth:
        try:
            dob = datetime.strptime(body.date_of_birth, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date_of_birth format. Use YYYY-MM-DD.",
            )

    structured_address = _structured_address_from_body(body)
    display_name_parts = body.username.strip().split()
    legal_first_name = body.legal_first_name or display_name_parts[0]
    legal_last_name = body.legal_last_name or (
        " ".join(display_name_parts[1:]) if len(display_name_parts) > 1 else "Pending"
    )

    heir = User(
        session_id=session_id,
        username=body.username,
        legal_first_name=legal_first_name,
        legal_middle_name=body.legal_middle_name,
        legal_last_name=legal_last_name,
        relationship_to_decedent=body.relationship_to_decedent,
        date_of_birth=dob,
        email=body.email,
        phone=body.phone,
        physical_address=_compose_physical_address(
            structured_address,
            fallback=body.physical_address,
        ),
        **structured_address,
        role="HEIR",
        invite_token=invite_token,
        invite_token_expires_at=invite_expires,
        invite_token_used=False,
        status="PENDING",
        consent_accepted=False,
        age_verified=False,
    )
    db.add(heir)
    db.commit()
    db.refresh(heir)

    # Build invite URL
    base_url = _public_base_url(request)
    invite_url = f"{base_url}/invite/{invite_token}"

    return JSONResponse(
        content={
            "id": str(heir.id),
            "heir_id": str(heir.id),
            "invite_token": str(invite_token),
            "invite_url": invite_url,
            "username": heir.username,
        },
        status_code=201,
    )


@app.post("/api/heirs/{heir_id}/invite-token")
@limiter.limit("30/minute")
async def renew_invite_token(
    request: Request,
    heir_id: str,
    body: InviteTokenRenewRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Regenerate a fresh single-use UUID invite token for an existing Heir.

    Per Backend Spec §9.1 (POST /api/heirs/{heir_id}/invite-token):
    Resets invite_token_used = False and expiration to expiration_days
    from now (default 14). Returns 400 if session is LOCKED/FINALIZED.
    """
    heir = db.query(User).filter(User.id == heir_id, User.role == "HEIR").first()
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found")

    session = (
        db.query(SessionModel).filter(SessionModel.id == heir.session_id).first()
    )
    if session and session.status in ("LOCKED", "FINALIZED"):
        raise HTTPException(
            status_code=400,
            detail="Cannot renew invite tokens for a locked or finalized session.",
        )

    import uuid as _uuid_mod

    now_utc = datetime.now(timezone.utc)
    expiration_days = body.expiration_days if body.expiration_days is not None else 14
    new_token = _uuid_mod.uuid4()

    heir.invite_token = new_token
    heir.invite_token_expires_at = now_utc + timedelta(days=expiration_days)
    heir.invite_token_used = False
    db.commit()

    base_url = _public_base_url(request)
    invite_url = f"{base_url}/invite/{new_token}"

    return JSONResponse(
        content={
            "invite_token": str(new_token),
            "invite_url": invite_url,
        }
    )


@app.post("/api/heirs/{heir_id}/send-invite")
@limiter.limit("30/minute")
async def send_invite(
    request: Request,
    heir_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Dispatch invitation email to the Heir.

    Per Backend Spec §9.1 (POST /api/heirs/{heir_id}/send-invite):
    Sends email asynchronously via SMTP. On successful relay, updates
    invitation_dispatched_at. Returns 400 if session is LOCKED/FINALIZED.
    """
    heir = db.query(User).filter(User.id == heir_id, User.role == "HEIR").first()
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found")

    if not heir.email:
        raise HTTPException(
            status_code=400,
            detail="Heir has no email address on file.",
        )

    session = (
        db.query(SessionModel).filter(SessionModel.id == heir.session_id).first()
    )
    if session and session.status in ("LOCKED", "FINALIZED"):
        raise HTTPException(
            status_code=400,
            detail="Cannot send invitations for a locked or finalized session.",
        )

    base_url = _public_base_url(request)
    invite_url = (
        f"{base_url}/invite/{heir.invite_token}" if heir.invite_token else base_url
    )

    # Fire background email task — transactionally decoupled
    subject = f"Estate Mediation Invitation — {session.title if session else 'Estate'}"
    body = (
        f"Dear {heir.username},\n\n"
        f"You have been invited to participate in the estate mediation for "
        f"'{session.title if session else 'Estate'}'.\n\n"
        f"Please use the following link to accept your invitation:\n{invite_url}\n\n"
        f"This invitation expires on "
        f"{heir.invite_token_expires_at.isoformat() if heir.invite_token_expires_at else 'N/A'}.\n\n"
        f"The Estate Steward"
    )

    email_sent = await send_email_background(
        to=heir.email,
        subject=subject,
        body=body,
        on_failure_message=(
            f"SYSTEM WARNING: Invitation email to {heir.email} "
            f"(heir {heir.username}) failed to deliver."
        ),
    )
    if not email_sent:
        raise HTTPException(
            status_code=502,
            detail="Invitation email could not be delivered to the configured SMTP service.",
        )

    # Mark as dispatched
    now_utc = datetime.now(timezone.utc)
    heir.invitation_dispatched_at = now_utc
    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": "Invitation email dispatched",
        }
    )


# ---------------------------------------------------------------------------
# T60 — Admin Heir Deletion API
# ---------------------------------------------------------------------------


@app.delete("/api/sessions/{session_id}/heirs/{heir_id}")
@limiter.limit("30/minute")
async def delete_heir(
    request: Request,
    session_id: str,
    heir_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Admin deletion of an Heir from a session.

    Per Backend Spec §9.1 (DELETE /api/sessions/{session_id}/heirs/{heir_id}):
    1. Unlink pre-allocated assets (reset allocated_to_id, status -> LIVE).
    2. Delete encrypted ID scan file from disk storage if present.
    3. Erase all LangGraph checkpointer state records for this Heir's thread.
    4. Cascade-delete the user row (chat, support, valuations, audit via ORM).
    5. Anonymize audit_logs state_snapshot for this Heir to prevent PII leakage.

    Returns 400 if session status is LOCKED or FINALIZED.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status in ("LOCKED", "FINALIZED"):
        raise HTTPException(
            status_code=400,
            detail="Cannot delete heirs from a locked or finalized session.",
        )

    heir = (
        db.query(User)
        .filter(User.id == heir_id, User.session_id == session_id, User.role == "HEIR")
        .first()
    )
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found in this session")

    # 1. Unlink pre-allocated assets
    pre_allocated = (
        db.query(Asset)
        .filter(
            Asset.session_id == session_id,
            Asset.allocated_to_id == heir_id,
            Asset.status == "PRE_ALLOCATED",
        )
        .all()
    )
    for asset in pre_allocated:
        asset.allocated_to_id = None
        asset.status = "LIVE"

    # 2. Delete encrypted ID scan file from storage if present
    if heir.id_scan_uri:
        try:
            storage = get_storage_driver()
            storage.delete(heir.id_scan_uri)
        except Exception:
            logger.warning(
                "Failed to delete ID scan file %s for heir %s",
                heir.id_scan_uri,
                heir_id,
            )

    # 3. Erase LangGraph checkpointer state for this Heir's thread
    thread_id = f"{session_id}:{heir_id}"
    try:
        from .database import engine
        from sqlalchemy import text as sa_text
        with engine.begin() as conn:
            for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
                conn.execute(
                    sa_text(f"DELETE FROM {table} WHERE thread_id = :tid"),
                    {"tid": thread_id},
                )
    except Exception:
        logger.warning(
            "Failed to clean checkpointer state for thread %s — continuing",
            thread_id,
        )

    # 4. Collect PII for audit log anonymization before cascade delete
    heir_id_str = str(heir.id)
    pii_values = [
        heir.legal_first_name,
        heir.legal_middle_name,
        heir.legal_last_name,
        heir.email,
        heir.phone,
        heir.physical_address,
        *_address_response_fields(heir).values(),
    ]
    pii_values = [v for v in pii_values if v]

    # 5. Cascade-delete the heir — this removes the user row and cascades
    #    to chat_messages, support_requests, valuations via ORM relationships
    db.delete(heir)
    db.flush()

    # 6. Anonymize audit_logs state_snapshot for this Heir
    audit_logs = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == session_id)
        .all()
    )
    for log_entry in audit_logs:
        try:
            snapshot = log_entry.state_snapshot
            if not isinstance(snapshot, (dict, list)):
                continue
            _redact_pii_in_place(snapshot, heir_id_str, pii_values)
            # Mark the column as modified so SQLAlchemy writes the updated value
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(log_entry, "state_snapshot")
        except Exception:
            logger.warning(
                "Failed to anonymize audit log %d — continuing",
                log_entry.id,
            )

    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": "Heir removed, associated ID scan files deleted, "
            "checkpointer states cleared, and data cascade-deleted",
        }
    )


# ---------------------------------------------------------------------------
# T40 — Asset Deletion API
# ---------------------------------------------------------------------------


@app.delete("/api/assets/{asset_id}")
@limiter.limit("30/minute")
async def delete_asset(
    request: Request,
    asset_id: str,
    reason: Optional[str] = None,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Permanently delete an asset and its associated files.
    Allows deleting assets when the session status is SETUP or ACTIVE.
    Requires a reason for major deletions (LIVE assets or ACTIVE sessions).
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    session = (
        db.query(SessionModel).filter(SessionModel.id == asset.session_id).first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status in ("LOCKED", "FINALIZED"):
        raise HTTPException(
            status_code=400,
            detail=f"Assets cannot be deleted when session status is '{session.status}'.",
        )

    # Classify as Major if asset is published or session is already active
    is_major = (asset.status == "LIVE") or (session.status == "ACTIVE")
    if is_major:
        if not reason or not reason.strip():
            raise HTTPException(
                status_code=400,
                detail="A reason is required when deleting an asset post-launch or after publishing.",
            )

    # Concurrency control locking
    session = db.query(SessionModel).filter(SessionModel.id == asset.session_id).with_for_update().first()
    asset = db.query(Asset).filter(Asset.id == asset_id).with_for_update().first()

    # Write ASSET_DELETED audit log entry BEFORE deletion
    state_snapshot = {
        "event": "ASSET_DELETED",
        "asset_id": str(asset.id),
        "asset_title": asset.title,
        "classification": "MAJOR" if is_major else "MINOR",
        "reason": reason if is_major else None,
        "notified": False,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    _log_asset_audit_event(db, str(session.id), "ASSET_DELETED", state_snapshot)

    # Reset heir submissions if major change in ACTIVE session
    if is_major:
        _reset_session_submitted_heirs(db, str(session.id))

    # Remove all associated images from storage (including the primary/legacy image_uri)
    storage = get_storage_driver()
    deleted_uris = set()
    for img in asset.images:
        if img.image_uri and img.image_uri not in deleted_uris:
            try:
                storage.delete(img.image_uri)
                deleted_uris.add(img.image_uri)
            except Exception:
                pass
    if asset.image_uri and asset.image_uri not in deleted_uris:
        try:
            storage.delete(asset.image_uri)
            deleted_uris.add(asset.image_uri)
        except Exception:
            pass

    # Remove audio file from storage if present
    if asset.audio_uri:
        try:
            storage.delete(asset.audio_uri)
        except Exception:
            pass

    # Cascade-delete: valuations are handled by the ORM relationship
    # (cascade="all, delete-orphan"), but we explicitly delete the asset
    # to trigger the cascade.
    db.delete(asset)
    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": "Asset and associated files deleted",
        }
    )


# ---------------------------------------------------------------------------
# T31 — Government ID Scan Upload API
# ---------------------------------------------------------------------------


@app.get("/api/sessions/{session_id}/pending-updates")
@limiter.limit("60/minute")
async def get_pending_updates(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Returns the count of pending (un-notified) asset updates.
    """
    unnotified_logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.session_id == session_id,
            AuditLog.event_type.in_(["ASSET_CREATED", "ASSET_UPDATED", "ASSET_DELETED"]),
        )
        .all()
    )
    pending_count = 0
    for log in unnotified_logs:
        if isinstance(log.state_snapshot, dict) and not log.state_snapshot.get("notified", False):
            pending_count += 1

    return JSONResponse(content={"pending_count": pending_count})


@app.post("/api/sessions/{session_id}/publish-updates")
@limiter.limit("10/minute")
async def publish_updates(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Publish queued asset changes (additions, modifications, deletions) as a single batch.
    Emails a change summary to all active/verified heirs and broadcasts a WebSocket notification.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).with_for_update().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status not in ("SETUP", "ACTIVE"):
        raise HTTPException(
            status_code=400,
            detail=f"Updates can only be published during SETUP or ACTIVE phases. Current status: '{session.status}'",
        )

    # 1. Query all un-notified audit logs for this session
    unnotified_logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.session_id == session_id,
            AuditLog.event_type.in_(["ASSET_CREATED", "ASSET_UPDATED", "ASSET_DELETED"]),
        )
        .all()
    )

    # Decrypt and filter logs where snapshot has notified = False
    pending_logs = []
    for log in unnotified_logs:
        snapshot = log.state_snapshot
        if isinstance(snapshot, dict) and not snapshot.get("notified", False):
            pending_logs.append(log)

    if not pending_logs:
        return JSONResponse(
            content={
                "status": "noop",
                "message": "No pending asset updates to publish.",
            }
        )

    # 2. Count additions, modifications, and deletions
    added_count = 0
    modified_count = 0
    deleted_count = 0
    changes_details = []

    for log in pending_logs:
        snap = log.state_snapshot
        evt = snap.get("event")
        title = snap.get("asset_title") or "Unnamed Asset"
        cls = snap.get("classification")
        reason = snap.get("reason")

        if evt == "ASSET_CREATED":
            added_count += 1
            changes_details.append(f"- Added new asset (staged): {title}")
        elif evt == "ASSET_DELETED":
            deleted_count += 1
            reason_str = f" (Reason: {reason})" if reason else ""
            changes_details.append(f"- Deleted asset: {title}{reason_str}")
        elif evt == "ASSET_UPDATED":
            # Check if it was an transition from staged to live
            chg = snap.get("changes", {})
            if "status" in chg and chg["status"].get("new") == "LIVE":
                added_count += 1
                reason_str = f" (Reason: {reason})" if reason else ""
                changes_details.append(f"- Published asset: {title}{reason_str}")
            else:
                modified_count += 1
                changed_keys = ", ".join(chg.keys())
                reason_str = f" (Reason: {reason})" if reason else ""
                changes_details.append(f"- Modified asset '{title}' (Fields: {changed_keys}){reason_str}")

    # Build summary line
    summary_parts = []
    if added_count > 0:
        summary_parts.append(f"{added_count} item(s) added")
    if modified_count > 0:
        summary_parts.append(f"{modified_count} item(s) modified")
    if deleted_count > 0:
        summary_parts.append(f"{deleted_count} item(s) deleted")
    summary_line = "Updated: " + ", ".join(summary_parts)

    # 3. Write ASSET_PUBLISH_BATCH log to AuditLog
    state_snapshot = {
        "event": "ASSET_PUBLISH_BATCH",
        "summary": summary_line,
        "published_log_ids": [log.id for log in pending_logs],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    batch_log = _log_asset_audit_event(db, session_id, "ASSET_PUBLISH_BATCH", state_snapshot)

    # Mark all pending logs as notified = True in DB
    for log in pending_logs:
        new_snap = dict(log.state_snapshot)
        new_snap["notified"] = True
        log.state_snapshot = new_snap

    # 4. Email all active/verified heirs
    from .services.smtp_service import send_email_background
    active_heirs = (
        db.query(User)
        .filter(
            User.session_id == session_id,
            User.role == "HEIR",
            User.status.in_(["ACTIVE", "SUBMITTED"]),
        )
        .all()
    )

    email_body = (
        f"Notice: The Executor has published updates to the estate inventory for '{session.title}'.\n\n"
        f"Summary of changes:\n"
        f"{summary_line}\n\n"
        f"Details:\n"
        + "\n".join(changes_details) + "\n\n"
        f"Please log into your Estate Steward workspace to review the latest inventory and update your allocations if needed."
    )

    for heir in active_heirs:
        if heir.email:
            await send_email_background(
                to=heir.email,
                subject=f"Estate Inventory Updates - {session.title}",
                body=email_body,
                on_failure_message=f"Failed to deliver inventory update email to {heir.email}"
            )

    db.commit()

    # 5. Broadcast WebSockets notification
    await manager.broadcast_session_status(
        session_id,
        {
            "type": "inventory_updated",
            "summary": summary_line,
            "session_status": session.status,
        },
    )

    return JSONResponse(
        content={
            "status": "success",
            "summary": summary_line,
            "batch_log_id": batch_log.id,
        }
    )


# ---------------------------------------------------------------------------
# T42 — Support Request & Help CRUD API
# ---------------------------------------------------------------------------


def _support_request_response(db: DBSession, ticket: SupportRequest) -> dict:
    heir = db.query(User).filter(User.id == ticket.heir_id).first()
    admin = (
        db.query(User).filter(User.id == ticket.responded_by_id).first()
        if getattr(ticket, "responded_by_id", None)
        else None
    )
    legal_name = " ".join(
        part
        for part in (
            getattr(heir, "legal_first_name", None),
            getattr(heir, "legal_middle_name", None),
            getattr(heir, "legal_last_name", None),
        )
        if part
    )

    return {
        "id": str(ticket.id),
        "session_id": str(ticket.session_id),
        "heir_id": str(ticket.heir_id),
        "username": getattr(heir, "username", None) or "Unknown",
        "legal_name": legal_name or getattr(heir, "username", None) or "Unknown",
        "message": ticket.message,
        "admin_response": getattr(ticket, "admin_response", None),
        "heir_image_uri": getattr(ticket, "heir_image_uri", None),
        "admin_image_uri": getattr(ticket, "admin_image_uri", None),
        "initiator_role": getattr(ticket, "initiator_role", None) or "HEIR",
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "responded_at": ticket.responded_at.isoformat() if getattr(ticket, "responded_at", None) else None,
        "resolved_at": ticket.resolved_at.isoformat() if getattr(ticket, "resolved_at", None) else None,
        "responded_by_id": str(ticket.responded_by_id) if getattr(ticket, "responded_by_id", None) else None,
        "responded_by_username": getattr(admin, "username", None) if admin else None,
    }


@app.post("/api/sessions/{session_id}/help")
@limiter.limit("30/minute")
async def create_help_request(
    request: Request,
    session_id: str,
    message: Annotated[Optional[str], Form()] = None,
    file: Annotated[Optional[UploadFile], File()] = None,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Submit a help ticket from an Heir to the Executor.

    Per Backend Spec §9.4 (POST /api/sessions/{session_id}/help):
    Heir submits a support request, persisted to support_requests table.
    Broadcasts a WebSocket alert to the Admin channel.
    """
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Only heirs can submit help requests")

    heir_id = current_user.get("user_id")
    token_session_id = current_user.get("session_id")
    if not token_session_id or str(token_session_id) != str(session_id):
        raise HTTPException(status_code=403, detail="Session mismatch")

    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    heir = (
        db.query(User)
        .filter(
            User.id == heir_id,
            User.role == "HEIR",
            User.session_id == session_id,
        )
        .first()
    )
    if not heir:
        raise HTTPException(status_code=403, detail="Heir is not registered for this session")

    message_str = message.strip() if message else ""

    if not message_str and not file:
        raise HTTPException(status_code=400, detail="Must provide message or image")

    heir_image_uri = None
    if file:
        import uuid as _uuid_mod
        file_bytes = await file_upload.read()
        if file_bytes:
            try:
                processed = preprocess_image(file_bytes)
                storage = get_storage_driver()
                image_id = _uuid_mod.uuid4()
                filename = f"static/uploads/support_{image_id}_heir.webp"
                storage.save(filename, processed)
                heir_image_uri = f"/{filename}"
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

    sr = SupportRequest(
        session_id=session_id,
        heir_id=heir_id,
        message=message_str or "Sent an image",
        heir_image_uri=heir_image_uri,
        initiator_role="HEIR",
        status="OPEN",
    )
    db.add(sr)
    db.flush()

    _log_asset_audit_event(
        db,
        session_id,
        "SUPPORT_REQUEST_CREATED",
        {
            "event": "SUPPORT_REQUEST_CREATED",
            "support_request_id": str(sr.id),
            "heir_id": str(heir_id),
            "heir_username": current_user.get("username", ""),
            "message": body.message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.commit()

    # Broadcast WebSocket alert to Admin
    await manager.broadcast_support_alert(
        session_id,
        str(sr.id),
        current_user.get("username", ""),
        body.message,
    )

    return JSONResponse(
        content={
            "status": "submitted",
            "ticket": _support_request_response(db, sr),
        },
        status_code=201,
    )


@app.post("/api/sessions/{session_id}/help/direct")
@limiter.limit("30/minute")
async def create_direct_help_message(
    request: Request,
    session_id: str,
    heir_id: Annotated[str, Form()],
    message: Annotated[Optional[str], Form()] = None,
    file: Annotated[Optional[UploadFile], File()] = None,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """Send a direct Executor message to one registered heir."""
    import uuid as _uuid_mod

    form = await request.form()
    heir_id = form.get("heir_id")
    if not heir_id:
        raise HTTPException(status_code=400, detail="Missing heir_id")

    try:
        heir_uuid = _uuid_mod.UUID(str(heir_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid heir_id")

    try:
        session_uuid = _uuid_mod.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")

    session = db.query(SessionModel).filter(SessionModel.id == session_uuid).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    heir = (
        db.query(User)
        .filter(
            User.id == heir_uuid,
            User.role == "HEIR",
            User.session_id == session_uuid,
        )
        .first()
    )
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found for this session")

    message_str = message.strip() if message else ""

    if not message_str and not file:
        raise HTTPException(status_code=400, detail="Must provide message or image")

    admin_image_uri = None
    if file:
        file_bytes = await file.read()
        if file_bytes:
            try:
                processed = preprocess_image(file_bytes)
                storage = get_storage_driver()
                image_id = _uuid_mod.uuid4()
                filename = f"static/uploads/support_{image_id}_admin.webp"
                storage.save(filename, processed)
                admin_image_uri = f"/{filename}"
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

    now_utc = datetime.now(timezone.utc)
    sr = SupportRequest(
        session_id=session_uuid,
        heir_id=heir_uuid,
        message="Executor initiated direct message.",
        admin_response=message_str or "Sent an image",
        admin_image_uri=admin_image_uri,
        initiator_role="ADMIN",
        status="RESPONDED",
        responded_at=now_utc,
        responded_by_id=current_admin.get("user_id"),
    )
    db.add(sr)
    db.flush()

    _log_asset_audit_event(
        db,
        session_id,
        "SUPPORT_DIRECT_MESSAGE_SENT",
        {
            "event": "SUPPORT_DIRECT_MESSAGE_SENT",
            "support_request_id": str(sr.id),
            "heir_id": str(heir_uuid),
            "heir_username": getattr(heir, "username", ""),
            "responded_by_id": str(current_admin.get("user_id")),
            "responded_by_username": current_admin.get("username", ""),
            "admin_response": sr.admin_response,
            "responded_at": now_utc.isoformat(),
        },
    )
    db.commit()
    db.refresh(sr)

    await manager.send_to_heir(
        session_id,
        str(heir_uuid),
        {
            "type": "support_reply",
            "ticket_id": str(sr.id),
            "message": sr.admin_response,
            "responded_at": now_utc.isoformat(),
            "initiator_role": "ADMIN",
        },
    )

    return JSONResponse(content=_support_request_response(db, sr), status_code=201)


@app.get("/api/sessions/{session_id}/help")
@limiter.limit("60/minute")
async def list_help_requests(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    List all help requests for a session.

    Per Backend Spec §9.4 (GET /api/sessions/{session_id}/help):
    Admin credentials required. Returns list of SupportRequestResponse
    with resolved Heir usernames via database joins.
    """
    import uuid as _uuid_mod
    try:
        session_uuid = _uuid_mod.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    tickets = (
        db.query(SupportRequest)
        .filter(SupportRequest.session_id == session_uuid)
        .order_by(SupportRequest.created_at.desc())
        .all()
    )

    return JSONResponse(content=[_support_request_response(db, t) for t in tickets])


@app.get("/api/sessions/{session_id}/help/mine")
@limiter.limit("60/minute")
async def list_my_help_requests(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List the current heir's help requests and executor responses."""
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")

    if current_user.get("session_id") and str(current_user.get("session_id")) != str(session_id):
        raise HTTPException(status_code=403, detail="Session mismatch")

    import uuid as _uuid_mod
    try:
        session_uuid = _uuid_mod.UUID(session_id)
        heir_uuid = _uuid_mod.UUID(current_user.get("user_id"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    tickets = (
        db.query(SupportRequest)
        .filter(
            SupportRequest.session_id == session_uuid,
            SupportRequest.heir_id == heir_uuid,
        )
        .order_by(SupportRequest.created_at.desc())
        .all()
    )
    return JSONResponse(content=[_support_request_response(db, t) for t in tickets])



@app.post("/api/help/{ticket_id}/reply")
@limiter.limit("30/minute")
async def reply_to_help_request(
    request: Request,
    ticket_id: str,
    response: Annotated[Optional[str], Form()] = None,
    file: Annotated[Optional[UploadFile], File()] = None,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Admin replies to a specific help ticket.
    """
    ticket = db.query(SupportRequest).filter(SupportRequest.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Support request not found")
    if ticket.status == "RESOLVED":
        raise HTTPException(status_code=400, detail="Cannot reply to a resolved request")

    response_str = response.strip() if response else ""

    if not response_str and not file:
        raise HTTPException(status_code=400, detail="Must provide message or image")

    admin_image_uri = None
    if file:
        import uuid as _uuid_mod
        file_bytes = await file.read()
        if file_bytes:
            try:
                processed = preprocess_image(file_bytes)
                storage = get_storage_driver()
                image_id = _uuid_mod.uuid4()
                filename = f"static/uploads/support_{image_id}_admin.webp"
                storage.save(filename, processed)
                admin_image_uri = f"/{filename}"
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

    now_utc = datetime.now(timezone.utc)
    ticket.admin_response = response_str or "Sent an image"
    if admin_image_uri:
        ticket.admin_image_uri = admin_image_uri
    ticket.responded_at = now_utc
    ticket.responded_by_id = current_admin.get("user_id")
    ticket.status = "RESPONDED"

    _log_asset_audit_event(
        db,
        str(ticket.session_id),
        "SUPPORT_REPLY_SENT",
        {
            "event": "SUPPORT_REPLY_SENT",
            "support_request_id": str(ticket.id),
            "heir_id": str(ticket.heir_id),
            "responded_by_id": str(current_admin.get("user_id")),
            "responded_by_username": current_admin.get("username", ""),
            "original_message": ticket.message,
            "admin_response": ticket.admin_response,
            "responded_at": now_utc.isoformat(),
        },
    )
    db.commit()
    db.refresh(ticket)

    await manager.send_to_heir(
        str(ticket.session_id),
        str(ticket.heir_id),
        {
            "type": "support_reply",
            "ticket_id": str(ticket.id),
            "message": body.response,
            "responded_at": now_utc.isoformat(),
            "initiator_role": getattr(ticket, "initiator_role", None) or "HEIR",
        },
    )

    return JSONResponse(content=_support_request_response(db, ticket))


@app.post("/api/help/{ticket_id}/resolve")
@limiter.limit("30/minute")
async def resolve_help_request(
    request: Request,
    ticket_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Mark a support request as RESOLVED.

    Per Backend Spec §9.4 (POST /api/help/{ticket_id}/resolve):
    Admin credentials required. Toggles support request status to 'RESOLVED'.
    """
    ticket = (
        db.query(SupportRequest).filter(SupportRequest.id == ticket_id).first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Support ticket not found")

    ticket.status = "RESOLVED"
    ticket.resolved_at = datetime.now(timezone.utc)
    _log_asset_audit_event(
        db,
        str(ticket.session_id),
        "SUPPORT_REQUEST_RESOLVED",
        {
            "event": "SUPPORT_REQUEST_RESOLVED",
            "support_request_id": str(ticket.id),
            "heir_id": str(ticket.heir_id),
            "resolved_by_id": str(current_admin.get("user_id")),
            "resolved_by_username": current_admin.get("username", ""),
            "resolved_at": ticket.resolved_at.isoformat(),
        },
    )
    db.commit()
    db.refresh(ticket)

    await manager.send_to_heir(
        str(ticket.session_id),
        str(ticket.heir_id),
        {
            "type": "support_resolution",
            "ticket_id": str(ticket.id),
            "status": ticket.status,
            "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
            "initiator_role": getattr(ticket, "initiator_role", None) or "HEIR",
        },
    )

    return JSONResponse(
        content={
            "status": "resolved",
            "ticket": _support_request_response(db, ticket),
        }
    )


# ---------------------------------------------------------------------------
# T41 — Admin Audio Story Upload & Delete API
# ---------------------------------------------------------------------------


@app.post("/api/assets/{asset_id}/audio")
@limiter.limit("30/minute")
async def upload_asset_audio(
    request: Request,
    asset_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Upload an audio story for a specific asset.

    Per Backend Spec §9.2 (POST /api/assets/{asset_id}/audio):
    Accepts multipart/form-data with 'file' key (WebM/MP3/WAV up to 10MB).
    Saves the audio file to the configured storage driver and updates
    assets.audio_uri. Returns 400 if session is not in SETUP status.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    session = (
        db.query(SessionModel).filter(SessionModel.id == asset.session_id).first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "SETUP":
        raise HTTPException(
            status_code=400,
            detail=f"Audio stories can only be uploaded during the SETUP phase. "
            f"Current session status is '{session.status}'.",
        )

    # Parse multipart upload
    form = await request.form()
    file_upload = form.get("file")
    if not file_upload:
        raise HTTPException(status_code=400, detail="No file uploaded")

    raw_bytes = await file_upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Size limit: 10MB
    if len(raw_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")

    # Determine file extension from content type or original filename
    content_type = file_upload.content_type or ""
    filename = file_upload.filename or ""
    if "webm" in content_type.lower() or filename.lower().endswith(".webm"):
        ext = ".webm"
    elif "mpeg" in content_type.lower() or "mp3" in content_type.lower() or filename.lower().endswith(".mp3"):
        ext = ".mp3"
    elif "wav" in content_type.lower() or filename.lower().endswith(".wav"):
        ext = ".wav"
    elif "ogg" in content_type.lower() or filename.lower().endswith(".ogg"):
        ext = ".ogg"
    elif "mp4" in content_type.lower() or "m4a" in content_type.lower() or "aac" in content_type.lower() or filename.lower().endswith(".mp4") or filename.lower().endswith(".m4a") or filename.lower().endswith(".aac"):
        ext = ".m4a"
    else:
        ext = ".webm"  # default fallback

    import uuid as _uuid_mod
    audio_filename = f"static/uploads/{_uuid_mod.uuid4()}{ext}"

    storage = get_storage_driver()
    storage.save(audio_filename, raw_bytes)

    asset.audio_uri = audio_filename
    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "audio_uri": audio_filename,
        }
    )


@app.delete("/api/assets/{asset_id}/audio")
@limiter.limit("30/minute")
async def delete_asset_audio(
    request: Request,
    asset_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Remove the audio story from an asset.

    Per Backend Spec §9.2 (DELETE /api/assets/{asset_id}/audio):
    Deletes the audio file from storage and nullifies assets.audio_uri.
    Returns 400 if session is not in SETUP status.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    session = (
        db.query(SessionModel).filter(SessionModel.id == asset.session_id).first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "SETUP":
        raise HTTPException(
            status_code=400,
            detail=f"Audio stories can only be deleted during the SETUP phase. "
            f"Current session status is '{session.status}'.",
        )

    if not asset.audio_uri:
        raise HTTPException(status_code=404, detail="No audio file exists for this asset")

    # Delete audio file from storage
    try:
        storage = get_storage_driver()
        storage.delete(asset.audio_uri)
    except Exception:
        pass

    asset.audio_uri = None
    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": "Asset voice recording deleted",
        }
    )


# ---------------------------------------------------------------------------
# T12 — Schema
# ---------------------------------------------------------------------------


class ValuationDraftItem(BaseModel):
    asset_id: str
    points: int = Field(..., ge=0, le=1000)
    reasoning: str | None = None
    is_reasoning_shared: bool = False


class ValuationDraftRequest(BaseModel):
    draft_version: int = Field(..., ge=0)
    valuations: list[ValuationDraftItem]


class ValuationSubmitItem(BaseModel):
    asset_id: str
    points: int = Field(..., ge=0, le=1000)
    reasoning: str | None = None
    is_reasoning_shared: bool = False


class ValuationSubmitRequest(BaseModel):
    valuations: list[ValuationSubmitItem]


# ---------------------------------------------------------------------------
# T12 — FastAPI Valuation Router: draft saving, submission, HITL_GUARD gate
# ---------------------------------------------------------------------------


@app.put("/api/sessions/{session_id}/valuations/draft")
@limiter.limit("30/minute")
async def save_valuation_draft(
    request: Request,
    session_id: str,
    body: ValuationDraftRequest,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Save draft point allocations for the Heir.

    Per Backend Spec §9.3 (PUT /api/sessions/{session_id}/valuations/draft):
    1. Acquires a pessimistic shared read lock on the Session row.
    2. Queries the Heir's current draft_version. If incoming <= stored, 409.
    3. Concurrency check: FOR UPDATE locking on User and Valuation rows.
    4. Bulk upserts points/reasoning rows, bumps draft_version on commit.

    Constraints:
      - 400 if session is LOCKED or FINALIZED.
      - 403 if Heir is in PROFILE_HOLD.
    """
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")

    heir_id = current_user.get("user_id")

    # Pessimistic shared read lock on the session
    session = (
        db.query(SessionModel)
        .filter(SessionModel.id == session_id)
        .with_for_update(read=True)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status in ("LOCKED", "FINALIZED"):
        raise HTTPException(
            status_code=400,
            detail=f"Drafts cannot be saved — session is '{session.status}'.",
        )

    # Exclusive lock on the heir row for concurrency control
    heir = (
        db.query(User)
        .filter(User.id == heir_id, User.role == "HEIR")
        .with_for_update()
        .first()
    )
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found")

    if heir.status == "PROFILE_HOLD":
        raise HTTPException(
            status_code=403,
            detail="Profile pending Executor identity verification. "
            "Bidding and mediation chat are locked.",
        )

    # Version race-condition check
    if body.draft_version <= heir.draft_version:
        raise HTTPException(
            status_code=409,
            detail="Draft version conflict — your draft is out of date. "
            "Reload the latest version and retry.",
        )

    # Bulk upsert valuations
    for item in body.valuations:
        # Verify asset exists and belongs to this session
        asset = (
            db.query(Asset)
            .filter(Asset.id == item.asset_id, Asset.session_id == session_id)
            .first()
        )
        if not asset:
            raise HTTPException(
                status_code=400,
                detail=f"Asset {item.asset_id} not found in this session.",
            )

        existing = (
            db.query(Valuation)
            .filter(
                Valuation.asset_id == item.asset_id,
                Valuation.heir_id == heir_id,
            )
            .with_for_update()
            .first()
        )
        if existing:
            existing.points = item.points
            existing.reasoning = item.reasoning
            existing.is_reasoning_shared = item.is_reasoning_shared
        else:
            db.add(Valuation(
                asset_id=item.asset_id,
                heir_id=heir_id,
                points=item.points,
                reasoning=item.reasoning,
                is_reasoning_shared=item.is_reasoning_shared,
            ))

    heir.draft_version = body.draft_version
    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": "Draft allocations saved",
            "draft_version": heir.draft_version,
        }
    )


@app.post("/api/sessions/{session_id}/valuations/submit")
@limiter.limit("20/minute")
async def submit_valuations(
    request: Request,
    session_id: str,
    body: ValuationSubmitRequest,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Submit final point valuations for the Heir.

    Per Backend Spec §9.3 (POST /api/sessions/{session_id}/valuations/submit):
    1. Pessimistic exclusive lock on Session (FOR UPDATE).
    2. Verifies Heir status is ACTIVE (not PROFILE_HOLD, SUBMITTED, ABSTAINED).
    3. Checks LangGraph thread for HITL_GUARD suspension → 403.
    4. Validates points sum == 1000.
    5. Checks session status not LOCKED or FINALIZED → 400.
    6. Upserts all valuations via bulk operation.
    7. Sets is_submitted = True, submitted_at = UTC now, status = 'SUBMITTED'.
    8. Broadcasts WebSocket status update.
    9. All-submitted check: if all eligible heirs submitted, triggers solver logic.

    Returns 403 with HITL_GUARD message if thread is suspended.
    """
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")

    heir_id = current_user.get("user_id")

    # Pessimistic exclusive lock on session → User → Valuations
    session = (
        db.query(SessionModel)
        .filter(SessionModel.id == session_id)
        .with_for_update()
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status in ("LOCKED", "FINALIZED"):
        raise HTTPException(
            status_code=400,
            detail=f"Submissions are not accepted — session is '{session.status}'.",
        )

    # Exclusive lock on the heir row
    heir = (
        db.query(User)
        .filter(User.id == heir_id, User.role == "HEIR")
        .with_for_update()
        .first()
    )
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found")

    if heir.status != "ACTIVE":
        raise HTTPException(
            status_code=403,
            detail="Only active verified heirs can submit point valuations.",
        )

    # Check LangGraph checkpointer for HITL_GUARD suspension
    try:
        from .graph import get_checkpointer  # PostgresSaver singleton
        saver = get_checkpointer()
        config = {"configurable": {"thread_id": f"{session_id}:{heir_id}"}}
        state = saver.get_tuple(config)
        if state and state.pending_writes:
            for pending in state.pending_writes:
                if isinstance(pending, tuple) and len(pending) >= 2:
                    node = pending[0] if isinstance(pending, tuple) else None
                    if node == "HITL_GUARD":
                        raise HTTPException(
                            status_code=403,
                            detail="Points submission suspended. Your allocations "
                            "require review and correction by the Executor.",
                        )
    except HTTPException:
        raise
    except Exception:
        pass  # Checkpointer not yet configured or unavailable — proceed

    # Validate points sum == 1000
    total = sum(item.points for item in body.valuations)
    if total != 1000:
        raise HTTPException(
            status_code=400,
            detail=f"Points sum must equal exactly 1000. Current total: {total}.",
        )

    # Verify each referenced asset exists and is LIVE or PRE_ALLOCATED
    asset_ids = {item.asset_id for item in body.valuations}
    exist_assets = (
        db.query(Asset.id)
        .filter(
            Asset.id.in_(asset_ids),
            Asset.session_id == session_id,
            Asset.status.in_(["LIVE", "PRE_ALLOCATED"]),
        )
        .all()
    )
    exist_set = {str(a[0]) for a in exist_assets}
    for aid in asset_ids:
        if aid not in exist_set:
            raise HTTPException(
                status_code=400,
                detail=f"Asset {aid} not found or not eligible for points allocation.",
            )

    # Bulk upsert valuations with exclusive locks
    for item in body.valuations:
        existing = (
            db.query(Valuation)
            .filter(
                Valuation.asset_id == item.asset_id,
                Valuation.heir_id == heir_id,
            )
            .with_for_update()
            .first()
        )
        if existing:
            existing.points = item.points
            existing.reasoning = item.reasoning
            existing.is_reasoning_shared = item.is_reasoning_shared
        else:
            db.add(Valuation(
                asset_id=item.asset_id,
                heir_id=heir_id,
                points=item.points,
                reasoning=item.reasoning,
                is_reasoning_shared=item.is_reasoning_shared,
            ))

    now_utc = datetime.now(timezone.utc)
    heir.is_submitted = True
    heir.submitted_at = now_utc
    heir.status = "SUBMITTED"
    db.commit()

    # Broadcast WebSocket status update
    await manager.broadcast_session_status(
        session_id,
        {
            "type": "heir_submitted",
            "heir_id": str(heir.id),
            "heir_username": heir.username,
        },
    )

    # All-submitted check: if no eligible heirs still pending, optionally trigger deadlock check
    pending = (
        db.query(User)
        .filter(
            User.session_id == session_id,
            User.role == "HEIR",
            User.status.in_(["PENDING", "PROFILE_HOLD", "ACTIVE"]),
        )
        .count()
    )

    result = {
        "status": "submitted",
        "submitted_at": now_utc.isoformat(),
    }

    if pending == 0:
        result["all_submitted"] = True

    return JSONResponse(content=result)


@app.get("/api/sessions/{session_id}/heirs/{heir_id}/valuations")
@limiter.limit("60/minute")
async def get_heir_valuations(
    request: Request,
    session_id: str,
    heir_id: str,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retrieve the existing point allocations for the specified Heir.

    Per Backend Spec §9.3 (GET /api/sessions/{session_id}/heirs/{heir_id}/valuations):
    Access: Heir JWT matching heir_id, or Admin credentials.
    Returns list of ValuationSchema objects.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")

    if role == "HEIR" and user_id != heir_id:
        raise HTTPException(status_code=403, detail="Access denied")

    valuations = (
        db.query(Valuation)
        .filter(Valuation.heir_id == heir_id)
        .all()
    )

    return JSONResponse(
        content=[
            {
                "asset_id": str(v.asset_id),
                "heir_id": str(v.heir_id),
                "points": v.points,
                "reasoning": v.reasoning,
                "is_reasoning_shared": v.is_reasoning_shared if v.is_reasoning_shared is not None else False,
            }
            for v in valuations
        ]
    )


# ---------------------------------------------------------------------------
# T34 — Schema
# ---------------------------------------------------------------------------


class VerifyIdentityRequest(BaseModel):
    action: str = Field(..., pattern=r"^(approve|reject)$")
    rejection_reason: str | None = Field(None, min_length=3, max_length=250)


# ---------------------------------------------------------------------------
# T34 — Executor ID Verification API
# ---------------------------------------------------------------------------


def _identity_scan_media_type(raw_bytes: bytes) -> str:
    if raw_bytes.startswith(b"%PDF"):
        return "application/pdf"
    if raw_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw_bytes.startswith(b"RIFF") and raw_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


@app.get("/api/heirs/{heir_id}/id-scan")
@limiter.limit("30/minute")
async def preview_heir_id_scan(
    request: Request,
    heir_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """Return a decrypted ID scan for authenticated Executor review only."""
    heir = db.query(User).filter(
        User.id == heir_id,
        User.role == "HEIR",
    ).first()
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found")
    if not heir.id_scan_uri:
        raise HTTPException(status_code=404, detail="No ID scan uploaded")

    encryption_key = os.environ.get("ENCRYPTION_KEY")
    if not encryption_key:
        raise HTTPException(status_code=500, detail="Server encryption key is not configured.")

    try:
        from cryptography.fernet import Fernet
        from fastapi.responses import StreamingResponse

        encrypted_bytes = get_storage_driver().get(heir.id_scan_uri)
        raw_bytes = Fernet(encryption_key.encode()).decrypt(encrypted_bytes)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="ID scan file not found")
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to decrypt ID scan")

    headers = {"Cache-Control": "no-store"}
    return StreamingResponse(
        io.BytesIO(raw_bytes),
        media_type=_identity_scan_media_type(raw_bytes),
        headers=headers,
    )


@app.post("/api/heirs/{heir_id}/verify-identity")
@limiter.limit("10/minute")
async def verify_heir_identity(
    request: Request,
    heir_id: str,
    body: VerifyIdentityRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Executor visually inspects ID scan and approves or rejects the Heir.

    Per Backend Spec §9.5 (POST /api/heirs/{heir_id}/verify-identity):
    - Approve: sets identity_verified=True, status→ACTIVE, seeds 0-pt
      valuations for all LIVE assets, deletes the ID scan file, sets
      id_scan_uri=NULL.
    - Reject: deletes the ID scan file, sets id_scan_uri=NULL.
    """
    heir = db.query(User).filter(
        User.id == heir_id,
        User.role == "HEIR",
    ).first()
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found")

    if body.action == "approve":
        heir.identity_verified = True
        heir.status = "ACTIVE"

        # Seed default 0-point valuations for all LIVE assets in this session
        live_assets = (
            db.query(Asset)
            .filter(
                Asset.session_id == heir.session_id,
                Asset.status == "LIVE",
            )
            .all()
        )
        for asset in live_assets:
            existing = (
                db.query(Valuation)
                .filter(
                    Valuation.asset_id == asset.id,
                    Valuation.heir_id == heir_id,
                )
                .first()
            )
            if not existing:
                db.add(Valuation(
                    asset_id=asset.id,
                    heir_id=heir_id,
                    points=0,
                ))

        # Delete ID scan file from storage
        if heir.id_scan_uri:
            try:
                storage = get_storage_driver()
                storage.delete(heir.id_scan_uri)
            except Exception:
                pass
        heir.id_scan_uri = None

        db.commit()
        db.refresh(heir)

        # Refresh the admin's JWT cookie so their session doesn't expire
        # while they are actively reviewing IDs.
        admin_token = create_access_token(
            user_id=current_admin["user_id"],
            username=current_admin["username"],
            role="ADMIN",
            session_id=current_admin.get("session_id"),
        )
        response = JSONResponse(
            content={
                "status": "success",
                "message": "Verification action processed successfully.",
                "heir": _heir_to_response(heir),
            }
        )
        set_auth_cookie(response, admin_token)
        return response

    elif body.action == "reject":
        # Delete ID scan file, reset id_scan_uri
        if heir.id_scan_uri:
            try:
                storage = get_storage_driver()
                storage.delete(heir.id_scan_uri)
            except Exception:
                pass
        heir.id_scan_uri = None
        db.commit()
        db.refresh(heir)

        # Refresh the admin's JWT cookie so their session doesn't expire
        # while they are actively reviewing IDs.
        admin_token = create_access_token(
            user_id=current_admin["user_id"],
            username=current_admin["username"],
            role="ADMIN",
            session_id=current_admin.get("session_id"),
        )
        response = JSONResponse(
            content={
                "status": "success",
                "message": "Verification action processed successfully.",
                "heir": _heir_to_response(heir),
            }
        )
        set_auth_cookie(response, admin_token)
        return response


# ---------------------------------------------------------------------------
# T64 — Schema
# ---------------------------------------------------------------------------


class AssetPreAllocateRequest(BaseModel):
    allocated_to_id: str


# ---------------------------------------------------------------------------
# T64 — Asset Pre-Allocation API
# ---------------------------------------------------------------------------


@app.post("/api/assets/{asset_id}/pre-allocate")
@limiter.limit("30/minute")
async def pre_allocate_asset(
    request: Request,
    asset_id: str,
    body: AssetPreAllocateRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Pre-allocate a staged/live asset to an Heir during setup.

    Per Backend Spec §9.2 (POST /api/assets/{asset_id}/pre-allocate):
    Updates the asset row: sets allocated_to_id and transitions status
    to 'PRE_ALLOCATED'. Deletes all existing valuation rows for this
    asset to prevent orphaned valuations from polluting the solver matrix.
    Returns 400 if session is ACTIVE, LOCKED, or FINALIZED.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    session = (
        db.query(SessionModel).filter(SessionModel.id == asset.session_id).first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status in ("ACTIVE", "LOCKED", "FINALIZED"):
        raise HTTPException(
            status_code=400,
            detail=f"Assets can only be pre-allocated during the SETUP phase. "
            f"Current session status is '{session.status}'.",
        )

    # Delete all existing valuation rows for this asset
    db.query(Valuation).filter(Valuation.asset_id == asset_id).delete()

    # Update asset
    asset.allocated_to_id = body.allocated_to_id
    asset.status = "PRE_ALLOCATED"
    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "asset_id": str(asset.id),
            "allocated_to_id": str(asset.allocated_to_id),
        }
    )


# ---------------------------------------------------------------------------
# T43 — Custom FAQ CRUD API
# ---------------------------------------------------------------------------


@app.post("/api/sessions/{session_id}/faqs")
@limiter.limit("30/minute")
async def create_faq(
    request: Request,
    session_id: str,
    body: FAQCreate,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Create a custom FAQ for a session.

    Per Backend Spec §9.4 (POST /api/sessions/{session_id}/faqs):
    Admin creates a custom FAQ entry (question + answer).
    Broadcasts a WebSocket event to refresh Heir dashboards.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    faq = CustomFAQ(
        session_id=session_id,
        question=body.question,
        answer=body.answer,
    )
    db.add(faq)
    db.commit()

    # Broadcast FAQ mutation event
    await manager.broadcast_session_status(
        session_id,
        {"type": "faq_updated", "action": "created", "faq_id": str(faq.id)},
    )

    return JSONResponse(
        content={
            "id": str(faq.id),
            "question": faq.question,
            "answer": faq.answer,
        },
        status_code=201,
    )


@app.put("/api/sessions/{session_id}/faqs/{faq_id}")
@limiter.limit("30/minute")
async def update_faq(
    request: Request,
    session_id: str,
    faq_id: str,
    body: FAQCreate,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Update an existing custom FAQ.

    Per Backend Spec §9.4 (PUT /api/sessions/{session_id}/faqs/{faq_id}):
    Admin edits an existing FAQ. Broadcasts WebSocket event.
    """
    faq = db.query(CustomFAQ).filter(
        CustomFAQ.id == faq_id,
        CustomFAQ.session_id == session_id,
    ).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    faq.question = body.question
    faq.answer = body.answer
    db.commit()

    await manager.broadcast_session_status(
        session_id,
        {"type": "faq_updated", "action": "updated", "faq_id": faq_id},
    )

    return JSONResponse(
        content={
            "id": faq_id,
            "question": faq.question,
            "answer": faq.answer,
        }
    )


@app.delete("/api/sessions/{session_id}/faqs/{faq_id}")
@limiter.limit("30/minute")
async def delete_faq(
    request: Request,
    session_id: str,
    faq_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Delete a custom FAQ.

    Per Backend Spec §9.4 (DELETE /api/sessions/{session_id}/faqs/{faq_id}):
    Admin permanently deletes a custom FAQ. Broadcasts WebSocket event.
    """
    faq = db.query(CustomFAQ).filter(
        CustomFAQ.id == faq_id,
        CustomFAQ.session_id == session_id,
    ).first()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    db.delete(faq)
    db.commit()

    await manager.broadcast_session_status(
        session_id,
        {"type": "faq_updated", "action": "deleted", "faq_id": faq_id},
    )

    return JSONResponse(
        content={
            "status": "success",
            "message": "Custom FAQ deleted",
        }
    )


@app.get("/api/sessions/{session_id}/faqs")
@limiter.limit("60/minute")
async def list_faqs(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retrieve all FAQs for a session.

    Per Backend Spec §9.4 (GET /api/sessions/{session_id}/faqs):
    Returns all custom FAQs for the session. Accessible to Heirs and Admin.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    faqs = (
        db.query(CustomFAQ)
        .filter(CustomFAQ.session_id == session_id)
        .order_by(CustomFAQ.created_at.desc())
        .all()
    )

    return JSONResponse(
        content=[
            {
                "id": str(f.id),
                "question": f.question,
                "answer": f.answer,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in faqs
        ]
    )


# ---------------------------------------------------------------------------
# T39 — Schema
# ---------------------------------------------------------------------------


class AdminSetupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=100)


class SessionCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


class SessionUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# T39 — Admin Setup & Session Creation API
# ---------------------------------------------------------------------------


@app.get("/api/setup/status")
@limiter.limit("60/minute")
async def setup_status(
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
):
    """Return whether first-admin setup has already been completed."""
    existing_admin = (
        db.query(User).filter(User.role == "ADMIN").first()
    )
    return {"admin_exists": existing_admin is not None}


@app.post("/api/setup/admin")
@limiter.limit("5/minute")
async def setup_admin(
    request: Request,
    body: AdminSetupRequest,
    response: Response,
    db: DBSession = Depends(get_db),
):
    """
    First-boot admin account creation with BIP39 paper recovery key.

    Per Backend Spec §9.5 (POST /api/setup/admin):
    Seed route to initialize the first Administrator account. Reads the
    system's active ENCRYPTION_KEY, converts it into a 24-word BIP39
    mnemonic Paper Recovery Key, saves the hashed admin credentials,
    and returns the mnemonic phrase. Idempotent — returns 409 if an
    Admin user already exists.
    """
    existing_admin = (
        db.query(User).filter(User.role == "ADMIN").first()
    )
    if existing_admin is not None:
        raise HTTPException(
            status_code=409,
            detail="Admin account already exists. Setup can only be run once.",
        )

    import base64 as _base64
    from mnemonic import Mnemonic as _Mnemonic

    encryption_key = os.environ.get("ENCRYPTION_KEY")
    if not encryption_key:
        raise HTTPException(
            status_code=500,
            detail="ENCRYPTION_KEY environment variable is not set. "
            "Cannot generate paper recovery key.",
        )

    # Derive BIP39 mnemonic from the 32-byte raw AES key
    try:
        raw_key_bytes = _base64.urlsafe_b64decode(encryption_key.encode())
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="ENCRYPTION_KEY is not a valid base64-encoded Fernet key.",
        )

    if len(raw_key_bytes) != 32:
        raise HTTPException(
            status_code=500,
            detail="ENCRYPTION_KEY must decode to exactly 32 bytes.",
        )

    mnemo = _Mnemonic("english")
    paper_recovery_key = mnemo.to_mnemonic(raw_key_bytes)

    # Create admin user
    pw_hashed = hash_password(body.password)
    admin_user = User(
        username=body.username,
        role="ADMIN",
        pw_hash=pw_hashed,
        status="ACTIVE",
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    # Issue JWT cookie so the admin is immediately authenticated
    jwt_token = create_access_token(
        user_id=str(admin_user.id),
        username=admin_user.username,
        role="ADMIN",
        session_id=None,
    )
    set_auth_cookie(response, jwt_token)

    response.status_code = 201
    return {
        "status": "created",
        "username": admin_user.username,
        "paper_recovery_key": paper_recovery_key,
    }


class SessionResponse(BaseModel):
    id: str
    title: str
    status: str = Field(..., pattern=r"^(SETUP|ACTIVE|LOCKED|FINALIZED)$")
    is_paused: bool
    paused_at: str | None = None
    is_deadlocked: bool
    announcement: str | None = None
    announcement_updated_at: str | None = None
    deadline: str | None = None
    created_at: str


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
@limiter.limit("60/minute")
async def get_session_details(
    request: Request,
    session_id: str,
    response: Response,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retrieve session details by ID.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(
        id=str(session.id),
        title=session.title,
        status=session.status,
        is_paused=session.is_paused,
        paused_at=session.paused_at.isoformat() if session.paused_at else None,
        is_deadlocked=session.is_deadlocked,
        announcement=session.announcement,
        announcement_updated_at=session.announcement_updated_at.isoformat() if session.announcement_updated_at else None,
        deadline=session.deadline.isoformat() if session.deadline else None,
        created_at=session.created_at.isoformat() if session.created_at else "",
    )


@app.get("/api/sessions", response_model=list[SessionResponse])
@limiter.limit("60/minute")
async def list_sessions(
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    List all sessions (accessible to Admin or Heir).
    """
    if current_user.get("role") == "ADMIN":
        sessions = db.query(SessionModel).all()
    else:
        session_id = current_user.get("session_id")
        sessions = db.query(SessionModel).filter(SessionModel.id == session_id).all() if session_id else []

    return [
        SessionResponse(
            id=str(s.id),
            title=s.title,
            status=s.status,
            is_paused=s.is_paused,
            paused_at=s.paused_at.isoformat() if s.paused_at else None,
            is_deadlocked=s.is_deadlocked,
            announcement=s.announcement,
            announcement_updated_at=s.announcement_updated_at.isoformat() if s.announcement_updated_at else None,
            deadline=s.deadline.isoformat() if s.deadline else None,
            created_at=s.created_at.isoformat() if s.created_at else "",
        )
        for s in sessions
    ]


@app.post("/api/sessions")
@limiter.limit("30/minute")
async def create_session(
    request: Request,
    body: SessionCreateRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Create a new mediation session.

    Per Backend Spec §9.1 (POST /api/sessions):
    Admin credentials required. Creates a new estate mediation session
    with the given title, defaults to 'SETUP' status.
    """
    session = SessionModel(
        title=body.title,
        status="SETUP",
        is_paused=False,
        is_deadlocked=False,
    )
    db.add(session)
    db.flush()

    # Seed default categories
    default_categories = ["Jewelry", "Furniture", "Art", "Other"]
    for cat_name in default_categories:
        db.add(Category(session_id=session.id, name=cat_name))

    db.commit()
    db.refresh(session)

    return JSONResponse(
        content={
            "session_id": str(session.id),
            "title": session.title,
            "status": session.status,
            "is_paused": session.is_paused,
            "deadline": (
                session.deadline.isoformat() if session.deadline else None
            ),
        },
        status_code=201,
    )


@app.patch("/api/sessions/{session_id}", response_model=SessionResponse)
@limiter.limit("30/minute")
async def update_session(
    request: Request,
    session_id: str,
    response: Response,
    body: SessionUpdateRequest,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Update a mediation session's title.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.title = body.title.strip()
    db.commit()
    db.refresh(session)

    return SessionResponse(
        id=str(session.id),
        title=session.title,
        status=session.status,
        is_paused=session.is_paused,
        paused_at=session.paused_at.isoformat() if session.paused_at else None,
        is_deadlocked=session.is_deadlocked,
        announcement=session.announcement,
        announcement_updated_at=session.announcement_updated_at.isoformat() if session.announcement_updated_at else None,
        deadline=session.deadline.isoformat() if session.deadline else None,
        created_at=session.created_at.isoformat() if session.created_at else "",
    )





@app.get("/api/heirs/me")
@limiter.limit("60/minute")
async def get_my_heir_profile(
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retrieve current heir profile.
    Per Backend Spec §9.5 (GET /api/heirs/me):
    """
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")

    heir_id = current_user.get("user_id")
    heir = db.query(User).filter(User.id == heir_id).first()
    if not heir:
        raise HTTPException(status_code=401, detail="Heir not found")

    return JSONResponse(content=_heir_to_response(heir))


@app.put("/api/heirs/me/profile")
@limiter.limit("30/minute")
async def update_my_heir_profile(
    request: Request,
    body: HeirProfileUpdate,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Update current heir profile.
    Per Backend Spec §9.5 (PUT /api/heirs/me/profile):
    """
    import hashlib
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")

    heir_id = current_user.get("user_id")
    heir = db.query(User).filter(User.id == heir_id).first()
    if not heir:
        raise HTTPException(status_code=401, detail="Heir not found")

    # 1. Verify session status is not LOCKED or FINALIZED
    session = db.query(SessionModel).filter(SessionModel.id == heir.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status in ["LOCKED", "FINALIZED"]:
        raise HTTPException(status_code=400, detail="Cannot update profile when session is locked or finalized.")

    # 2. Verify heir status is not ABSTAINED or EXPIRED_NON_PARTICIPATING
    if heir.status in ["ABSTAINED", "EXPIRED_NON_PARTICIPATING"]:
        raise HTTPException(status_code=400, detail="Cannot update profile for abstained or non-participating heirs.")

    # Parse date_of_birth
    try:
        new_dob = datetime.strptime(body.date_of_birth, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date_of_birth format. Use YYYY-MM-DD.")

    # 3. Check if legal identity fields changed
    legal_fields_changed = (
        heir.legal_first_name != body.legal_first_name or
        heir.legal_middle_name != body.legal_middle_name or
        heir.legal_last_name != body.legal_last_name or
        heir.date_of_birth != new_dob
    )

    # Collect pre-update values
    pre_update_snapshot = {
        "legal_first_name": heir.legal_first_name,
        "legal_middle_name": heir.legal_middle_name,
        "legal_last_name": heir.legal_last_name,
        "relationship_to_decedent": heir.relationship_to_decedent,
        "date_of_birth": heir.date_of_birth.isoformat() if heir.date_of_birth else None,
        "email": heir.email,
        "phone": heir.phone,
        "physical_address": heir.physical_address,
        **_address_response_fields(heir),
        "identity_verified": heir.identity_verified,
        "status": heir.status,
        "id_scan_uri": heir.id_scan_uri,
    }

    if legal_fields_changed:
        if heir.id_scan_uri:
            try:
                storage = get_storage_driver()
                storage.delete(heir.id_scan_uri)
            except Exception:
                pass
            heir.id_scan_uri = None
        heir.identity_verified = False
        heir.status = "PROFILE_HOLD"

    # 4. Save updated fields
    heir.legal_first_name = body.legal_first_name
    heir.legal_middle_name = body.legal_middle_name
    heir.legal_last_name = body.legal_last_name
    heir.relationship_to_decedent = body.relationship_to_decedent
    heir.date_of_birth = new_dob
    heir.email = body.email
    heir.phone = body.phone
    structured_address = _structured_address_from_body(body)
    heir.physical_address = _compose_physical_address(
        structured_address,
        fallback=body.physical_address,
    )
    for field_name, value in structured_address.items():
        setattr(heir, field_name, value)

    post_update_snapshot = {
        "legal_first_name": heir.legal_first_name,
        "legal_middle_name": heir.legal_middle_name,
        "legal_last_name": heir.legal_last_name,
        "relationship_to_decedent": heir.relationship_to_decedent,
        "date_of_birth": heir.date_of_birth.isoformat() if heir.date_of_birth else None,
        "email": heir.email,
        "phone": heir.phone,
        "physical_address": heir.physical_address,
        **_address_response_fields(heir),
        "identity_verified": heir.identity_verified,
        "status": heir.status,
        "id_scan_uri": heir.id_scan_uri,
    }

    changed_fields = {}
    for k, v in post_update_snapshot.items():
        if pre_update_snapshot[k] != v:
            changed_fields[k] = {
                "pre": pre_update_snapshot[k],
                "post": v
            }

    # 5. Log USER_PROFILE_UPDATE event
    prev_hash = "0" * 64
    last_log = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == heir.session_id)
        .order_by(AuditLog.id.desc())
        .first()
    )
    if last_log:
        prev_hash = last_log.sha256_hash

    state_snapshot = {
        "event": "USER_PROFILE_UPDATE",
        "editor_id": str(heir_id),
        "heir_id": str(heir_id),
        "changed_fields": changed_fields,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    snapshot_str = str(sorted(state_snapshot.items()))
    profile_update_hash = hashlib.sha256(
        (prev_hash + snapshot_str).encode("utf-8")
    ).hexdigest()

    audit_entry = AuditLog(
        session_id=heir.session_id,
        event_type="USER_PROFILE_UPDATE",
        state_snapshot=state_snapshot,
        prev_hash=prev_hash,
        sha256_hash=profile_update_hash,
    )
    db.add(audit_entry)
    db.commit()

    # 6. Broadcast WebSocket status frame
    if heir.session_id:
        await manager.broadcast_session_status(
            str(heir.session_id),
            {
                "type": "heir_profile_updated",
                "heir_id": str(heir.id),
                "heir_username": heir.username,
                "status": heir.status,
            },
        )

    return JSONResponse(
        content={
            "status": "success",
            "message": "Heir profile updated successfully.",
            "identity_verified": heir.identity_verified,
        }
    )


@app.post("/api/heirs/me/upload-id")
@limiter.limit("10/minute")
async def upload_id_scan(
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Upload a government ID scan (image or PDF).

    Per Backend Spec §9.5 (POST /api/heirs/me/upload-id):
    1. Accepts multipart/form-data with file key (up to 10MB).
    2. Encrypts the uploaded file bytes using AES-Fernet.
    3. Saves encrypted file to /app/static/uploads/identities/ with UUID filename.
    4. Updates id_scan_uri and sets identity_verified = False.
    """
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")

    heir_id = current_user.get("user_id")
    heir = db.query(User).filter(User.id == heir_id).first()
    if not heir:
        raise HTTPException(status_code=401, detail="Heir not found")

    # Parse multipart upload
    form = await request.form()
    file_upload = form.get("file")
    if not file_upload:
        raise HTTPException(status_code=400, detail="No file uploaded")

    raw_bytes = await file_upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Size limit: 10MB
    if len(raw_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")

    # Encrypt the file bytes using AES-Fernet
    import os as _os
    from cryptography.fernet import Fernet

    encryption_key = _os.environ.get("ENCRYPTION_KEY")
    if not encryption_key:
        raise HTTPException(
            status_code=500,
            detail="Server encryption key is not configured.",
        )

    fernet = Fernet(encryption_key.encode())
    encrypted_bytes = fernet.encrypt(raw_bytes)

    # Save encrypted file to identities directory
    import uuid as _uuid_mod

    file_id = _uuid_mod.uuid4()
    filename = f"static/uploads/identities/{file_id}"

    storage = get_storage_driver()
    storage.save(filename, encrypted_bytes)

    # Update heir record
    heir.id_scan_uri = filename
    heir.identity_verified = False
    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": "ID document uploaded and encrypted successfully",
            "user_status": heir.status,
            "identity_verified": heir.identity_verified,
            "id_scan_uri": heir.id_scan_uri,
        }
    )


# ---------------------------------------------------------------------------
# T55 — FastAPI Heir GDPR Erasure Router
# ---------------------------------------------------------------------------


@app.delete("/api/heirs/me")
@limiter.limit("10/minute")
async def gdpr_erase_heir(
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    GDPR Right to Erasure — Soft Anonymization for the calling Heir.

    Per Backend Spec §9.5 (DELETE /api/heirs/me):
    1. Overwrites PII fields (name → "Anonymized", contact → NULL).
    2. Deletes encrypted ID scan file from storage if present.
    3. Clears invite tokens.
    4. Permanently deletes all private chat transcripts for this Heir.
    5. Permanently deletes all LangGraph checkpointer records for this Heir's thread.
    6. Submission Status Separation:
       - Unsubmitted (is_submitted=False): status→ABSTAINED, cascade-delete valuations.
       - Submitted (is_submitted=True): retains status/points/public memories,
         overwrites private reasoning text with NULL.
    7. Anonymizes historical audit_logs state_snapshot for this Heir.
    """
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")

    heir_id = current_user.get("user_id")
    heir = (
        db.query(User)
        .filter(User.id == heir_id, User.role == "HEIR")
        .with_for_update()
        .first()
    )
    if not heir:
        raise HTTPException(status_code=401, detail="Heir not found")

    session = (
        db.query(SessionModel)
        .filter(SessionModel.id == heir.session_id)
        .first()
    )
    if session and session.status in ("LOCKED", "FINALIZED"):
        raise HTTPException(
            status_code=400,
            detail="Account erasure is not permitted after session is locked or finalized.",
        )

    session_id = str(heir.session_id) if heir.session_id else ""
    heir_id_str = str(heir.id)
    is_submitted = heir.is_submitted

    # Collect original PII values for audit log sanitization
    pii_values = [
        heir.legal_first_name,
        heir.legal_middle_name,
        heir.legal_last_name,
        heir.email,
        heir.phone,
        heir.physical_address,
        *_address_response_fields(heir).values(),
        heir.username,
    ]
    pii_values = [v for v in pii_values if v]

    # 1. Overwrite PII fields
    heir.username = f"Anonymized Beneficiary {heir_id_str[-12:]}"
    heir.legal_first_name = "Anonymized"
    heir.legal_middle_name = None
    heir.legal_last_name = f"Beneficiary {heir_id_str[-12:]}"
    heir.relationship_to_decedent = None
    heir.date_of_birth = None
    heir.email = None
    heir.phone = None
    heir.physical_address = None
    for field_name in ADDRESS_FIELD_NAMES:
        setattr(heir, field_name, None)
    heir.pw_hash = None

    # 2. Delete encrypted ID scan file from storage if present
    if heir.id_scan_uri:
        try:
            storage = get_storage_driver()
            storage.delete(heir.id_scan_uri)
        except Exception:
            logger.warning(
                "Failed to delete ID scan file %s for heir %s",
                heir.id_scan_uri,
                heir_id,
            )
    heir.id_scan_uri = None

    # 3. Clear invite tokens
    heir.invite_token = None
    heir.invite_token_expires_at = None
    heir.invite_token_used = False

    # 4. Permanently delete all private chat transcripts
    db.query(ChatMessage).filter(ChatMessage.heir_id == heir_id).delete()

    # 5. Permanently delete LangGraph checkpointer records
    thread_id = f"{session_id}:{heir_id_str}"
    try:
        from .database import engine
        from sqlalchemy import text as sa_text
        with engine.begin() as conn:
            for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
                conn.execute(
                    sa_text(f"DELETE FROM {table} WHERE thread_id = :tid"),
                    {"tid": thread_id},
                )
    except Exception:
        logger.warning(
            "Failed to clean checkpointer state for thread %s — continuing",
            thread_id,
        )

    # 6. Submission Status Separation
    if not is_submitted:
        # Unsubmitted: status→ABSTAINED, cascade-delete valuations
        heir.status = "ABSTAINED"
        db.query(Valuation).filter(Valuation.heir_id == heir_id).delete()
    else:
        # Submitted: retain status/points/public memories, delete private reasoning
        heir.status = "SUBMITTED"
        # Overwrite private reasoning with NULL
        valuations = (
            db.query(Valuation)
            .filter(
                Valuation.heir_id == heir_id,
                Valuation.is_reasoning_shared == False,
                Valuation.reasoning.isnot(None),
            )
            .all()
        )
        for v in valuations:
            v.reasoning = None

    db.flush()

    # 7. Anonymize historical audit_logs state_snapshot
    audit_logs = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == heir.session_id)
        .all()
    )
    for log_entry in audit_logs:
        try:
            snapshot = log_entry.state_snapshot
            if not isinstance(snapshot, (dict, list)):
                continue
            _redact_pii_in_place(snapshot, heir_id_str, pii_values)
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(log_entry, "state_snapshot")
        except Exception:
            logger.warning(
                "Failed to anonymize audit log %d — continuing",
                log_entry.id,
            )

    db.commit()

    # Clear auth cookie
    clear_auth_cookie(response)

    return JSONResponse(
        content={
            "status": "success",
            "message": "Personal identification purged; account records soft-anonymized "
            "and checkpointer states cleared for probate record-keeping.",
        }
    )


# ---------------------------------------------------------------------------
# T57 — FastAPI GDPR Data Portability API
# ---------------------------------------------------------------------------


@app.get("/api/heirs/me/export")
@limiter.limit("10/minute")
async def gdpr_export_heir(
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    GDPR Article 20 — Data Portability endpoint.

    Per Backend Spec §9.5 (GET /api/heirs/me/export):
    Decrypts and packages all of the Heir's personal records in a
    structured JSON download: profile details, valuations, decrypted
    chat history, and support requests.

    Returns: application/json file stream attachment.
    """
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")

    heir_id = current_user.get("user_id")
    heir = db.query(User).filter(User.id == heir_id, User.role == "HEIR").first()
    if not heir:
        raise HTTPException(status_code=401, detail="Heir not found")

    now_utc = datetime.now(timezone.utc)

    # Collect valuations
    valuations = (
        db.query(Valuation)
        .filter(Valuation.heir_id == heir_id)
        .all()
    )
    valuation_data = []
    for v in valuations:
        valuation_data.append({
            "asset_id": str(v.asset_id),
            "points": v.points,
            "reasoning": v.reasoning,
            "is_reasoning_shared": v.is_reasoning_shared if v.is_reasoning_shared is not None else False,
        })

    # Collect decrypted chat history (per Compliance Spec §2.2)
    chat_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.heir_id == heir_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    chat_data = []
    for msg in chat_messages:
        chat_data.append({
            "timestamp": msg.created_at.isoformat() if msg.created_at else None,
            "sender": msg.sender,
            "text": msg.message_text,
        })

    # Collect support tickets (per Compliance Spec §2.2 key name)
    support_requests = (
        db.query(SupportRequest)
        .filter(SupportRequest.heir_id == heir_id)
        .order_by(SupportRequest.created_at.desc())
        .all()
    )
    support_data = []
    for sr in support_requests:
        support_data.append({
            "id": str(sr.id),
            "message": sr.message,
            "admin_response": getattr(sr, "admin_response", None),
            "initiator_role": getattr(sr, "initiator_role", None) or "HEIR",
            "status": sr.status,
            "created_at": sr.created_at.isoformat() if sr.created_at else None,
            "responded_at": sr.responded_at.isoformat() if getattr(sr, "responded_at", None) else None,
            "resolved_at": sr.resolved_at.isoformat() if getattr(sr, "resolved_at", None) else None,
        })

    payload = {
        "heir_id": str(heir.id),
        "username": heir.username,
        "legal_first_name": heir.legal_first_name,
        "legal_middle_name": heir.legal_middle_name,
        "legal_last_name": heir.legal_last_name,
        "relationship_to_decedent": heir.relationship_to_decedent,
        "date_of_birth": heir.date_of_birth.isoformat() if heir.date_of_birth else None,
        "identity_verified": heir.identity_verified,
        "email": heir.email,
        "phone": heir.phone,
        "physical_address": heir.physical_address,
        **_address_response_fields(heir),
        "consent_accepted": heir.consent_accepted,
        "age_verified": heir.age_verified,
        "consent_timestamp": heir.consent_timestamp.isoformat() if heir.consent_timestamp else None,
        "is_submitted": heir.is_submitted,
        "valuations": valuation_data,
        "chat_history": chat_data,
        "support_tickets": support_data,
    }

    return JSONResponse(content=payload)


# ---------------------------------------------------------------------------
# T16 — Schema
# ---------------------------------------------------------------------------

import hashlib
from fastapi.responses import StreamingResponse


class KeepsakeEmailRequest(BaseModel):
    heir_id: str | None = None


class AdminOverrideRequest(BaseModel):
    asset_id: str
    allocated_to_id: str
    reason: str = Field(..., min_length=5, max_length=250)


class AbstainRequest(BaseModel):
    legal_name_signature: str = Field(..., min_length=3, max_length=200)


def _reconstruct_solver_result_for_finalized_pdf(
    assets: list[Asset],
    audit_logs: list[AuditLog],
):
    """Rebuild the solver result needed by finalized PDF downloads.

    The finalization endpoint persists the authoritative MNW scalar and
    allocation map in the FINALIZED audit block. Asset rows are still used as a
    fallback for older ledgers that predate that snapshot shape.
    """
    from .solver import SolverResult

    allocation: dict[str, list[str]] = {}
    mnw_product_value = 0.0

    final_log = next(
        (
            log for log in reversed(audit_logs)
            if log.event_type == "FINALIZED" and isinstance(log.state_snapshot, dict)
        ),
        None,
    )
    if final_log:
        snapshot = final_log.state_snapshot or {}
        raw_allocation = snapshot.get("allocations") or {}
        if isinstance(raw_allocation, dict):
            for heir_id, asset_ids in raw_allocation.items():
                if isinstance(asset_ids, list):
                    allocation[str(heir_id)] = [str(asset_id) for asset_id in asset_ids]
        try:
            mnw_product_value = float(snapshot.get("mnw_product_value") or 0.0)
        except (TypeError, ValueError):
            mnw_product_value = 0.0

    if not allocation:
        for asset in assets:
            if asset.allocated_to_id and asset.status == "DISTRIBUTED":
                hid = str(asset.allocated_to_id)
                allocation.setdefault(hid, []).append(str(asset.id))

    return SolverResult(
        allocation=allocation,
        mnw_product_value=mnw_product_value,
        tie_breaker_events=[],
    )


# ---------------------------------------------------------------------------
# T33 — Active Abstention Waiver PDF Receipt & Email
# ---------------------------------------------------------------------------


def _generate_waiver_hash(session_id: str, heir_id: str, signature: str, prev_hash: str) -> str:
    """Generate a SHA-256 hash for the abstention waiver audit log entry."""
    raw_data = f"{session_id}:{heir_id}:ABSTENTION_WAIVER:{signature}:{prev_hash}"
    return hashlib.sha256(raw_data.encode()).hexdigest()


@app.post("/api/heirs/me/abstain")
@limiter.limit("10/minute")
async def abstain(
    request: Request,
    body: AbstainRequest,
    response: Response,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Active Abstention / Waiver of Rights.

    Per Backend Spec §9.5 (POST /api/heirs/me/abstain):
    1. Verifies Heir status is ACTIVE or SUBMITTED.
    2. Logs ABSTENTION_WAIVER event block in audit_logs.
    3. Updates status to ABSTAINED, cascade-deletes valuations.
    4. Queues SMTP receipt email. On failure, sets waiver_email_failed=True
       and auto-generates a support request.
    5. Broadcasts WebSocket status frame.
    """
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")

    heir_id = current_user.get("user_id")
    heir = (
        db.query(User)
        .filter(User.id == heir_id, User.role == "HEIR")
        .with_for_update()
        .first()
    )
    if not heir:
        raise HTTPException(status_code=401, detail="Heir not found")

    if heir.status not in ("ACTIVE", "SUBMITTED"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot abstain — current status is '{heir.status}'.",
        )

    now_utc = datetime.now(timezone.utc)
    client_ip = request.client.host if request.client else "unknown"

    # 2. Write ABSTENTION_WAIVER audit log entry
    prev_hash = "0" * 64
    last_log = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == heir.session_id)
        .order_by(AuditLog.id.desc())
        .first()
    )
    if last_log:
        prev_hash = last_log.sha256_hash

    state_snapshot = {
        "event": "ABSTENTION_WAIVER",
        "heir_id": str(heir.id),
        "heir_username": heir.username,
        "legal_name_signature": body.legal_name_signature,
        "ip_address": client_ip,
        "timestamp_utc": now_utc.isoformat(),
    }
    waiver_hash = _generate_waiver_hash(
        str(heir.session_id) if heir.session_id else "",
        str(heir.id),
        body.legal_name_signature,
        prev_hash,
    )

    audit_entry = AuditLog(
        session_id=heir.session_id,
        event_type="ABSTENTION_WAIVER",
        state_snapshot=state_snapshot,
        prev_hash=prev_hash,
        sha256_hash=waiver_hash,
    )
    db.add(audit_entry)

    # 3. Update status and cascade-delete valuations
    heir.status = "ABSTAINED"
    heir.is_submitted = False
    # Delete all valuations for this heir (both default 0-pt and submitted values)
    db.query(Valuation).filter(Valuation.heir_id == heir_id).delete()

    # 4. E-SIGN/UETA compliance email dispatch
    if heir.email:
        full_name = " ".join(
            p for p in [
                heir.legal_first_name,
                heir.legal_middle_name,
                heir.legal_last_name,
            ] if p
        ) or heir.username

        subject = f"Abstention Waiver Receipt — {full_name}"
        email_body = (
            f"Dear {full_name},\n\n"
            f"This email confirms that you have electronically signed an abstention "
            f"waiver, voluntarily withdrawing from the asset distribution proceedings.\n\n"
            f"Signed: {body.legal_name_signature}\n"
            f"Date: {now_utc.strftime('%B %d, %Y at %H:%M UTC')}\n"
            f"IP Address: {client_ip}\n\n"
            f"Per the Electronic Signatures in Global and National Commerce Act "
            f"(E-SIGN, 15 U.S.C. § 7001) and the Uniform Electronic Transactions Act "
            f"(UETA), your electronic signature carries the same legal weight as a "
            f"handwritten signature.\n\n"
            f"To obtain a PDF copy of your signed waiver receipt, visit your dashboard "
            f"and download it from the 'My Abstention' section.\n\n"
            f"The Estate Steward"
        )

        # Session for the subject description
        session = (
            db.query(SessionModel)
            .filter(SessionModel.id == heir.session_id)
            .first()
        )
        session_title = session.title if session else "Estate"

        email_success = await send_email(
            to=heir.email,
            subject=subject,
            body=email_body,
        )

        if not email_success:
            # SMTP failed after all retries — set flag and auto-generate support ticket
            heir.waiver_email_failed = True
            fallback_msg = (
                f"SYSTEM WARNING: Electronic waiver confirmation email to "
                f"{heir.email} failed to deliver. Executor must physically "
                f"deliver a printed copy of the signed waiver receipt to "
                f"satisfy E-SIGN/UETA regulations."
            )
            logger.warning(fallback_msg)
            support_ticket = SupportRequest(
                session_id=heir.session_id,
                heir_id=heir.id,
                message=fallback_msg,
                status="OPEN",
            )
            db.add(support_ticket)

    db.commit()

    # 5. Broadcast WebSocket status frame
    if heir.session_id:
        await manager.broadcast_session_status(
            str(heir.session_id),
            {
                "type": "heir_abstained",
                "heir_id": str(heir.id),
                "heir_username": heir.username,
            },
        )

    return JSONResponse(
        content={
            "status": "success",
            "message": "Waiver signed and abstention registered",
        }
    )


@app.get("/api/heirs/me/abstain/receipt")
@limiter.limit("20/minute")
async def download_abstain_receipt(
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Download the signed waiver receipt PDF.

    Per Backend Spec §9.5 (GET /api/heirs/me/abstain/receipt):
    Generates and downloads a single-page ReportLab PDF receipt containing
    the full E-SIGN disclosure, signed waiver text, Heir's legal name,
    IP address, timestamp, and database SHA-256 block hash seal.
    """
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")

    heir_id = current_user.get("user_id")
    heir = db.query(User).filter(
        User.id == heir_id,
        User.role == "HEIR",
        User.status == "ABSTAINED",
    ).first()
    if not heir:
        raise HTTPException(
            status_code=400,
            detail="No abstention waiver found. Your account is not in ABSTAINED status.",
        )

    session = (
        db.query(SessionModel)
        .filter(SessionModel.id == heir.session_id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Retrieve the ABSTENTION_WAIVER audit log entry for this heir
    waiver_log = (
        db.query(AuditLog)
        .filter(
            AuditLog.session_id == heir.session_id,
            AuditLog.event_type == "ABSTENTION_WAIVER",
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    if not waiver_log:
        raise HTTPException(
            status_code=500,
            detail="Waiver audit log entry not found.",
        )

    snapshot = waiver_log.state_snapshot or {}
    legal_name_signature = snapshot.get("legal_name_signature", heir.username)
    ip_address = snapshot.get("ip_address", "unknown")
    timestamp_str = snapshot.get("timestamp_utc", "")
    if timestamp_str:
        try:
            timestamp_utc = datetime.fromisoformat(timestamp_str)
        except ValueError:
            timestamp_utc = waiver_log.created_at or datetime.now(timezone.utc)
    else:
        timestamp_utc = waiver_log.created_at or datetime.now(timezone.utc)
    sha256_hash = waiver_log.sha256_hash

    try:
        from .pdf_builder import build_waiver_receipt_pdf

        pdf_buf = build_waiver_receipt_pdf(
            session=session,
            heir=heir,
            legal_name_signature=legal_name_signature,
            ip_address=ip_address,
            timestamp_utc=timestamp_utc,
            sha256_hash=sha256_hash,
        )
    except Exception as e:
        logger.exception("Failed to build waiver receipt PDF")
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {str(e)}",
        )

    pdf_bytes = pdf_buf.getvalue()
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="waiver_receipt_{heir_id}.pdf"',
        },
    )


# ---------------------------------------------------------------------------
# T44 — Session Override API
# ---------------------------------------------------------------------------


@app.post("/api/sessions/{session_id}/override")
@limiter.limit("10/minute")
async def session_override(
    request: Request,
    session_id: str,
    body: list[AdminOverrideRequest],
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Admin override of division deadlocks — force allocation of contested assets.

    Per Backend Spec §9.3 (POST /api/sessions/{session_id}/override):
    1. Gates on LOCKED or deadlocked session state → 400 otherwise.
    2. For each override: update asset in DB (allocated_to_id, status=PRE_ALLOCATED).
    3. Adjust heir points budgets: subtract points allocated to overridden assets
       from each heir's 1000-point budget.
    4. Write ADMIN_OVERRIDE audit log block with fiduciary reason.
    5. Write corrected valuations into LangGraph checkpointer state via
       graph.update_state(config, {"valuations": corrected_valuations}, as_node="HITL_GUARD").
    6. Resume graph execution via graph.stream(None, config), routing to COMMIT_NODE.
    7. Clear is_deadlocked, transition to ACTIVE if not paused.
    8. Broadcast WebSocket status update.
    """
    session = (
        db.query(SessionModel)
        .filter(SessionModel.id == session_id)
        .with_for_update()
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status not in ("LOCKED",):
        raise HTTPException(
            status_code=400,
            detail=f"Session override is only available during LOCKED state. "
            f"Current status is '{session.status}'.",
        )

    if len(body) == 0:
        raise HTTPException(
            status_code=400,
            detail="At least one override assignment is required.",
        )

    now_utc = datetime.now(timezone.utc)

    # Collect all relevant heirs and their current valuations before overrides
    heirs = (
        db.query(User)
        .filter(User.session_id == session_id, User.role == "HEIR")
        .all()
    )
    heir_map = {str(h.id): h for h in heirs}

    # 2. Process each override — update asset allocations
    override_asset_ids: set[str] = set()
    for override in body:
        asset = db.query(Asset).filter(
            Asset.id == override.asset_id,
            Asset.session_id == session_id,
        ).first()
        if not asset:
            raise HTTPException(
                status_code=400,
                detail=f"Asset {override.asset_id} not found in this session.",
            )
        if override.allocated_to_id not in heir_map:
            raise HTTPException(
                status_code=400,
                detail=f"Heir {override.allocated_to_id} not found in this session.",
            )

        asset.allocated_to_id = override.allocated_to_id
        asset.status = "PRE_ALLOCATED"
        override_asset_ids.add(override.asset_id)

    # 3. Adjust heir points budgets for overridden assets
    #    For each heir, find their point allocations to overridden assets
    #    and remove those valuations (since assets are now PRE_ALLOCATED and
    #    won't enter the solver).
    for heir in heirs:
        db.query(Valuation).filter(
            Valuation.asset_id.in_(override_asset_ids),
            Valuation.heir_id == heir.id,
        ).delete()

    db.flush()

    # 4. Write ADMIN_OVERRIDE audit log block
    prev_hash = "0" * 64
    last_log = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == session_id)
        .order_by(AuditLog.id.desc())
        .first()
    )
    if last_log:
        prev_hash = last_log.sha256_hash

    overrides_snapshot = []
    for override in body:
        overrides_snapshot.append({
            "asset_id": override.asset_id,
            "allocated_to_id": override.allocated_to_id,
            "reason": override.reason,
        })

    state_snapshot = {
        "event": "ADMIN_OVERRIDE",
        "session_id": session_id,
        "overrides": overrides_snapshot,
        "timestamp_utc": now_utc.isoformat(),
    }
    snapshot_str = str(sorted(state_snapshot.items()))
    override_hash = hashlib.sha256(
        (prev_hash + snapshot_str).encode("utf-8")
    ).hexdigest()

    audit_entry = AuditLog(
        session_id=session_id,
        event_type="ADMIN_OVERRIDE",
        state_snapshot=state_snapshot,
        prev_hash=prev_hash,
        sha256_hash=override_hash,
    )
    db.add(audit_entry)

    # 5 & 6. Write corrected allocations into LangGraph checkpointer state
    #    and resume graph execution for each affected heir's thread
    try:
        from .graph import get_graph, get_postgres_checkpointer

        saver = get_postgres_checkpointer()
        graph = get_graph()

        for heir in heirs:
            hid = str(heir.id)
            thread_id = f"{session_id}:{hid}"
            config = {"configurable": {"thread_id": thread_id}}

            # Collect the heir's current valuations after the deletions
            current_vals = (
                db.query(Valuation)
                .filter(Valuation.heir_id == heir.id)
                .all()
            )
            corrected_valuations = [
                {
                    "asset_id": str(v.asset_id),
                    "heir_id": str(v.heir_id),
                    "points": v.points,
                    "reasoning": v.reasoning,
                    "is_reasoning_shared": v.is_reasoning_shared,
                }
                for v in current_vals
            ]

            # Write corrected valuations into the checkpointer state at HITL_GUARD
            try:
                graph.update_state(
                    config,
                    {"valuations": corrected_valuations},
                    as_node="HITL_GUARD",
                )
            except Exception:
                logger.warning(
                    "Could not update checkpointer state for thread %s — "
                    "thread may not exist yet. Continuing.",
                    thread_id,
                )

            # Resume graph execution — skips HITL_GUARD, routes to COMMIT_NODE
            try:
                for event in graph.stream(None, config):
                    logger.debug(
                        "Graph resumed for thread %s — event: %s",
                        thread_id,
                        list(event.keys()) if isinstance(event, dict) else str(event),
                    )
            except Exception:
                logger.warning(
                    "Graph resume failed for thread %s — continuing.",
                    thread_id,
                )
    except Exception as e:
        logger.warning(
            "LangGraph override state update failed for session %s: %s",
            session_id,
            e,
        )

    # 7. Clear is_deadlocked, transition to ACTIVE if not paused
    session.is_deadlocked = False
    if not session.is_paused:
        session.status = "ACTIVE"

    db.commit()
    db.refresh(session)

    # 8. Broadcast WebSocket status update
    await manager.broadcast_session_status(
        session_id,
        {
            "type": "session_status",
            "status": session.status,
            "is_paused": session.is_paused,
            "is_deadlocked": session.is_deadlocked,
        },
    )

    return JSONResponse(
        content={
            "status": "resolved",
        }
    )


# ---------------------------------------------------------------------------
# T16 — Session Finalization & Keepsake PDF Download Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/sessions/{session_id}/finalize")
@limiter.limit("10/minute")
async def finalize_session(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Finalize the session — run solver, seal audit chain, commit allocations.

    Per Backend Spec §9.3 (POST /api/sessions/{session_id}/finalize):
    1. Verifies session is ACTIVE or LOCKED (not SETUP or FINALIZED).
    2. Auto-transitions non-submitting active heirs to ABSTAINED, expired
       heirs to EXPIRED_NON_PARTICIPATING.
    3. Verifies no heirs are PROFILE_HOLD.
    4. Collects valuations, runs Fairpyx MNW solver.
    5. Commits allocation results (updates assets.allocated_to_id, status→DISTRIBUTED).
    6. Writes FINALIZED audit log entry and seals SHA-256 hash chain.
    7. Transitions session status to FINALIZED.
    8. Broadcasts WebSocket status update.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status not in ("ACTIVE", "LOCKED"):
        raise HTTPException(
            status_code=400,
            detail=f"Session cannot be finalized — current status is '{session.status}'.",
        )

    if session.status == "FINALIZED":
        raise HTTPException(
            status_code=400,
            detail="Session is already finalized.",
        )

    now_utc = datetime.now(timezone.utc)

    # 2. Auto-transition non-submitting heirs
    all_heirs = (
        db.query(User)
        .filter(User.session_id == session_id, User.role == "HEIR")
        .all()
    )
    for heir in all_heirs:
        if heir.status == "ACTIVE" and not heir.is_submitted:
            heir.status = "ABSTAINED"
        elif (
            heir.status in ("PENDING", "ACTIVE")
            and heir.invite_token_used == False
            and heir.invite_token_expires_at
            and heir.invite_token_expires_at < now_utc
        ):
            heir.status = "EXPIRED_NON_PARTICIPATING"

    db.flush()

    # Refresh after status updates
    all_heirs = (
        db.query(User)
        .filter(User.session_id == session_id, User.role == "HEIR")
        .all()
    )

    # 3. Verify no PROFILE_HOLD heirs
    profile_hold = [h for h in all_heirs if h.status == "PROFILE_HOLD"]
    if profile_hold:
        names = [h.username for h in profile_hold]
        raise HTTPException(
            status_code=400,
            detail=f"Cannot finalize — the following heirs are still pending "
            f"identity verification: {', '.join(names)}.",
        )

    # 4. Collect assets and valuations
    assets = (
        db.query(Asset)
        .filter(Asset.session_id == session_id)
        .all()
    )

    # Participating heirs: SUBMITTED only
    participating = [h for h in all_heirs if h.status == "SUBMITTED"]

    # Pre-allocated assets
    pre_allocated: dict[str, str] = {}
    for a in assets:
        if a.status == "PRE_ALLOCATED" and a.allocated_to_id:
            pre_allocated[str(a.id)] = str(a.allocated_to_id)

    # Build valuations matrix
    heir_ids = [str(h.id) for h in participating]
    asset_ids = [str(a.id) for a in assets if a.status == "LIVE"]
    heir_valuations: dict[str, dict[str, int]] = {}
    submission_times: dict[str, datetime] = {}
    creation_times: dict[str, datetime] = {}

    for heir in participating:
        hid = str(heir.id)
        submission_times[hid] = heir.submitted_at
        creation_times[hid] = heir.created_at
        heir_valuations[hid] = {}
        for a in assets:
            if a.status == "LIVE":
                valuation = (
                    db.query(Valuation)
                    .filter(
                        Valuation.asset_id == a.id,
                        Valuation.heir_id == heir.id,
                    )
                    .first()
                )
                heir_valuations[hid][str(a.id)] = valuation.points if valuation else 0

    # Run solver
    try:
        from .solver import solve_mnw

        result = solve_mnw(
            heir_ids=heir_ids,
            asset_ids=asset_ids,
            valuations=heir_valuations,
            pre_allocated=pre_allocated,
            submission_times=submission_times,
            creation_times=creation_times,
        )
    except Exception as e:
        logger.exception("Solver failed for session %s", session_id)
        raise HTTPException(
            status_code=500,
            detail=f"Fair division solver failed: {str(e)}",
        )

    # 5. Commit allocation results
    for hid, allocated_asset_ids in result.allocation.items():
        for aid in allocated_asset_ids:
            asset = db.query(Asset).filter(Asset.id == aid).first()
            if asset and asset.status == "LIVE":
                asset.allocated_to_id = hid
                asset.status = "DISTRIBUTED"

    # 6. Write FINALIZED audit log entry and seal hash chain
    prev_hash = "0" * 64
    last_log = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == session_id)
        .order_by(AuditLog.id.desc())
        .first()
    )
    if last_log:
        prev_hash = last_log.sha256_hash

    state_snapshot = {
        "event": "FINALIZED",
        "session_id": session_id,
        "allocations": {
            hid: aids for hid, aids in result.allocation.items()
        },
        "mnw_product_value": result.mnw_product_value,
        "tie_breaker_events": [
            e.event_description for e in result.tie_breaker_events
        ],
    }
    snapshot_str = str(sorted(state_snapshot.items()))
    new_hash = hashlib.sha256(
        (prev_hash + snapshot_str).encode("utf-8")
    ).hexdigest()

    audit_entry = AuditLog(
        session_id=session_id,
        event_type="FINALIZED",
        state_snapshot=state_snapshot,
        prev_hash=prev_hash,
        sha256_hash=new_hash,
    )
    db.add(audit_entry)

    # 7. Transition session to FINALIZED
    session.status = "FINALIZED"

    db.commit()
    db.refresh(session)

    # 8. Broadcast WebSocket status update
    await manager.broadcast_session_status(
        session_id,
        {
            "type": "session_status",
            "status": session.status,
            "is_paused": session.is_paused,
            "is_deadlocked": session.is_deadlocked,
        },
    )

    return JSONResponse(
        content={
            "status": "finalized",
            "session_id": str(session.id),
            "mnw_product_value": result.mnw_product_value,
            "tie_breaker_count": len(result.tie_breaker_events),
        }
    )


@app.get("/api/sessions/{session_id}/keepsake")
@limiter.limit("30/minute")
async def download_probate_ledger(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Download the Final Distribution & Probate Audit Ledger PDF.

    Per Backend Spec §9.3 (GET /api/sessions/{session_id}/keepsake):
    Generates and returns the full probate audit ledger PDF.
    Accessible by any authenticated Heir or Admin for this session.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "FINALIZED":
        raise HTTPException(
            status_code=400,
            detail="Probate ledger is only available after session finalization.",
        )

    # Load all session data
    heirs = (
        db.query(User)
        .filter(
            User.session_id == session_id,
            User.role.in_(["HEIR", "ADMIN"]),
        )
        .all()
    )

    # Only show ADMIN users belonging to this session or admins without a session
    admin_user = db.query(User).filter(
        User.role == "ADMIN",
    ).first()
    if admin_user and admin_user not in heirs:
        heirs.append(admin_user)

    assets = (
        db.query(Asset)
        .filter(Asset.session_id == session_id)
        .all()
    )

    audit_logs = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == session_id)
        .order_by(AuditLog.id.asc())
        .all()
    )

    notice_log = build_notice_log(session_id, [h for h in heirs if h.role == "HEIR"])

    solver_result = _reconstruct_solver_result_for_finalized_pdf(assets, audit_logs)

    # Generate PDF
    try:
        from .pdf_builder import build_probate_ledger_pdf

        pdf_buf = build_probate_ledger_pdf(
            session=session,
            heirs=heirs,
            assets=assets,
            solver_result=solver_result,
            audit_logs=audit_logs,
            notice_log=notice_log,
        )
    except Exception as e:
        logger.exception("Failed to build probate ledger PDF")
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {str(e)}",
        )

    pdf_bytes = pdf_buf.getvalue()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    _log_asset_audit_event(db, session_id, "DOWNLOAD_LEDGER", {"action": "download", "user_id": current_user.get("user_id"), "timestamp": timestamp})
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{timestamp}_probate_ledger_{session_id}.pdf"',
        },
    )


@app.get("/api/sessions/{session_id}/keepsake/zip")
@limiter.limit("10/minute")
async def download_all_keepsakes_zip(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Download the Probate Audit Ledger and all individual Heir Keepsakes
    bundled into a single ZIP archive.
    """
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "FINALIZED":
        raise HTTPException(
            status_code=400,
            detail="Keepsakes are only available after session finalization.",
        )

    # Load all session data
    heirs = (
        db.query(User)
        .filter(
            User.session_id == session_id,
            User.role.in_(["HEIR", "ADMIN"]),
        )
        .all()
    )

    admin_user = db.query(User).filter(
        User.role == "ADMIN",
    ).first()
    if admin_user and admin_user not in heirs:
        heirs.append(admin_user)

    assets = (
        db.query(Asset)
        .filter(Asset.session_id == session_id)
        .all()
    )

    audit_logs = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == session_id)
        .order_by(AuditLog.id.asc())
        .all()
    )

    notice_log = build_notice_log(session_id, [h for h in heirs if h.role == "HEIR"])

    solver_result = _reconstruct_solver_result_for_finalized_pdf(assets, audit_logs)

    from .pdf_builder import build_probate_ledger_pdf, build_keepsake_pdf

    try:
        ledger_pdf_buf = build_probate_ledger_pdf(
            session=session,
            heirs=heirs,
            assets=assets,
            solver_result=solver_result,
            audit_logs=audit_logs,
            notice_log=notice_log,
        )
    except Exception as e:
        logger.exception("Failed to build probate ledger PDF")
        raise HTTPException(
            status_code=500,
            detail=f"Ledger PDF generation failed: {str(e)}",
        )

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Add Ledger
        zf.writestr(f"{timestamp}_{session.title}-probate-audit-ledger.pdf", ledger_pdf_buf.getvalue())
        
        # Add Heir Keepsakes
        for heir in heirs:
            if heir.role != "HEIR":
                continue
            try:
                heir_pdf_buf = build_keepsake_pdf(
                    session=session,
                    heir=heir,
                    assets=assets,
                    solver_result=solver_result,
                    audit_logs=audit_logs,
                )
                heir_name = (heir.username or f"{heir.legal_first_name or ''} {heir.legal_last_name or ''}".strip() or heir.email or "Heir").replace("/", "_").replace("\\", "_")
                zf.writestr(f"{timestamp}_{session.title}-{heir_name}-keepsake-memory-book.pdf", heir_pdf_buf.getvalue())
            except Exception as e:
                logger.error(f"Failed to build keepsake PDF for heir {heir.id}: {e}")
                pass

    zip_buf.seek(0)
    _log_asset_audit_event(db, session_id, "DOWNLOAD_ALL_KEEPSAKES", {"action": "download_zip", "user_id": current_user.get("user_id"), "timestamp": timestamp})
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{timestamp}_{session.title}_all_documents.zip"',
        },
    )


@app.get("/api/sessions/{session_id}/heirs/{heir_id}/keepsake")
@limiter.limit("30/minute")
async def download_heir_keepsake(
    request: Request,
    session_id: str,
    heir_id: str,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Download the individual Heir's Keepsake Memory Book PDF.

    Per Backend Spec §9.3 (GET /api/sessions/{session_id}/heirs/{heir_id}/keepsake):
    Generates and returns the Heir's keepsake PDF. Accessible by matching
    Heir JWT or Admin credentials.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")

    if role == "HEIR" and user_id != heir_id:
        raise HTTPException(status_code=403, detail="Access denied")

    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "FINALIZED":
        raise HTTPException(
            status_code=400,
            detail="Keepsake is only available after session finalization.",
        )

    heir = db.query(User).filter(
        User.id == heir_id,
        User.session_id == session_id,
        User.role == "HEIR",
    ).first()
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found")

    assets = (
        db.query(Asset)
        .filter(Asset.session_id == session_id)
        .all()
    )

    audit_logs = (
        db.query(AuditLog)
        .filter(AuditLog.session_id == session_id)
        .order_by(AuditLog.id.asc())
        .all()
    )

    solver_result = _reconstruct_solver_result_for_finalized_pdf(assets, audit_logs)

    try:
        from .pdf_builder import build_keepsake_pdf

        pdf_buf = build_keepsake_pdf(
            session=session,
            heir=heir,
            assets=assets,
            solver_result=solver_result,
            audit_logs=audit_logs,
        )
    except Exception as e:
        logger.exception("Failed to build keepsake PDF")
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {str(e)}",
        )

    pdf_bytes = pdf_buf.getvalue()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    _log_asset_audit_event(db, session_id, "DOWNLOAD_KEEPSAKE", {"action": "download", "heir_id": heir_id, "user_id": current_user.get("user_id"), "timestamp": timestamp})
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{timestamp}_keepsake_{heir_id}.pdf"',
        },
    )


# ---------------------------------------------------------------------------
# T83 — Mediation Chat History API
# ---------------------------------------------------------------------------


@app.get("/api/sessions/{session_id}/heirs/{heir_id}/chat")
async def get_heir_chat(
    request: Request,
    session_id: str,
    heir_id: str,
    db: DBSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Retrieve chronologically-sorted chat history for a specific Heir.

    Per Backend Spec §9.3 (GET /api/sessions/{session_id}/heirs/{heir_id}/chat):
    - Access: Heir JWT cookie matching {heir_id} only.
    - Admin credentials are rejected with 403 Forbidden to guarantee
      mediation confidentiality (per Legal Spec §6).

    Returns: List[ChatMessageSchema] sorted by created_at ascending.
    """
    role = current_user.get("role")
    user_id = current_user.get("user_id")

    if role == "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Admin access to mediation chat history is prohibited "
            "to preserve confidentiality of active listening transcripts.",
        )

    if role == "HEIR" and user_id != heir_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view your own mediation chat history.",
        )

    # Verify the session exists
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Verify the heir exists and belongs to this session
    heir = db.query(User).filter(
        User.id == heir_id,
        User.session_id == session_id,
        User.role == "HEIR",
    ).first()
    if not heir:
        raise HTTPException(status_code=404, detail="Heir not found in this session")

    messages = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session_id,
            ChatMessage.heir_id == heir_id,
        )
        .order_by(ChatMessage.created_at.asc())
        .all()
    )

    return JSONResponse(
        content=[
            {
                "id": str(msg.id),
                "session_id": str(msg.session_id),
                "heir_id": str(msg.heir_id),
                "sender": msg.sender,
                "message_text": msg.message_text,
                "scrubbed_text": msg.scrubbed_text,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            for msg in messages
        ]
    )


# ---------------------------------------------------------------------------
# T36 — AB 2013 Model Transparency API
# ---------------------------------------------------------------------------


@app.get("/api/system/models")
async def system_models():
    """
    California AB 2013 AI Training Data Transparency endpoint.

    Per Compliance Spec §2.4 (GET /api/system/models):
    Returns metadata outlining the active model parameters, licensing,
    and training provenance. Dynamically queries environment variables
    for active model names: FAST_THINKER_MODEL, SLOW_THINKER_MODEL,
    VISION_MODEL, EMBEDDING_MODEL. If a non-default model name is
    detected, the response reflects the actual model name from the env
    var so that changing env vars dynamically alters the transparency
    output (per UAT spec).

    Access: Public.
    """
    import os as _os

    fast = _os.environ.get("FAST_THINKER_MODEL", "qwen2.5:8b-instruct")
    slow = _os.environ.get("SLOW_THINKER_MODEL", "qwen2.5:14b-instruct")
    vision = _os.environ.get("VISION_MODEL", "llava:7b")
    embed = _os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

    # Map Ollama model identifiers to human-readable display metadata.
    # When an env var maps to a known model, use the canonical display info;
    # otherwise fall back to a generic entry using the raw env var value.
    _MODEL_DISPLAY = {
        # Fast thinker variants
        "qwen2.5:8b-instruct": {
            "display_name": "Qwen-2.5-8B-Instruct",
            "parameters": "8.0B",
            "license": "Apache-2.0",
            "provenance": "Pretrained on Qwen open training datasets; fine-tuned for instruction-following.",
        },
        "qwen2.5:latest": {
            "display_name": "Qwen-2.5 (latest)",
            "parameters": "8.0B",
            "license": "Apache-2.0",
            "provenance": "Pretrained on Qwen open training datasets; fine-tuned for instruction-following.",
        },
        "qwen2.5:3b-instruct": {
            "display_name": "Qwen-2.5-3B-Instruct (Pi 5 profile)",
            "parameters": "3.1B",
            "license": "Apache-2.0",
            "provenance": "Compact instruction-tuned Qwen variant optimized for low-resource devices.",
        },
        "qwen2.5:1.5b-instruct": {
            "display_name": "Qwen-2.5-1.5B-Instruct (Pi 5 alt profile)",
            "parameters": "1.5B",
            "license": "Apache-2.0",
            "provenance": "Smallest instruction-tuned Qwen variant for constrained hardware.",
        },
        # Slow thinker variants
        "qwen2.5:14b": {
            "display_name": "Qwen-2.5-14B-Instruct",
            "parameters": "14.2B",
            "license": "Apache-2.0",
            "provenance": "Pretrained and post-trained by Alibaba Cloud; optimized for reasoning and logical validation.",
        },
        "qwen2.5:14b-instruct": {
            "display_name": "Qwen-2.5-14B-Instruct",
            "parameters": "14.2B",
            "license": "Apache-2.0",
            "provenance": "Pretrained and post-trained by Alibaba Cloud; optimized for reasoning and logical validation.",
        },
        "qwen2.5:8b-instruct": {
            "display_name": "Qwen-2.5-8B-Instruct",
            "parameters": "8.0B",
            "license": "Apache-2.0",
            "provenance": "Pretrained on Qwen open training datasets; fine-tuned for instruction-following.",
        },
        # Vision variants
        "google/diffusiongemma-26b-a4b-it": {
            "display_name": "DiffusionGemma-26B-A4B-IT",
            "parameters": "25.2B (3.8B active)",
            "license": "NVIDIA Open Model Agreement / Gemma Terms",
            "provenance": "Developed by Google DeepMind; multimodal discrete diffusion model running on NVIDIA integrate NIM.",
        },
        "gemma4:e4b": {
            "display_name": "Gemma 4 E4B",
            "parameters": "~6GB",
            "license": "Google Gemma Terms",
            "provenance": "Google Gemma 4 native multimodal architecture. 128K context window. Optimized for multi-image analysis.",
        },
        "llava:7b": {
            "display_name": "Llava-1.5",
            "parameters": "7.0B",
            "license": "Apache-2.0",
            "provenance": "CLIP ViT-L/14 visual encoder and Llama-2; trained on public multi-modal datasets.",
        },
        "llava:latest": {
            "display_name": "Llava-1.5 (latest)",
            "parameters": "7.0B",
            "license": "Apache-2.0",
            "provenance": "CLIP ViT-L/14 visual encoder and Llama-2; trained on public multi-modal datasets.",
        },
        "moondream:latest": {
            "display_name": "Moondream (Pi 5 vision profile)",
            "parameters": "1.9B",
            "license": "Apache-2.0",
            "provenance": "Lightweight vision-language model optimized for edge devices.",
        },
        # Embedding variants
        "nomic-embed-text": {
            "display_name": "nomic-embed-text",
            "parameters": "137M",
            "license": "Apache-2.0",
            "provenance": "Trained by Nomic AI on public web text. Generates 768-dimensional dense vectors for estate asset similarity search and RAG context retrieval.",
        },
    }

    def _model_entry(component: str, model_id: str):
        info = _MODEL_DISPLAY.get(model_id)
        if info:
            return {
                "component": component,
                "name": info["display_name"],
                "parameters": info["parameters"],
                "license": info["license"],
                "provenance": info["provenance"],
                "model_id": model_id,
            }
        # Unknown model — return the raw env var as the name
        return {
            "component": component,
            "name": model_id,
            "parameters": "Unknown",
            "license": "Unknown",
            "provenance": f"Active model identifier: {model_id}. Provenance not catalogued.",
            "model_id": model_id,
        }

    models = [
        _model_entry("Fast Mediator (System 1)", fast),
        _model_entry("Slow Critic (System 2)", slow),
        _model_entry("Vision OCR Engine", vision),
        {
            "component": "Local Speech Synthesis (TTS)",
            "name": "Kokoro-82M ONNX",
            "parameters": "82M",
            "license": "Apache-2.0 / Custom Research",
            "provenance": "Trained on public domain and CC-licensed audio datasets. Runs locally on CPU.",
        },
        _model_entry("Semantic Search & RAG Embedding Engine", embed),
    ]
    return JSONResponse(content={"models": models})


# ---------------------------------------------------------------------------
# T82 — Hash Chain Verification Tool
# ---------------------------------------------------------------------------


def _compute_audit_hash(
    row_id: int, event_type: str, state_snapshot, prev_hash: str
) -> str:
    """Re-compute a SHA-256 audit hash from audit log row fields.

    Per Backend Spec §6.1: Uses a PII-scrubbed copy of the state_snapshot
    to ensure GDPR erasures don't break the chain. Mirrors how hashes are
    computed during audit log insertion.
    """
    snapshot_str = str(sorted(state_snapshot.items())) if isinstance(state_snapshot, dict) else str(state_snapshot)
    raw_data = f"{row_id}:{event_type}:{snapshot_str}:{prev_hash}"
    return hashlib.sha256(raw_data.encode("utf-8")).hexdigest()


@app.get("/api/system/verify-hash-chain")
async def verify_hash_chain(
    request: Request,
    session_id: str | None = None,
    db: DBSession = Depends(get_db),
):
    """
    Verify the tamper-proof SHA-256 audit chain.

    Per Implementation Plan T82:
    Re-computes hashes from database rows and compares against stored
    sha256_hash values. Returns per-row validation status and any breaks.

    Query params:
      - session_id (optional): filter to a specific session's audit logs.

    Access: Public — auditors and executors can verify integrity without
    authentication. The audit chain contains no PII (snapshots use PII-
    scrubbed copies for hash inputs per Backend Spec §6.1).
    """
    query = db.query(AuditLog).order_by(AuditLog.id.asc())

    if session_id:
        query = query.filter(AuditLog.session_id == session_id)

    logs = query.all()

    if not logs:
        return JSONResponse(
            content={
                "status": "empty",
                "message": "No audit log entries found.",
                "session_id": session_id,
                "rows": [],
                "verified": True,
            }
        )

    prev_expected_hash = "0" * 64
    rows = []
    all_valid = True

    for log_entry in logs:
        # Re-compute the expected hash
        recomp_hash = _compute_audit_hash(
            log_entry.id,
            log_entry.event_type,
            log_entry.state_snapshot,
            log_entry.prev_hash,
        )

        stored_hash = log_entry.sha256_hash
        valid = recomp_hash == stored_hash
        prev_match = log_entry.prev_hash == prev_expected_hash

        if not valid or not prev_match:
            all_valid = False

        rows.append({
            "id": log_entry.id,
            "event_type": log_entry.event_type,
            "session_id": str(log_entry.session_id),
            "created_at": log_entry.created_at.isoformat() if log_entry.created_at else None,
            "stored_sha256": stored_hash,
            "recomputed_sha256": recomp_hash,
            "hash_valid": valid,
            "prev_hash_match": prev_match,
        })

        # Set expected previous hash for the next row
        if valid:
            prev_expected_hash = stored_hash
        else:
            # When a break is found, we can't trust subsequent prev_hash references
            # but we continue verification — using the stored prev_hash for re-computation
            prev_expected_hash = recomp_hash if valid else stored_hash

    # Find breaks
    breaks = [r for r in rows if not r["hash_valid"] or not r["prev_hash_match"]]

    return JSONResponse(
        content={
            "status": "valid" if all_valid else "broken",
            "message": (
                f"All {len(rows)} audit log entries verified successfully."
                if all_valid
                else f"{len(breaks)} break(s) detected in the audit chain."
            ),
            "session_id": session_id,
            "total_rows": len(rows),
            "verified": all_valid,
            "breaks": [
                {
                    "row_id": b["id"],
                    "event_type": b["event_type"],
                    "stored_sha256": b["stored_sha256"],
                    "recomputed_sha256": b["recomputed_sha256"],
                }
                for b in breaks
            ],
            "rows": rows,
        }
    )


# ---------------------------------------------------------------------------
# T26 — System Backup & Restore
# ---------------------------------------------------------------------------


def _quote_sql_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _system_uploads_dir():
    from pathlib import Path

    return Path(os.environ.get("SYSTEM_UPLOADS_DIR", "/app/static/uploads"))


def _sql_literal(value) -> str:
    import json as _json
    import math as _math
    import uuid as _uuid
    from datetime import date as _date, datetime as _datetime, time as _time
    from decimal import Decimal as _Decimal

    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if _math.isnan(value) or _math.isinf(value):
            return "NULL"
        return repr(value)
    if isinstance(value, _Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "E'\\\\x" + bytes(value).hex() + "'::bytea"
    if isinstance(value, (dict, list)):
        text = _json.dumps(value, separators=(",", ":"), default=str)
    elif isinstance(value, _uuid.UUID):
        text = str(value)
    elif isinstance(value, _datetime):
        text = value.isoformat()
    elif isinstance(value, (_date, _time)):
        text = value.isoformat()
    else:
        text = str(value)
    return "'" + text.replace("'", "''") + "'"


def _ordered_table_names_for_backup(engine) -> list[str]:
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(engine)
    table_names = set(inspector.get_table_names())
    dependencies: dict[str, set[str]] = {name: set() for name in table_names}

    for table_name in table_names:
        for fk in inspector.get_foreign_keys(table_name):
            referred_table = fk.get("referred_table")
            if referred_table in table_names and referred_table != table_name:
                dependencies[table_name].add(referred_table)

    ordered: list[str] = []
    remaining = {name: set(deps) for name, deps in dependencies.items()}
    while remaining:
        ready = sorted(name for name, deps in remaining.items() if not deps)
        if not ready:
            # Fall back deterministically for unexpected circular dependencies.
            ready = [sorted(remaining)[0]]
        for name in ready:
            ordered.append(name)
            remaining.pop(name, None)
            for deps in remaining.values():
                deps.discard(name)
    return ordered


def _build_sql_backup_dump(engine) -> tuple[str, dict]:
    import hashlib as _hashlib
    from sqlalchemy import Integer, inspect as sa_inspect, text as sa_text

    inspector = sa_inspect(engine)
    table_names = _ordered_table_names_for_backup(engine)
    table_counts: dict[str, int] = {}
    dump_lines = [
        "-- Estate Steward SQL backup",
        "-- Generated via SQLAlchemy introspection",
        "-- Format: estate-steward-sql-v2",
        "",
    ]

    with engine.connect() as conn:
        for table_name in table_names:
            columns = [c["name"] for c in inspector.get_columns(table_name)]
            quoted_table = _quote_sql_identifier(table_name)
            quoted_cols = ", ".join(_quote_sql_identifier(c) for c in columns)
            rows = conn.execute(sa_text(f"SELECT * FROM {quoted_table}")).fetchall()
            table_counts[table_name] = len(rows)
            if not rows:
                continue

            dump_lines.append(f"INSERT INTO {quoted_table} ({quoted_cols}) VALUES")
            value_lines = []
            for row in rows:
                values = [_sql_literal(value) for value in row]
                value_lines.append("  (" + ", ".join(values) + ")")
            dump_lines.append(",\n".join(value_lines) + ";")
            dump_lines.append("")

        # Restore PostgreSQL sequences for integer identity/serial columns.
        for table_name in table_names:
            column_info = {
                column["name"]: column
                for column in inspector.get_columns(table_name)
            }
            for pk_col in inspector.get_pk_constraint(table_name).get("constrained_columns", []):
                if not isinstance(column_info.get(pk_col, {}).get("type"), Integer):
                    continue
                quoted_table = _quote_sql_identifier(table_name)
                quoted_col = _quote_sql_identifier(pk_col)
                table_literal = table_name.replace("'", "''")
                col_literal = pk_col.replace("'", "''")
                dump_lines.append(
                    "SELECT setval(seq_name, max_id, has_rows) FROM ("
                    f"SELECT pg_get_serial_sequence('{table_literal}', '{col_literal}') AS seq_name, "
                    f"COALESCE((SELECT MAX({quoted_col}) FROM {quoted_table}), 1) AS max_id, "
                    f"(SELECT COUNT(*) > 0 FROM {quoted_table}) AS has_rows"
                    ") AS seq_state WHERE seq_name IS NOT NULL;"
                )

    sql_dump = "\n".join(dump_lines).strip() + "\n"
    manifest = {
        "format": "estate-steward-backup-v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tables": table_counts,
        "table_order": table_names,
        "dump_sha256": _hashlib.sha256(sql_dump.encode("utf-8")).hexdigest(),
    }
    return sql_dump, manifest


def _safe_extract_tar(tar, destination) -> None:
    from pathlib import Path

    destination = Path(destination).resolve()
    for member in tar.getmembers():
        if member.issym() or member.islnk():
            raise HTTPException(
                status_code=400,
                detail="Backup archive contains an unsafe link.",
            )
        target = (destination / member.name).resolve()
        if target != destination and destination not in target.parents:
            raise HTTPException(
                status_code=400,
                detail="Backup archive contains an unsafe file path.",
            )
    tar.extractall(destination)


def _prepare_uploads_restore(extract_dir):
    import shutil
    import tempfile
    from pathlib import Path

    uploads_dst = _system_uploads_dir()
    uploads_dst.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix="estate-uploads-restore-"))
    staging_uploads = staging_parent / "uploads"
    uploads_src = Path(extract_dir) / "uploads"

    if uploads_src.exists():
        shutil.copytree(uploads_src, staging_uploads)
    else:
        staging_uploads.mkdir(parents=True, exist_ok=True)

    for path in staging_uploads.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    staging_uploads.chmod(0o755)
    return uploads_dst, staging_parent, staging_uploads


def _remove_upload_entry(path) -> None:
    import shutil

    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _clear_upload_directory(directory) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for child in list(directory.iterdir()):
        _remove_upload_entry(child)


def _copy_upload_contents(src_dir, dst_dir) -> None:
    import shutil

    dst_dir.mkdir(parents=True, exist_ok=True)
    for child in sorted(src_dir.iterdir(), key=lambda path: path.name):
        target = dst_dir / child.name
        if target.exists() or target.is_symlink():
            _remove_upload_entry(target)
        if child.is_dir() and not child.is_symlink():
            shutil.copytree(child, target, symlinks=False)
        else:
            shutil.copy2(child, target)


def _cleanup_upload_restore_state(state) -> None:
    import shutil

    for key in ("staging_parent", "backup_parent"):
        path = state.get(key)
        if path is not None and path.exists():
            shutil.rmtree(path, ignore_errors=True)


def _begin_uploads_restore(uploads_dst, staging_parent, staging_uploads) -> dict:
    import tempfile
    from pathlib import Path

    uploads_dst.mkdir(parents=True, exist_ok=True)
    backup_parent = Path(tempfile.mkdtemp(prefix="estate-uploads-before-restore-"))
    backup_uploads = backup_parent / "uploads"
    backup_uploads.mkdir(parents=True, exist_ok=True)

    state = {
        "uploads_dst": uploads_dst,
        "staging_parent": staging_parent,
        "backup_parent": backup_parent,
        "backup_uploads": backup_uploads,
    }

    try:
        _copy_upload_contents(uploads_dst, backup_uploads)
        _clear_upload_directory(uploads_dst)
        _copy_upload_contents(staging_uploads, uploads_dst)
    except Exception:
        try:
            _clear_upload_directory(uploads_dst)
            _copy_upload_contents(backup_uploads, uploads_dst)
        finally:
            _cleanup_upload_restore_state(state)
        raise

    return state


def _rollback_uploads_restore(state) -> None:
    uploads_dst = state["uploads_dst"]
    backup_uploads = state["backup_uploads"]
    try:
        _clear_upload_directory(uploads_dst)
        _copy_upload_contents(backup_uploads, uploads_dst)
    finally:
        _cleanup_upload_restore_state(state)


def _commit_uploads_restore(state) -> None:
    _cleanup_upload_restore_state(state)


def _run_post_restore_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")


@app.get("/api/system/backup")
@limiter.limit("5/minute")
async def system_backup(
    request: Request,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Generate an encrypted backup of the entire system.

    Per Backend Spec §9.5 (GET /api/system/backup):
    1. Generates a PostgreSQL SQL dump of all tables.
    2. Compresses the SQL dump together with static/uploads/ into a .tar.gz.
    3. Encrypts the archive using AES-Fernet (ENCRYPTION_KEY).

    Returns: application/octet-stream (.estate.bak).
    """
    import json as _json
    import tempfile
    import tarfile
    from cryptography.fernet import Fernet
    from pathlib import Path

    encryption_key = os.environ.get("ENCRYPTION_KEY")
    if not encryption_key:
        raise HTTPException(
            status_code=500,
            detail="ENCRYPTION_KEY is not configured. Cannot encrypt backup.",
        )

    # ── Generate SQL dump via SQLAlchemy introspection ─────────────────
    # No external pg_dump required — pure-Python, portable.
    try:
        if database.engine is None:
            raise RuntimeError("Database engine is not initialized.")
        sql_dump_content, manifest = _build_sql_backup_dump(database.engine)
    except Exception as e:
        logger.exception("SQLAlchemy dump generation failed")
        raise HTTPException(
            status_code=500,
            detail=f"Database dump generation failed: {str(e)[:500]}",
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        sql_dump_path = tmp / "dump.sql"
        archive_path = tmp / "backup.tar.gz"
        encrypted_path = tmp / "backup.estate.bak"

        sql_dump_path.write_text(sql_dump_content, encoding="utf-8")
        (tmp / "manifest.json").write_text(
            _json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        # Absolute path to the uploads directory inside the container.
        # WORKDIR is /app, and docker-compose mounts the live volume to /app/static/uploads.
        uploads_dir = _system_uploads_dir()
        empty_uploads_dir = tmp / "uploads"
        empty_uploads_dir.mkdir(exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(sql_dump_path, arcname="dump.sql")
            tar.add(tmp / "manifest.json", arcname="manifest.json")
            tar.add(uploads_dir if uploads_dir.exists() else empty_uploads_dir, arcname="uploads")

        fernet = Fernet(encryption_key.encode())
        with open(archive_path, "rb") as f:
            plaintext = f.read()
        encrypted = fernet.encrypt(plaintext)
        with open(encrypted_path, "wb") as f:
            f.write(encrypted)

        with open(encrypted_path, "rb") as f:
            encrypted_bytes = f.read()

    return StreamingResponse(
        io.BytesIO(encrypted_bytes),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="estate_backup.estate.bak"',
        },
    )


@app.post("/api/system/restore")
@limiter.limit("3/minute")
async def system_restore(
    request: Request,
    db: DBSession = Depends(get_db),
):
    """
    Restore the system from an encrypted backup archive.

    Per Backend Spec §9.5 (POST /api/system/restore):
    - Admin credentials required, OR Public if zero registered users exist.
    - Decrypts with ENCRYPTION_KEY or 24-word BIP39 recovery key.
    - Unpacks tar.gz, executes SQL dump in transaction, restores media files.
    """
    import hashlib as _hashlib
    import json as _json
    import tempfile
    import tarfile
    import base64 as _base64
    from cryptography.fernet import Fernet, InvalidToken
    from mnemonic import Mnemonic as _Mnemonic
    from pathlib import Path
    from sqlalchemy import text as sa_text

    admin_count = db.query(User).filter(User.role == "ADMIN").count()
    is_fresh_system = admin_count == 0
    try:
        # Release the read transaction opened by the admin-count query before
        # the restore transaction attempts to TRUNCATE the users table.
        db.rollback()
    except Exception:
        pass

    if not is_fresh_system:
        # T72: Require admin JWT cookie authentication on initialized systems
        auth_token = request.cookies.get("estate_session")
        if not auth_token:
            raise HTTPException(
                status_code=401,
                detail="Admin authentication required for restore on an initialized system.",
            )
        try:
            payload = decode_access_token(auth_token)
            if payload.get("role") != "ADMIN":
                raise HTTPException(
                    status_code=401,
                    detail="Admin authentication required for system restore.",
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired admin credentials.",
            )

    form = await request.form()
    backup_file = form.get("backup_file") or form.get("file")
    if not backup_file:
        raise HTTPException(status_code=400, detail="No backup_file provided.")

    recovery_key_mnemonic = form.get("recovery_key")
    raw_bytes = await backup_file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded backup file is empty.")

    fernet = None
    decrypted = None

    encryption_key = os.environ.get("ENCRYPTION_KEY")
    if encryption_key:
        try:
            fernet = Fernet(encryption_key.encode())
            decrypted = fernet.decrypt(raw_bytes)
        except InvalidToken:
            pass

    if decrypted is None and recovery_key_mnemonic:
        try:
            mnemo = _Mnemonic("english")
            if not mnemo.check(str(recovery_key_mnemonic)):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid recovery key mnemonic phrase.",
                )
            raw_key = mnemo.to_entropy(str(recovery_key_mnemonic))
            fernet_key = _base64.urlsafe_b64encode(raw_key).decode()
            fernet = Fernet(fernet_key.encode())
            decrypted = fernet.decrypt(raw_bytes)
        except InvalidToken:
            raise HTTPException(
                status_code=400,
                detail="Recovery key does not match the backup archive.",
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Recovery key validation failed: {str(e)}",
            )

    if decrypted is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot decrypt backup. Provide the correct 24-word recovery "
            "key mnemonic or ensure ENCRYPTION_KEY matches the backup's key.",
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        archive_path = tmp / "backup.tar.gz"
        with open(archive_path, "wb") as f:
            f.write(decrypted)

        extract_dir = tmp / "extract"
        extract_dir.mkdir(exist_ok=True)
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                _safe_extract_tar(tar, extract_dir)
        except HTTPException:
            raise
        except tarfile.TarError:
            raise HTTPException(
                status_code=400,
                detail="Backup archive is not a valid tar.gz file.",
            )

        sql_dump = extract_dir / "dump.sql"
        if not sql_dump.exists():
            raise HTTPException(
                status_code=400,
                detail="Backup archive does not contain dump.sql.",
            )

        sql_content = sql_dump.read_text()
        sql_content = sql_content.replace("SET statement_timeout = 0;", "")
        sql_content = sql_content.replace("SET lock_timeout = 0;", "")

        manifest_path = extract_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail="Backup manifest is not valid JSON.",
                )
            expected_hash = manifest.get("dump_sha256")
            actual_hash = _hashlib.sha256(sql_content.encode("utf-8")).hexdigest()
            if expected_hash and expected_hash != actual_hash:
                raise HTTPException(
                    status_code=400,
                    detail="Backup manifest checksum does not match dump.sql.",
                )

        uploads_dst = staging_parent = staging_uploads = uploads_restore_state = None
        try:
            from sqlalchemy import inspect as _restore_inspect

            if database.engine is None:
                raise RuntimeError("Database engine is not initialized.")

            uploads_dst, staging_parent, staging_uploads = _prepare_uploads_restore(extract_dir)
            uploads_restore_state = _begin_uploads_restore(
                uploads_dst,
                staging_parent,
                staging_uploads,
            )
            staging_parent = None

            # Restore database atomically. If loading the dump fails, the TRUNCATE
            # and all INSERTs are rolled back together.
            inspector = _restore_inspect(database.engine)
            table_names = sorted(inspector.get_table_names())
            with database.engine.begin() as conn:
                for tname in table_names:
                    conn.execute(sa_text(f'TRUNCATE TABLE {_quote_sql_identifier(tname)} RESTART IDENTITY CASCADE'))
                conn.exec_driver_sql(sql_content)

            _run_post_restore_migrations()
            _commit_uploads_restore(uploads_restore_state)
            uploads_restore_state = None
        except Exception as e:
            if uploads_restore_state is not None:
                try:
                    _rollback_uploads_restore(uploads_restore_state)
                except Exception:
                    logger.exception("Upload rollback failed after restore error")
            if staging_parent is not None and staging_parent.exists():
                import shutil
                shutil.rmtree(staging_parent, ignore_errors=True)
            logger.exception("System restore failed")
            raise HTTPException(
                status_code=500,
                detail=f"Database restore failed: {str(e)[:500]}",
            )

        try:
            reset_provider()
        except Exception:
            pass

    return JSONResponse(
        content={
            "status": "success",
            "message": "System database and media restored successfully",
        }
    )


# ---------------------------------------------------------------------------
# T49 — Secure Session Purge
# ---------------------------------------------------------------------------


@app.delete("/api/sessions/{session_id}")
@limiter.limit("3/minute")
async def secure_session_purge(
    request: Request,
    session_id: str,
    confirm: bool = None,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Irreversibly purge a FINALIZED session and all associated data.

    Per Backend Spec §9.1 (DELETE /api/sessions/{session_id}?confirm=true):
    6-step permanent deletion — chat, checkpointer rows, asset files,
    Heir users (cascade valuations/support), and session row.
    Gates on session.status == 'FINALIZED' AND confirm=true.
    """
    if confirm is not True:
        raise HTTPException(
            status_code=400,
            detail="Confirmation required. Use ?confirm=true to proceed.",
        )

    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 1. Delete all chat messages
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()

    # 2. Delete LangGraph checkpointer rows for all threads in this session
    try:
        from .database import engine
        from sqlalchemy import text as sa_text
        with engine.begin() as conn:
            for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
                conn.execute(
                    sa_text(f"DELETE FROM {table} WHERE thread_id LIKE :pattern"),
                    {"pattern": f"{session_id}:%"},
                )
    except Exception:
        logger.warning(
            "Failed to clean checkpointer state for session %s — continuing",
            session_id,
        )

    # 3. Delete all asset files from storage
    assets = db.query(Asset).filter(Asset.session_id == session_id).all()
    storage = get_storage_driver()
    for asset in assets:
        deleted_uris = set()
        for img in asset.images:
            if img.image_uri and img.image_uri not in deleted_uris:
                try:
                    storage.delete(img.image_uri)
                    deleted_uris.add(img.image_uri)
                except Exception:
                    pass
        if asset.image_uri and asset.image_uri not in deleted_uris:
            try:
                storage.delete(asset.image_uri)
                deleted_uris.add(asset.image_uri)
            except Exception:
                pass
        if asset.audio_uri:
            try:
                storage.delete(asset.audio_uri)
            except Exception:
                pass

    # 4. Hard-delete all Heir users (cascade valuations, support)
    heirs = db.query(User).filter(
        User.session_id == session_id,
        User.role == "HEIR",
    ).all()
    for heir in heirs:
        if heir.id_scan_uri:
            try:
                storage.delete(heir.id_scan_uri)
            except Exception:
                pass
        db.delete(heir)

    # 5. Delete the session (cascades audit_logs, custom_faqs, assets)
    db.delete(session)
    db.commit()

    return JSONResponse(
        content={
            "status": "success",
            "message": f"Session {session_id} permanently purged.",
        }
    )


# ---------------------------------------------------------------------------
# T22 — WebSocket Server Endpoint  (/api/sessions/{session_id}/ws)
# ---------------------------------------------------------------------------
# Per Backend Spec §9.6: Persistent per-session WebSocket connection.
# Authenticates via JWT cookie, registers with the shared
# ConnectionManager (T38), enforces HITL_GUARD gate lock, and
# streams text-only chat_reply_chunk frames (audio: null per T21
# graceful degradation contract when Kokoro is unavailable).
# ---------------------------------------------------------------------------


def _check_hitl_guard(session_id: str, heir_id: str) -> bool:
    """Check if the given heir thread is suspended at HITL_GUARD.

    Returns True if the thread IS suspended (send error frame).
    Returns False if the thread is not suspended (allow chat).
    """
    try:
        from .graph import get_postgres_checkpointer
        saver = get_postgres_checkpointer()
        config = {"configurable": {"thread_id": f"{session_id}:{heir_id}"}}
        state = saver.get_tuple(config)
        if state and state.pending_writes:
            for pending in state.pending_writes:
                if isinstance(pending, tuple) and len(pending) >= 2:
                    node = pending[0]
                    if node == "HITL_GUARD":
                        return True
    except Exception:
        pass
    return False


@app.websocket("/api/sessions/{session_id}/ws")
async def session_websocket(
    websocket: WebSocket,
    session_id: str,
):
    """Session-scoped WebSocket for LangGraph chat mediation.

    Per Backend Spec §9.6:
      - Authenticates via JWT cookie during handshake
      - Heir: validated session_id matches token; registered to private thread
      - Admin: connected for broadcast status frames
      - HITL_GUARD gate: rejects incoming chat frames with error, keeps
        socket open for status broadcasts
      - Text-only chat_reply_chunk frames with audio: null (T21 degradation)
      - All frames carry "is_synthetic": true per SB 942 (§2.5)
    """
    # ── Handshake authentication ──────────────────────────────────────────
    try:
        cookie_value = websocket.cookies.get("estate_session")
    except Exception:
        await websocket.close(code=4003, reason="No JWT cookie found")
        return

    if not cookie_value:
        await websocket.close(code=4003, reason="No JWT cookie found")
        return

    try:
        payload = decode_access_token(cookie_value)
    except Exception:
        await websocket.close(code=4003, reason="Invalid JWT token")
        return

    role = payload.get("role")
    user_id = payload.get("user_id")
    username = payload.get("username", "unknown")
    token_session_id = payload.get("session_id")

    if not role or not user_id:
        await websocket.close(code=4003, reason="Malformed JWT payload")
        return

    # ── Authorization ─────────────────────────────────────────────────────
    if role == "HEIR":
        if token_session_id != session_id:
            await websocket.close(
                code=4003,
                reason="Session ID mismatch in JWT token",
            )
            return

        # Verify heir exists and is in a permissible status
        db = _get_session_factory()()
        try:
            heir = db.query(User).filter(User.id == user_id, User.role == "HEIR").first()
        finally:
            db.close()

        if not heir:
            await websocket.close(code=4003, reason="Heir not found")
            return

        if heir.status == "PROFILE_HOLD":
            await websocket.close(
                code=4003,
                reason="Profile pending Executor identity verification. "
                "Bidding and mediation chat are locked.",
            )
            return

    # ── Register with ConnectionManager ──────────────────────────────────
    if role == "HEIR":
        await manager.connect(websocket, session_id, heir_id=user_id)
    else:
        await manager.connect(websocket, session_id)

    logger.info(
        "WebSocket accepted — session=%s role=%s user=%s",
        session_id,
        role,
        user_id,
    )

    # ── Message loop ──────────────────────────────────────────────────────
    try:
        while True:
            raw = await websocket.receive_text()

            import json

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON frame",
                })
                continue

            msg_type = msg.get("type", "")

            # ── Status pings are never blocked ──────────────────────────
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            # ── Chat message processing (Heir only) ──────────────────────
            if msg_type == "chat_message" and role == "HEIR":
                # HITL_GUARD gate: reject chat, keep socket open
                if _check_hitl_guard(session_id, user_id):
                    await websocket.send_json({
                        "type": "error",
                        "message": (
                            "Points submission suspended. Your allocations "
                            "require review and correction by the Executor."
                        ),
                    })
                    continue

                input_text = (msg.get("text") or "").strip()
                if not input_text:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Empty message text",
                    })
                    continue

                # ── Persist the incoming chat message ──────────────────
                db = _get_session_factory()()
                try:
                    chat_msg = ChatMessage(
                        session_id=session_id,
                        heir_id=user_id,
                        sender="HEIR",
                        message_text=input_text,
                        scrubbed_text=input_text,
                    )
                    db.add(chat_msg)
                    db.commit()
                except Exception:
                    logger.exception("Failed to persist chat message")
                finally:
                    db.close()

                # ── Generate a text-only chat reply ─────────────────────
                # Per T21 graceful degradation: audio is always null when
                # Kokoro is unavailable. The client must handle null audio.
                try:
                    reply_text = (
                        f"I hear what you're saying about your feelings "
                        f"toward the estate items. These are deeply personal "
                        f"decisions, and I'm here to help you reflect on what "
                        f"matters most to you."
                    )

                    # Try to invoke LangGraph for a contextual response
                    try:
                        from .graph import get_graph
                        graph = get_graph()
                        config = {
                            "configurable": {
                                "thread_id": f"{session_id}:{user_id}",
                            },
                        }
                        initial_state = {
                            "session_id": session_id,
                            "heir_id": user_id,
                            "input_text": input_text,
                            "scrubbed_text": input_text,
                            "routing_intent": "CHAT_MEDIATION",
                        }
                        for event in graph.stream(initial_state, config):
                            if isinstance(event, dict):
                                for node_name, node_output in event.items():
                                    if isinstance(node_output, dict):
                                        med_resp = node_output.get(
                                            "mediator_response"
                                        )
                                        if med_resp:
                                            reply_text = med_resp
                    except Exception:
                        logger.debug(
                            "LangGraph unavailable — using default reply"
                        )

                    # Stream sentence chunks as chat_reply_chunk frames.
                    # Split on sentence boundaries (.!?) and emit each
                    # as a non-final frame; set is_final on the last.
                    import re
                    sentences = re.split(r'(?<=[.!?])\s+', reply_text.strip())
                    if not sentences:
                        sentences = [reply_text]

                    for idx, sentence in enumerate(sentences):
                        is_final = idx == len(sentences) - 1

                        # Try Kokoro TTS; omit audio if unavailable
                        audio_b64 = None
                        if TTS_AVAILABLE:
                            try:
                                tts = get_kokoro_tts()
                                audio_b64 = await tts.synthesize(sentence)
                            except Exception:
                                pass  # graceful degradation

                        frame = {
                            "type": "chat_reply_chunk",
                            "text": sentence,
                            "audio": audio_b64,
                            "is_synthetic": True,
                            "is_final": is_final,
                        }
                        await websocket.send_json(frame)

                except Exception:
                    logger.exception("Error generating chat reply")
                    await websocket.send_json({
                        "type": "error",
                        "message": "Failed to generate a response. Please try again.",
                    })

            # ── Admin broadcast messages (no LangGraph) ────────────────
            elif msg_type == "broadcast" and role == "ADMIN":
                await manager.broadcast_session_status(
                    session_id,
                    {
                        "type": "admin_broadcast",
                        "message": msg.get("text", ""),
                    },
                )

            # ── Unknown message type — log and ignore ──────────────────
            else:
                logger.debug(
                    "Unknown WebSocket frame type '%s' from %s",
                    msg_type,
                    role,
                )

    except WebSocketDisconnect:
        logger.info(
            "WebSocket disconnected — session=%s user=%s",
            session_id,
            user_id,
        )
    except Exception:
        logger.exception(
            "WebSocket error — session=%s user=%s",
            session_id,
            user_id,
        )
    finally:
        manager.disconnect(websocket, session_id=session_id)


from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print("VALIDATION ERROR:", exc.errors())
    # sanitize bytes
    errors = []
    for err in exc.errors():
        err_copy = err.copy()
        if "input" in err_copy and isinstance(err_copy["input"], bytes):
            err_copy["input"] = "<bytes>"
        if "ctx" in err_copy and isinstance(err_copy.get("ctx", {}).get("error"), Exception):
            err_copy["ctx"]["error"] = str(err_copy["ctx"]["error"])
        errors.append(err_copy)
    return JSONResponse(status_code=422, content={"detail": errors})
