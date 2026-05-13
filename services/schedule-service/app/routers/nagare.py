"""Nagare schedule routes.

Endpoints
---------
GET  /api/v1/schedule/nagare              — list schedules for a date
POST /api/v1/schedule/nagare              — upload Excel/CSV, create schedule + consignments
GET  /api/v1/schedule/nagare/{nagare_id}  — single record
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import date

import boto3
import botocore.exceptions
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.consignment import Consignment
from app.models.nagare import NagareSchedule
from app.models.vendor import Vendor
from app.schemas.nagare import NagareResponse
from app.services.nagare_parser import parse_nagare_excel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["nagare"])


def _get_s3_client():
    """Return a boto3 S3 client pointed at MinIO."""
    return boto3.client(
        "s3",
        endpoint_url=f"http://{settings.MINIO_ENDPOINT}",
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name="us-east-1",
    )


async def _upload_to_minio(file_bytes: bytes, filename: str) -> str:
    """Upload raw file to MinIO and return its public URL."""
    import asyncio

    s3 = _get_s3_client()
    key = f"nagare/{filename}"

    def _upload() -> None:
        try:
            s3.create_bucket(Bucket=settings.MINIO_BUCKET_NAGARE)
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] not in (
                "BucketAlreadyOwnedByYou",
                "BucketAlreadyExists",
            ):
                raise
        s3.put_object(
            Bucket=settings.MINIO_BUCKET_NAGARE,
            Key=key,
            Body=io.BytesIO(file_bytes),
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _upload)
    return f"http://{settings.MINIO_ENDPOINT}/{settings.MINIO_BUCKET_NAGARE}/{key}"


@router.get("/nagare", response_model=list[NagareResponse])
async def list_nagare(
    date: date | None = Query(None, description="Filter by schedule date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
) -> list[NagareResponse]:
    """List Nagare schedules, optionally filtered by date."""
    stmt = select(NagareSchedule).order_by(NagareSchedule.schedule_date.desc())
    if date:
        stmt = stmt.where(NagareSchedule.schedule_date == date)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/nagare/{nagare_id}", response_model=NagareResponse)
async def get_nagare(
    nagare_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> NagareResponse:
    """Retrieve a single Nagare schedule by ID."""
    result = await db.execute(
        select(NagareSchedule).where(NagareSchedule.id == nagare_id)
    )
    nagare = result.scalar_one_or_none()
    if nagare is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nagare schedule not found")
    return nagare


@router.post("/nagare", response_model=NagareResponse, status_code=status.HTTP_201_CREATED)
async def upload_nagare(
    file: UploadFile,
    schedule_date: date = Query(..., description="Date this schedule applies to (YYYY-MM-DD)"),
    shift: str | None = Query(None, description="Shift: A, B, C, or FULL"),
    uploaded_by: str | None = Query(None, description="Username of the uploader"),
    db: AsyncSession = Depends(get_db),
) -> NagareResponse:
    """Upload an Excel or CSV Nagare file and create consignments from its rows.

    - Accepts .xlsx or .csv files.
    - Expects columns: vendor_code, bay_code, slot_start (HH:MM), slot_end (HH:MM),
      part_numbers (comma-separated, optional).
    - Creates a ``NagareSchedule`` record and one ``Consignment`` per valid row.
    - Skips rows where vendor_code is not found in the vendors table (logs a warning).
    """
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty",
        )

    # Upload raw file to MinIO
    safe_filename = f"{schedule_date}_{shift or 'FULL'}_{file.filename or 'upload'}"
    try:
        raw_file_url = await _upload_to_minio(file_bytes, safe_filename)
    except Exception as exc:  # noqa: BLE001
        logger.warning("MinIO upload failed (%s) — continuing without file URL", exc)
        raw_file_url = None

    # Parse rows
    try:
        rows = parse_nagare_excel(file_bytes, schedule_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No valid consignment rows found in the uploaded file",
        )

    # Build vendor_code → vendor_id lookup
    vendor_codes = {r["vendor_code"] for r in rows}
    vendor_result = await db.execute(
        select(Vendor).where(Vendor.vendor_code.in_(vendor_codes))
    )
    vendor_map: dict[str, Vendor] = {v.vendor_code: v for v in vendor_result.scalars().all()}

    missing_codes = vendor_codes - vendor_map.keys()
    if missing_codes:
        logger.warning("Unknown vendor codes in Nagare upload: %s — rows will be skipped", missing_codes)

    # Create NagareSchedule record
    nagare = NagareSchedule(
        schedule_date=schedule_date,
        shift=shift,
        uploaded_by=uploaded_by,
        raw_file_url=raw_file_url,
        is_published=False,
    )
    db.add(nagare)
    await db.flush()  # populate nagare.id

    # Create Consignment records
    created_count = 0
    for row in rows:
        vendor = vendor_map.get(row["vendor_code"])
        if vendor is None:
            continue  # skip unknown vendors
        consignment = Consignment(
            nagare_id=nagare.id,
            vendor_id=vendor.id,
            bay_code=row.get("bay_code"),
            part_numbers=row.get("part_numbers", []),
            slot_start=row["slot_start"],
            slot_end=row["slot_end"],
            status="SCHEDULED",
        )
        db.add(consignment)
        created_count += 1

    await db.flush()
    logger.info(
        "Nagare %s: created %d consignments from %d rows (%d skipped)",
        nagare.id,
        created_count,
        len(rows),
        len(rows) - created_count,
    )

    return nagare
