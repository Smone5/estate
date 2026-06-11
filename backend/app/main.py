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
from .models import User, Session as SessionModel, Asset, Valuation, SupportRequest, CustomFAQ
from .websocket_manager import manager
from .services.storage import get_storage_driver, preprocess_image
from .services.llm_provider import get_provider, reset_provider
from .services.smtp_service import send_email_background, Attachment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Perform startup database initialization with retry loop."""
    logger.info("Starting Estate Steward backend...")
    init_db()
    logger.info("Startup complete.")
    yield
    logger.info("Shutting down.")


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
