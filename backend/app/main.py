"""
The Estate Steward — FastAPI application entry point.

Per DB Spec §6.3: init_db() is called at startup with a retry loop
that prevents crashes when the PostgreSQL container starts slower
than the API container.

T10: Exposes core auth and onboarding endpoints with rate limiting.
"""

import logging
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
from .models import User, Session as SessionModel, Asset, Valuation
from .websocket_manager import manager
from .services.storage import get_storage_driver, preprocess_image
from .services.llm_provider import get_provider, reset_provider

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