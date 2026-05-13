"""Core authentication business logic (pure functions + DB helpers)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.user import User

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password helpers ──────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*."""
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Return ``True`` when *plain* matches *hashed*."""
    return _pwd_context.verify(plain, hashed)


# ── Token helpers ─────────────────────────────────────────────────────────────


def create_access_token(data: dict, settings: Settings) -> str:
    """Encode *data* into a signed JWT access token.

    Args:
        data: Claims to embed (``sub`` should be the user id string).
        settings: Application settings supplying the secret and algorithm.

    Returns:
        A compact JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(tz=timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.now(tz=timezone.utc)})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token() -> str:
    """Return a cryptographically random refresh token (UUID4 string)."""
    return str(uuid.uuid4())


def hash_token(raw_token: str) -> str:
    """Return a SHA-256 hex digest of *raw_token* for safe DB storage."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


# ── DB-backed helpers ─────────────────────────────────────────────────────────


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    """Fetch the user by *username* and verify *password*.

    Returns:
        The :class:`~app.models.user.User` instance on success, or ``None``
        when the username is unknown or the password is wrong.
    """
    result = await db.execute(select(User).where(User.username == username, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def refresh_token_expiry(settings: Settings) -> datetime:
    """Return the UTC expiry datetime for a new refresh token."""
    return datetime.now(tz=timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
