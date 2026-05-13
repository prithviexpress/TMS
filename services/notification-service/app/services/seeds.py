"""Seed default SMS templates."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.template import NotificationTemplate

DEFAULT_TEMPLATES = [
    {
        "code": "TRUCK_ALLOWED",
        "channel": "SMS",
        "body": "Your truck {{truck_plate}} is cleared. Proceed to bay {{bay_code}}. Slot: {{slot_start}}. - MSIL TMS",
    },
    {
        "code": "TRUCK_HOLD",
        "channel": "SMS",
        "body": "Your truck {{truck_plate}} arrived early. Please wait in parking. Slot in {{minutes_to_slot}} mins. - MSIL TMS",
    },
    {
        "code": "TRUCK_REJECT",
        "channel": "SMS",
        "body": "Your truck {{truck_plate}} cannot enter. Reason: {{rejection_reason}}. Contact MSIL logistics. - MSIL TMS",
    },
    {
        "code": "BAY_OCCUPIED",
        "channel": "SMS",
        "body": "Unloading started at bay {{bay_code}} for your consignment. - MSIL TMS",
    },
    {
        "code": "BAY_VACATED",
        "channel": "SMS",
        "body": "Unloading complete at {{bay_code}} ({{duration_minutes}} mins). Truck may depart. - MSIL TMS",
    },
]


async def seed_templates(session: AsyncSession) -> None:
    for tmpl_data in DEFAULT_TEMPLATES:
        existing = await session.execute(
            select(NotificationTemplate).where(NotificationTemplate.code == tmpl_data["code"])
        )
        if not existing.scalar_one_or_none():
            session.add(NotificationTemplate(**tmpl_data))
    await session.commit()
