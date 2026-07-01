"""
JWT authentication utilities for The Estate Steward.

Provides:
- Argon2 password hashing and verification
- JWT token creation and verification
- FastAPI dependency for extracting current user from HTTP-only cookies
- Cookie response helpers

Per Backend Spec §6.3: Admins use Argon2 credentials; Heirs authenticate
via single-use UUID invite tokens that grant HTTP-only JWT cookies.

Per Backend Spec §4: JWTPayload carries user_id, username, role (ADMIN|HEIR),
session_id (None for Admins), and exp.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, Header, HTTPException, Response
from sqlalchemy.orm import Session as DBSession

from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# Argon2 hasher with reasonable defaults for Raspberry Pi 5
_ph = PasswordHasher()

# JWT configuration
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRATION_MINUTES = int(os.environ.get("JWT_EXPIRATION_MINUTES", "1440"))  # 24 hours


def _get_jwt_secret() -> str:
    """Retrieve JWT secret at call time, raising a clear error if not configured."""
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise ValueError("JWT_SECRET environment variable is not set.")
    return secret


# ---------------------------------------------------------------------------
# Argon2 password hashing
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed: str) -> bool:
    """Verify a plaintext password against an Argon2 hash."""
    try:
        return _ph.verify(hashed, plain_password)
    except VerifyMismatchError:
        return False


# ---------------------------------------------------------------------------
# JWT token creation
# ---------------------------------------------------------------------------


def create_access_token(
    user_id: str,
    username: str,
    role: str,
    session_id: Optional[str] = None,
) -> str:
    """
    Create a signed JWT for the given user.

    Args:
        user_id: UUID of the user.
        username: Display username.
        role: 'ADMIN' or 'HEIR'.
        session_id: Session UUID (None for Admins).

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "session_id": session_id,
        "exp": now + timedelta(minutes=_JWT_EXPIRATION_MINUTES),
        "iat": now,
    }
    secret = _get_jwt_secret()
    return jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT, returning the payload dict.

    Raises:
        JWTError: If token is invalid or expired.
    """
    secret = _get_jwt_secret()
    return jwt.decode(token, secret, algorithms=[_JWT_ALGORITHM])


# ---------------------------------------------------------------------------
# FastAPI dependency: extract current user from cookie
# ---------------------------------------------------------------------------


# Role-scoped cookie names. ADMIN and HEIR get distinct cookies so the same
# browser can hold an active session for each role at once (e.g. one tab on
# /admin, another on /dashboard) without one login silently evicting the
# other. `role=None` keeps the original single-cookie name for callers that
# don't care (kept for backward compatibility with existing direct calls/tests).
_ROLE_COOKIE = {"ADMIN": "estate_admin_session", "HEIR": "estate_heir_session"}
_LEGACY_COOKIE = "estate_session"


def set_auth_cookie(response: Response, token: str, role: Optional[str] = None) -> None:
    """
    Set the HTTP-only JWT session cookie on a response.

    Per Backend Spec §6.3: Secure, HTTP-only cookie. Pass `role` ("ADMIN" or
    "HEIR") so the cookie is scoped to that role; omitting it falls back to
    the legacy shared cookie name.
    """
    response.set_cookie(
        key=_ROLE_COOKIE.get(role, _LEGACY_COOKIE),
        value=token,
        httponly=True,
        secure=False,  # Local dev — set True behind Nginx with TLS
        samesite="lax",
        max_age=_JWT_EXPIRATION_MINUTES * 60,
        path="/",
    )


def clear_auth_cookie(response: Response, role: Optional[str] = None) -> None:
    """Remove the JWT session cookie (logout) for the given role only."""
    response.delete_cookie(
        key=_ROLE_COOKIE.get(role, _LEGACY_COOKIE),
        path="/",
    )


def get_current_user(
    estate_admin_session: Optional[str] = Cookie(None),
    estate_heir_session: Optional[str] = Cookie(None),
    estate_session: Optional[str] = Cookie(None),
    x_estate_role: Optional[str] = Header(None, alias="X-Estate-Role"),
) -> dict:
    """
    FastAPI dependency: extract and validate the current user from
    whichever role-scoped session cookie applies.

    A single browser can simultaneously hold both an ADMIN and a HEIR
    cookie (e.g. one tab on /admin, another on /dashboard). The
    `X-Estate-Role` request header — set by the frontend based on which
    console/route is making the call — picks which cookie applies to
    *this* request. Without the header (older clients, tests, or a
    browser only logged into one role), falls back to whichever cookie
    is actually present, then the legacy single-cookie scheme.

    Raises 401 if no cookie decodes to a valid token.
    """
    if x_estate_role == "ADMIN":
        candidates = [estate_admin_session, estate_heir_session]
    else:
        candidates = [estate_heir_session, estate_admin_session]
    candidates.append(estate_session)

    for token in candidates:
        if not isinstance(token, str) or not token:
            continue
        try:
            return decode_access_token(token)
        except JWTError:
            continue
    raise HTTPException(status_code=401, detail="Not authenticated")


def get_current_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Dependency: require ADMIN role."""
    if current_user.get("role") != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def get_current_heir(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Dependency: require HEIR role."""
    if current_user.get("role") != "HEIR":
        raise HTTPException(status_code=403, detail="Heir access required")
    return current_user