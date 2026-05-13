"""Basic pytest tests for auth-service endpoints.

These tests use an in-memory SQLite database via a patched async engine so
they require no external services.  Run with:

    pytest services/auth-service/app/tests/
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models.user import Base, User, UserRole
from app.services.auth_logic import hash_password


# ── In-memory SQLite test database ────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    """Create all tables once per test session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def seed_admin():
    """Insert an admin user and yield; clean up afterwards."""
    async with TestSessionLocal() as session:
        user = User(
            username="admin",
            hashed_password=hash_password("secret123"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    yield {"username": "admin", "password": "secret123", "id": user_id}

    async with TestSessionLocal() as session:
        result = await session.get(User, user_id)
        if result:
            await session.delete(result)
            await session.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health():
    """Health endpoint returns 200 and status ok."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/auth/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_login_success(seed_admin):
    """Valid credentials return access and refresh tokens."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "secret123"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_wrong_password(seed_admin):
    """Wrong password returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrongpassword"},
        )
    assert response.status_code == 401
    assert "Invalid" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_unknown_user():
    """Non-existent username returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "ghost", "password": "doesnotmatter"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_refresh(seed_admin):
    """A valid refresh token returns a new token pair."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First, log in to get tokens
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "secret123"},
        )
        assert login_resp.status_code == 200
        refresh_token = login_resp.json()["refresh_token"]

        # Now refresh
        refresh_resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
    assert refresh_resp.status_code == 200
    data = refresh_resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    # New refresh token should differ from the old one (token rotation)
    assert data["refresh_token"] != refresh_token


@pytest.mark.asyncio
async def test_refresh_reuse_rejected(seed_admin):
    """Replaying a consumed refresh token returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "secret123"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        # First use is fine
        r1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert r1.status_code == 200

        # Second use should be rejected
        r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert r2.status_code == 401


@pytest.mark.asyncio
async def test_logout(seed_admin):
    """After logout the refresh token is invalidated."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "secret123"},
        )
        refresh_token = login_resp.json()["refresh_token"]

        logout_resp = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
        assert logout_resp.status_code == 204

        # Token should now be invalid
        refresh_resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 401
