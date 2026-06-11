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
from fastapi import Cookie, Depends, HTTPException, Response
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


def set_auth_cookie(response: Response, token: str) -> None:
    """
    Set the HTTP-only JWT session cookie on a response.

    Per Backend Spec §6.3: Secure, HTTP-only cookie.
    """
    response.set_cookie(
        key="estate_session",
        value=token,
        httponly=True,
        secure=False,  # Local dev — set True behind Nginx with TLS
        samesite="lax",
        max_age=_JWT_EXPIRATION_MINUTES * 60,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Remove the JWT session cookie (logout)."""
    response.delete_cookie(
        key="estate_session",
        path="/",
    )


def get_current_user(
    estate_session: Optional[str] = Cookie(None),
) -> dict:
    """
    FastAPI dependency: extract and validate the current user from the
    'estate_session' HTTP-only cookie.

    Raises 401 if the cookie is missing, expired, or invalid.
    """
    if not estate_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_access_token(estate_session)
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


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