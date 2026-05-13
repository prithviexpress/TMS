"""Gantt chart endpoint.

GET /api/v1/schedule/gantt?date=YYYY-MM-DD
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.gantt import GanttResponse
from app.services.gantt_builder import build_gantt

router = APIRouter(tags=["gantt"])


@router.get("/gantt", response_model=GanttResponse)
async def get_gantt(
    date: date = Query(..., description="Date to build the Gantt for (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
) -> GanttResponse:
    """Return Gantt chart blocks for the given date.

    Each block represents one consignment slot, sorted by bay_code then
    slot_start, ready for the Mendix frontend to render.
    """
    return await build_gantt(db, date)
