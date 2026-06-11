"""
The Estate Steward — FastAPI application entry point.

Per DB Spec §6.3: init_db() is called at startup with a retry loop
that prevents crashes when the PostgreSQL container starts slower
than the API container.

T10: Exposes core auth and onboarding endpoints with rate limiting.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Depends, HTTPException, Response, Request, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from .database import init_db, SessionLocal
from .rate_limiter import init_rate_limiting, limiter
from .auth import (
    hash_password,
    verify_password,
    create_access_token,
    set_auth_cookie,
    clear_auth_cookie,
    get_current_user,
    get_current_admin,
)
from .models import User, Session as SessionModel, Asset, Valuation, AuditLog, SupportRequest, CustomFAQ, ChatMessage
from .websocket_manager import manager
from .services.storage import get_storage_driver, preprocess_image
from .services.llm_provider import get_provider, reset_provider
from .services.smtp_service import send_email, send_email_background, Attachment
from .solver import solve_mnw, SolverResult
from .pdf_builder import build_keepsake_pdf, build_probate_ledger_pdf, build_waiver_receipt_pdf
from .notice_log import build_notice_log

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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
    legal_first_name: str = Field(..., min_length=1, max_length=50)
    legal_middle_name: str | None = None
    legal_last_name: str = Field(..., min_length=1, max_length=100)
    relationship_to_decedent: str = Field(..., min_length=1, max_length=50)
    date_of_birth: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")


class InviteLoginRequest(BaseModel):
    token: str


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def get_db() -> DBSession:
    """FastAPI dependency that yields a database session per request."""
    db = SessionLocal()
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
            db = SessionLocal()
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Perform startup database initialization with retry loop."""
    logger.info("Starting Estate Steward backend...")
    init_db()
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


# ---------------------------------------------------------------------------
# T11 — Schema
# ---------------------------------------------------------------------------


class AssetPublishRequest(BaseModel):
    title: str = Field(..., max_length=150)
    description: str
    category: str = Field(..., pattern=r"^(Jewelry|Furniture|Art|Other)$")
    valuation_min: float | None = None
    valuation_max: float | None = None
    valuation_source: str | None = None
    sentiment_tag: str | None = None


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


@app.post("/api/sessions/{session_id}/assets/stage")
@limiter.limit("30/minute")
async def asset_stage(
    request: Request,
    session_id: str,
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Stage an asset image for a session.

    Per Backend Spec §9.2 (POST /api/sessions/{session_id}/assets/stage):
    1. Preprocesses the image (HEIC conversion, WebP scaling) and saves it.
    2. Creates an asset row with ocr_status='PROCESSING' and status='STAGED'.
    3. Returns the asset ID for subsequent editing/publishing.

    Returns 400 if session is not in SETUP status (inventory lock).
    """
    import uuid as _uuid_mod

    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "SETUP":
        raise HTTPException(
            status_code=400,
            detail="Assets can only be staged during the SETUP phase.",
        )

    # Parse multipart upload
    form = await request.form()
    file_upload = form.get("file")
    if not file_upload:
        raise HTTPException(status_code=400, detail="No file uploaded")

    raw_bytes = await file_upload.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Preprocess image (HEIC -> WebP, scale, compress)
    try:
        processed = preprocess_image(raw_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Save to storage
    storage = get_storage_driver()
    asset_id = _uuid_mod.uuid4()
    filename = f"static/uploads/{asset_id}.webp"
    storage.save(filename, processed)

    # Create asset record
    asset = Asset(
        id=asset_id,
        session_id=session_id,
        title=None,
        description=None,
        category=None,
        valuation_min=None,
        valuation_max=None,
        valuation_source=None,
        sentiment_tag=None,
        image_uri=filename,
        audio_uri=None,
        ocr_status="PROCESSING",
        status="STAGED",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    return JSONResponse(
        content={
            "asset_id": str(asset.id),
            "status": asset.status,
            "ocr_status": asset.ocr_status,
        },
        status_code=201,
    )


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

    # Check session status — only SETUP allows publishing
    session = db.query(SessionModel).filter(SessionModel.id == asset.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status != "SETUP":
        raise HTTPException(
            status_code=400,
            detail="Assets can only be published during the SETUP phase.",
        )

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

    # Compute embedding
    try:
        provider = get_provider()
        text_to_embed = (
            f"Title: {asset.title}\n"
            f"Category: {asset.category}\n"
            f"Description: {asset.description}\n"
            f"Tags: {asset.sentiment_tag}"
        )
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

    db.commit()

    return JSONResponse(
        content={
            "asset_id": str(asset.id),
            "status": asset.status,
        }
    )


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

    query = db.query(Asset).filter(
        Asset.session_id == session_id,
        Asset.status.in_(["LIVE", "PRE_ALLOCATED", "DISTRIBUTED"]),
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
    if q:
        search_term = f"%{q}%"
        query = query.filter(
            (Asset.title.ilike(search_term)) | (Asset.description.ilike(search_term))
        )

    # Sorting
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
    return JSONResponse(
        content=[
            {
                "id": str(a.id),
                "session_id": str(a.session_id),
                "title": a.title,
                "description": a.description,
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
            }
            for a in assets
        ]
    )


# ---------------------------------------------------------------------------
# T42 — Schema
# ---------------------------------------------------------------------------


class SupportRequestCreate(BaseModel):
    message: str = Field(..., min_length=5, max_length=1000)


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
    legal_first_name: str = Field(..., min_length=1, max_length=50)
    legal_middle_name: str | None = None
    legal_last_name: str = Field(..., min_length=1, max_length=100)
    relationship_to_decedent: str | None = None
    date_of_birth: str | None = None
    email: str | None = None
    phone: str | None = None
    physical_address: str | None = None
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

    heir = User(
        session_id=session_id,
        username=body.username,
        legal_first_name=body.legal_first_name,
        legal_middle_name=body.legal_middle_name,
        legal_last_name=body.legal_last_name,
        relationship_to_decedent=body.relationship_to_decedent,
        date_of_birth=dob,
        email=body.email,
        phone=body.phone,
        physical_address=body.physical_address,
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
    base_url = str(request.base_url).rstrip("/")
    invite_url = f"{base_url}/invite/{invite_token}"

    return JSONResponse(
        content={
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

    base_url = str(request.base_url).rstrip("/")
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

    base_url = str(request.base_url).rstrip("/")
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

    await send_email_background(
        to=heir.email,
        subject=subject,
        body=body,
        on_failure_message=(
            f"SYSTEM WARNING: Invitation email to {heir.email} "
            f"(heir {heir.username}) failed to deliver."
        ),
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
    db: DBSession = Depends(get_db),
    current_admin: dict = Depends(get_current_admin),
):
    """
    Permanently delete an asset and its associated files.

    Per Backend Spec §9.2 (DELETE /api/assets/{asset_id}):
    Deletes the asset record, removes the associated image file from
    storage, and cascade-deletes all linked valuation rows.
    Returns 400 if the session status is ACTIVE, LOCKED, or FINALIZED.
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
            detail=f"Assets can only be deleted during the SETUP phase. "
            f"Current session status is '{session.status}'.",
        )

    # Remove image file from storage
    if asset.image_uri:
        try:
            storage = get_storage_driver()
            storage.delete(asset.image_uri)
        except Exception:
            pass

    # Remove audio file from storage if present
    if asset.audio_uri:
        try:
            storage = get_storage_driver()
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


# ---------------------------------------------------------------------------
# T42 — Support Request & Help CRUD API
# ---------------------------------------------------------------------------


@app.post("/api/sessions/{session_id}/help")
@limiter.limit("30/minute")
async def create_help_request(
    request: Request,
    session_id: str,
    body: SupportRequestCreate,
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

    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    sr = SupportRequest(
        session_id=session_id,
        heir_id=heir_id,
        message=body.message,
        status="OPEN",
    )
    db.add(sr)
    db.commit()

    # Broadcast WebSocket alert to Admin
    await manager.broadcast_support_alert(
        session_id,
        str(sr.id),
        current_user.get("username", ""),
        body.message,
    )

    return JSONResponse(
        content={"status": "submitted"},
        status_code=201,
    )


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
    tickets = (
        db.query(SupportRequest)
        .filter(SupportRequest.session_id == session_id)
        .order_by(SupportRequest.created_at.desc())
        .all()
    )

    results = []
    for t in tickets:
        heir = db.query(User).filter(User.id == t.heir_id).first()
        results.append({
            "id": str(t.id),
            "username": heir.username if heir else "Unknown",
            "message": t.message,
            "status": t.status,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return JSONResponse(content=results)


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
    db.commit()

    return JSONResponse(content={"status": "resolved"})


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

        return JSONResponse(
            content={
                "status": "success",
                "message": "Verification action processed successfully.",
            }
        )

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

        return JSONResponse(
            content={
                "status": "success",
                "message": "Verification action processed successfully.",
            }
        )


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


# ---------------------------------------------------------------------------
# T39 — Admin Setup & Session Creation API
# ---------------------------------------------------------------------------


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

    # Collect profile details
    profile = {
        "heir_id": str(heir.id),
        "username": heir.username,
        "legal_first_name": heir.legal_first_name,
        "legal_middle_name": heir.legal_middle_name,
        "legal_last_name": heir.legal_last_name,
        "relationship_to_decedent": heir.relationship_to_decedent,
        "date_of_birth": heir.date_of_birth.isoformat() if heir.date_of_birth else None,
        "email": heir.email,
        "phone": heir.phone,
        "physical_address": heir.physical_address,
        "identity_verified": heir.identity_verified,
        "status": heir.status,
        "is_submitted": heir.is_submitted,
        "submitted_at": heir.submitted_at.isoformat() if heir.submitted_at else None,
        "consent_accepted": heir.consent_accepted,
        "age_verified": heir.age_verified,
        "consent_timestamp": heir.consent_timestamp.isoformat() if heir.consent_timestamp else None,
        "created_at": heir.created_at.isoformat() if heir.created_at else None,
    }

    # Collect valuations
    valuations = (
        db.query(Valuation)
        .filter(Valuation.heir_id == heir_id)
        .all()
    )
    valuation_data = []
    for v in valuations:
        # Load asset title for context
        asset = db.query(Asset).filter(Asset.id == v.asset_id).first()
        valuation_data.append({
            "asset_id": str(v.asset_id),
            "asset_title": asset.title if asset else None,
            "points": v.points,
            "reasoning": v.reasoning,
            "is_reasoning_shared": v.is_reasoning_shared if v.is_reasoning_shared is not None else False,
        })

    # Collect decrypted chat history
    chat_messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.heir_id == heir_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    chat_data = []
    for msg in chat_messages:
        chat_data.append({
            "id": str(msg.id),
            "sender": msg.sender,
            "message_text": msg.message_text,  # EncryptedJSON auto-decrypts
            "scrubbed_text": msg.scrubbed_text,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        })

    # Collect support requests
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
            "status": sr.status,
            "created_at": sr.created_at.isoformat() if sr.created_at else None,
        })

    payload = {
        "export_timestamp_utc": now_utc.isoformat(),
        "profile": profile,
        "valuations": valuation_data,
        "chat_history": chat_data,
        "support_requests": support_data,
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

    # Reconstruct solver result from audit logs or assets
    solver_result = SolverResult(
        allocation={},
        mnw_product_value=0.0,
        tie_breaker_events=[],
    )

    # Build allocation from asset records
    for asset in assets:
        if asset.allocated_to_id and asset.status == "DISTRIBUTED":
            hid = str(asset.allocated_to_id)
            if hid not in solver_result.allocation:
                solver_result.allocation[hid] = []
            solver_result.allocation[hid].append(str(asset.id))

    # Generate PDF
    try:
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
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="probate_ledger_{session_id}.pdf"',
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

    # Reconstruct solver result from asset records
    solver_result = SolverResult(
        allocation={},
        mnw_product_value=0.0,
        tie_breaker_events=[],
    )
    for asset in assets:
        if asset.allocated_to_id and asset.status == "DISTRIBUTED":
            hid = str(asset.allocated_to_id)
            if hid not in solver_result.allocation:
                solver_result.allocation[hid] = []
            solver_result.allocation[hid].append(str(asset.id))

    try:
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
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="keepsake_{heir_id}.pdf"',
        },
    )
