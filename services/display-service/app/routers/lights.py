"""Banner K70 bay light router.

Provides HTTP endpoints to control individual and groups of K70 lights,
and to query current light states from the database.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.k70_state import K70LightState
from app.schemas.display import K70BulkRequest, K70LightRequest, K70StateResponse
from app.services.k70_client import set_k70_light

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/display", tags=["K70 Lights"])


def _get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def _upsert_k70(
    db: AsyncSession,
    bay_id: uuid.UUID,
    bay_code: str,
    color: str,
    mode: str,
    light_address: str,
) -> None:
    stmt = pg_insert(K70LightState).values(
        bay_id=bay_id,
        bay_code=bay_code,
        color=color,
        mode=mode,
        light_address=light_address,
        updated_at=datetime.now(tz=timezone.utc),
    ).on_conflict_do_update(
        index_elements=["bay_id"],
        set_={
            "color": color,
            "mode": mode,
            "light_address": light_address,
            "updated_at": datetime.now(tz=timezone.utc),
        },
    )
    await db.execute(stmt)


@router.post("/lights/{bay_id}", status_code=status.HTTP_200_OK)
async def set_light(
    bay_id: uuid.UUID,
    body: K70LightRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set the colour and mode of the K70 light for a specific bay."""
    settings = get_settings()
    light_address = f"bay-{bay_id}"

    # Look up any existing state to get the light_address if stored
    result = await db.execute(
        select(K70LightState).where(K70LightState.bay_id == bay_id)
    )
    existing = result.scalar_one_or_none()
    if existing and existing.light_address:
        light_address = existing.light_address

    http_client = _get_http_client(request)
    code, resp_body = await set_k70_light(
        http_client=http_client,
        gateway_ip=settings.K70_GATEWAY_IP,
        light_address=light_address,
        color=body.color,
        mode=body.mode,
        db=db,
        trigger_event="manual_api",
    )

    # Persist the new state
    bay_code = existing.bay_code if existing else str(bay_id)
    await _upsert_k70(db, bay_id, bay_code, body.color, body.mode, light_address)

    return {
        "bay_id": str(bay_id),
        "light_address": light_address,
        "color": body.color,
        "mode": body.mode,
        "gateway_response_code": code,
    }


@router.post("/lights/bulk", status_code=status.HTTP_200_OK)
async def set_lights_bulk(
    body: K70BulkRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set multiple K70 lights in a single API call."""
    settings = get_settings()
    http_client = _get_http_client(request)
    results = []

    for item in body.bays:
        light_address = f"bay-{item.bay_id}"

        result = await db.execute(
            select(K70LightState).where(K70LightState.bay_id == item.bay_id)
        )
        existing = result.scalar_one_or_none()
        if existing and existing.light_address:
            light_address = existing.light_address

        code, _ = await set_k70_light(
            http_client=http_client,
            gateway_ip=settings.K70_GATEWAY_IP,
            light_address=light_address,
            color=item.color,
            mode=item.mode,
            db=db,
            trigger_event="manual_api_bulk",
        )

        bay_code = existing.bay_code if existing else str(item.bay_id)
        await _upsert_k70(db, item.bay_id, bay_code, item.color, item.mode, light_address)

        results.append({
            "bay_id": str(item.bay_id),
            "light_address": light_address,
            "color": item.color,
            "mode": item.mode,
            "gateway_response_code": code,
        })

    return {"updated": len(results), "results": results}


@router.get("/lights/{bay_id}", response_model=K70StateResponse)
async def get_light_state(
    bay_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> K70StateResponse:
    """Return the current K70 light state for a bay."""
    result = await db.execute(
        select(K70LightState).where(K70LightState.bay_id == bay_id)
    )
    state = result.scalar_one_or_none()
    if state is None:
        raise HTTPException(status_code=404, detail="No K70 state found for this bay")

    return K70StateResponse(
        bay_id=state.bay_id,
        bay_code=state.bay_code,
        color=state.color,
        mode=state.mode,
        light_address=state.light_address,
        updated_at=state.updated_at.isoformat() if state.updated_at else None,
    )


@router.get("/health")
async def health() -> dict:
    """Service liveness probe."""
    return {"status": "ok"}
