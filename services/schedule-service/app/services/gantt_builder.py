"""Build Gantt chart data from consignment records."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.consignment import Consignment
from app.models.vendor import Vendor
from app.schemas.gantt import GanttBlock, GanttResponse


async def build_gantt(db: AsyncSession, target_date: date) -> GanttResponse:
    """Query all consignments for *target_date* and return a :class:`GanttResponse`.

    Consignments are filtered by ``slot_start`` date (UTC).  The blocks are
    sorted by ``bay_code`` (nulls last) then ``slot_start``.

    Args:
        db: Active async DB session.
        target_date: Calendar date to build the chart for.

    Returns:
        :class:`GanttResponse` with all blocks for the day.
    """
    # Build day boundaries in UTC
    day_start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=timezone.utc)
    day_end = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=timezone.utc)

    stmt = (
        select(Consignment)
        .options(joinedload(Consignment.vendor))
        .where(
            Consignment.slot_start >= day_start,
            Consignment.slot_start <= day_end,
        )
        .order_by(
            Consignment.bay_code.nulls_last(),
            Consignment.slot_start,
        )
    )

    result = await db.execute(stmt)
    consignments = result.scalars().all()

    blocks: list[GanttBlock] = []
    for c in consignments:
        blocks.append(
            GanttBlock(
                consignment_id=c.id,
                bay_code=c.bay_code,
                slot_start=c.slot_start,
                slot_end=c.slot_end,
                vendor_name=c.vendor.name,
                truck_plate=c.truck_plate,
                status=c.status,
            )
        )

    return GanttResponse(date=target_date, blocks=blocks)
