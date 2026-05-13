"""Seed script: creates all 160 dock bays for the MSIL plant.

Bay layout (realistic automotive plant naming):
    Zone AR  — Assembly Receiving, North wing, 40 bays  (AR-N1  … AR-N40)
    Zone AR  — Assembly Receiving, South wing, 20 bays  (AR-S1  … AR-S20)
    Zone ARC — Assembly Receiving Central, 10 bays      (ARC1   … ARC10)
    Zone B   — Body shop receiving, 20 bays             (B1     … B20)
    Zone C   — Components / Castings, 20 bays           (C1     … C20)
    Zone D   — Dispatch / finished goods, 20 bays       (D1     … D20)
    Zone E   — Engine / powertrain, 15 bays             (E1     … E15)
    Zone P   — Press shop, 10 bays                      (P1     … P10)
    Zone W   — Warehouse / spare-parts, 5 bays          (W1     … W5)
    Total = 40 + 20 + 10 + 20 + 20 + 20 + 15 + 10 + 5 = 160 bays

Run via:
    python -m app.seeds.bays
"""

from __future__ import annotations

import asyncio
import logging
import sys
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, engine
from app.models.bay import Bay
from app.models.bay_occupancy import BayOccupancy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _generate_bay_definitions() -> list[dict]:
    """Return a list of bay definition dicts for all 160 bays."""
    bays: list[dict] = []

    def _add(zone: str, prefix: str, numbers: range, suffix: str = "") -> None:
        for n in numbers:
            bays.append({"bay_code": f"{prefix}{suffix}{n}", "zone": zone})

    # Zone AR — Assembly Receiving, North wing (40 bays)
    _add("AR", "AR-N", range(1, 41))

    # Zone AR — Assembly Receiving, South wing (20 bays)
    _add("AR", "AR-S", range(1, 21))

    # Zone ARC — Assembly Receiving Central (10 bays)
    _add("ARC", "ARC", range(1, 11))

    # Zone B — Body shop (20 bays)
    _add("B", "B", range(1, 21))

    # Zone C — Components / Castings (20 bays)
    _add("C", "C", range(1, 21))

    # Zone D — Dispatch / finished goods (20 bays)
    _add("D", "D", range(1, 21))

    # Zone E — Engine / powertrain (15 bays)
    _add("E", "E", range(1, 16))

    # Zone P — Press shop (10 bays)
    _add("P", "P", range(1, 11))

    # Zone W — Warehouse / spare-parts (5 bays)
    _add("W", "W", range(1, 6))

    assert len(bays) == 160, f"Expected 160 bays, got {len(bays)}"
    return bays


async def seed(db: AsyncSession) -> None:
    """Insert all 160 bays (and their default BayOccupancy rows) idempotently."""
    definitions = _generate_bay_definitions()
    created = 0
    skipped = 0

    for defn in definitions:
        result = await db.execute(
            select(Bay).where(Bay.bay_code == defn["bay_code"])
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            skipped += 1
            continue

        bay = Bay(
            id=uuid4(),
            bay_code=defn["bay_code"],
            zone=defn["zone"],
            is_active=True,
        )
        db.add(bay)
        await db.flush()  # get the PK before creating occupancy

        # Create default VACANT occupancy record
        occ = BayOccupancy(
            id=uuid4(),
            bay_id=bay.id,
            status="VACANT",
        )
        db.add(occ)
        created += 1

    await db.commit()
    logger.info("Bay seed complete: %d created, %d already existed (total=%d)", created, skipped, created + skipped)


async def _run() -> None:
    """Entry point when run as __main__."""
    # Ensure tables exist (idempotent with checkfirst=True)
    from app.database import Base
    import app.models  # noqa: F401 — registers all models with Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)

    async with AsyncSessionLocal() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(_run())
