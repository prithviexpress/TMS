"""Auth-service API router."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models.user import RefreshToken, User, UserRole
from app.schemas.user import (
    LoginRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.services.auth_logic import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    refresh_token_expiry,
)
from tms_shared.auth import verify_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ── Type aliases ───────────────────────────────────────────────────────────────

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
TokenPayloadDep = Annotated[dict, Depends(verify_token)]


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _get_current_user(payload: TokenPayloadDep, db: DbDep) -> User:
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


CurrentUserDep = Annotated[User, Depends(_get_current_user)]


def _require_admin(current_user: CurrentUserDep) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return current_user


AdminDep = Annotated[User, Depends(_require_admin)]


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DbDep, settings: SettingsDep) -> TokenResponse:
    """Authenticate with username + password and receive JWT tokens."""
    user = await authenticate_user(db, body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last_login_at
    user.last_login_at = datetime.now(tz=timezone.utc)

    # Issue tokens
    access_token = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": user.role.value},
        settings,
    )
    raw_refresh = create_refresh_token()
    token_hash = hash_token(raw_refresh)

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=refresh_token_expiry(settings),
        )
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: DbDep, settings: SettingsDep) -> TokenResponse:
    """Exchange a valid refresh token for a new token pair."""
    token_hash = hash_token(body.refresh_token)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()

    if stored is None or not stored.is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Rotate: revoke old token
    stored.revoked_at = datetime.now(tz=timezone.utc)

    # Fetch user
    result = await db.execute(select(User).where(User.id == stored.user_id, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access_token = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": user.role.value},
        settings,
    )
    raw_refresh = create_refresh_token()
    new_hash = hash_token(raw_refresh)

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=new_hash,
            expires_at=refresh_token_expiry(settings),
        )
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, db: DbDep) -> None:
    """Revoke a refresh token (logout)."""
    token_hash = hash_token(body.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()
    if stored and stored.revoked_at is None:
        stored.revoked_at = datetime.now(tz=timezone.utc)


# ── User management ────────────────────────────────────────────────────────────


@router.get("/users", response_model=list[UserResponse])
async def list_users(db: DbDep, _admin: AdminDep) -> list[UserResponse]:
    """Return all users (admin only)."""
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, db: DbDep, _admin: AdminDep) -> UserResponse:
    """Create a new user (admin only)."""
    # Check uniqueness
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: uuid.UUID, db: DbDep, _current: CurrentUserDep) -> UserResponse:
    """Fetch a single user by ID."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    db: DbDep,
    current: CurrentUserDep,
) -> UserResponse:
    """Update a user's profile.

    Non-admin users may only update their own record; they cannot change their
    own role.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Non-admins can only edit themselves and cannot change roles
    if current.role != UserRole.ADMIN:
        if current.id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify another user")
        if body.role is not None and body.role != current.role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot change own role")

    if body.email is not None:
        user.email = body.email
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password is not None:
        user.hashed_password = hash_password(body.password)

    await db.flush()
    await db.refresh(user)
    return UserResponse.model_validate(user)
