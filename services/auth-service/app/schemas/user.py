"""Pydantic v2 request / response schemas for the auth service."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


# ── Request schemas ────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8)
    email: EmailStr | None = None
    full_name: str | None = Field(None, max_length=128)
    role: UserRole = UserRole.VIEWER


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(None, max_length=128)
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8)


# ── Response schemas ───────────────────────────────────────────────────────────


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str | None
    full_name: str | None
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires
