"""Vendor API router."""

from __future__ import annotations

import uuid
import logging
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.models.vendor import VendorProfile
from app.schemas.vendor import (
    TruckRegistrationRequest,
    TruckRegistrationResponse,
    VendorCreate,
    VendorResponse,
    VendorUpdate,
)
from app.services.truck_registration import register_truck
from tms_shared.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vendors", tags=["vendors"])

# ── Type aliases ───────────────────────────────────────────────────────────────

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
TokenPayloadDep = Annotated[dict, Depends(verify_token)]


# ── Health ─────────────────────────────────────────────────────────────────────


@router.get("/health")
async def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


# ── Vendor CRUD ────────────────────────────────────────────────────────────────


@router.get("", response_model=list[VendorResponse])
async def list_vendors(
    db: DbDep,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=200, description="Maximum records to return"),
    active_only: bool = Query(False, description="When true, return only active vendors"),
) -> list[VendorResponse]:
    """Return a paginated list of vendor profiles."""
    q = select(VendorProfile).order_by(VendorProfile.created_at)
    if active_only:
        q = q.where(VendorProfile.is_active.is_(True))
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    vendors = result.scalars().all()
    return [VendorResponse.model_validate(v) for v in vendors]


@router.post("", response_model=VendorResponse, status_code=status.HTTP_201_CREATED)
async def create_vendor(
    body: VendorCreate,
    db: DbDep,
    _token: TokenPayloadDep,
) -> VendorResponse:
    """Create a new vendor profile (auth required)."""
    # Check uniqueness of vendor_code
    existing = await db.execute(
        select(VendorProfile).where(VendorProfile.vendor_code == body.vendor_code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Vendor with code '{body.vendor_code}' already exists",
        )

    # Auto-generate registration_token if not provided
    token = body.registration_token or str(uuid.uuid4())

    vendor = VendorProfile(
        vendor_code=body.vendor_code,
        name=body.name,
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
        whatsapp_number=body.whatsapp_number,
        email=body.email,
        address=body.address,
        city=body.city,
        is_active=body.is_active,
        registration_token=token,
    )
    db.add(vendor)
    await db.flush()
    await db.refresh(vendor)
    return VendorResponse.model_validate(vendor)


@router.get("/{vendor_id}", response_model=VendorResponse)
async def get_vendor(vendor_id: uuid.UUID, db: DbDep) -> VendorResponse:
    """Fetch a single vendor by ID."""
    result = await db.execute(select(VendorProfile).where(VendorProfile.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    return VendorResponse.model_validate(vendor)


@router.put("/{vendor_id}", response_model=VendorResponse)
async def update_vendor(
    vendor_id: uuid.UUID,
    body: VendorUpdate,
    db: DbDep,
    _token: TokenPayloadDep,
) -> VendorResponse:
    """Update a vendor profile (auth required)."""
    result = await db.execute(select(VendorProfile).where(VendorProfile.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")

    if body.name is not None:
        vendor.name = body.name
    if body.contact_name is not None:
        vendor.contact_name = body.contact_name
    if body.contact_phone is not None:
        vendor.contact_phone = body.contact_phone
    if body.whatsapp_number is not None:
        vendor.whatsapp_number = body.whatsapp_number
    if body.email is not None:
        vendor.email = body.email
    if body.address is not None:
        vendor.address = body.address
    if body.city is not None:
        vendor.city = body.city
    if body.is_active is not None:
        vendor.is_active = body.is_active
    if body.registration_token is not None:
        vendor.registration_token = body.registration_token

    await db.flush()
    await db.refresh(vendor)
    return VendorResponse.model_validate(vendor)


# ── Vendor consignments (proxy to schedule-service) ───────────────────────────


@router.get("/{vendor_id}/consignments")
async def get_vendor_consignments(
    vendor_id: uuid.UUID,
    request: Request,
    settings: SettingsDep,
    _token: TokenPayloadDep,
) -> Any:
    """Proxy consignment list for a vendor from schedule-service.

    Forwards any additional query parameters (e.g. ``status``, ``from``,
    ``to``) transparently.
    """
    http_client: httpx.AsyncClient = request.app.state.http_client
    # Forward all original query params except we inject vendor_id
    params = dict(request.query_params)
    params["vendor_id"] = str(vendor_id)

    url = f"{settings.SCHEDULE_SERVICE_URL}/api/v1/schedule/consignments"
    try:
        resp = await http_client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"schedule-service error: {exc.response.text}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach schedule-service: {exc}",
        )


# ── Truck registration ─────────────────────────────────────────────────────────


@router.post("/register-truck", response_model=TruckRegistrationResponse)
async def register_truck_endpoint(
    body: TruckRegistrationRequest,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    _token: TokenPayloadDep,
) -> TruckRegistrationResponse:
    """Register a truck plate and driver phone for a scheduled consignment.

    Calls schedule-service to persist the update and broadcasts a NATS event.
    Auth required.
    """
    nats_js = request.app.state.nats_js
    http_client: httpx.AsyncClient = request.app.state.http_client

    try:
        return await register_truck(
            request=body,
            db=db,
            nats_js=nats_js,
            schedule_service_url=settings.SCHEDULE_SERVICE_URL,
            http_client=http_client,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"schedule-service error: {exc.response.text}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach schedule-service: {exc}",
        )


# ── Tokenised public endpoint (no auth) ───────────────────────────────────────


@router.get("/consignment/{token}")
async def get_consignment_by_token(
    token: str,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
) -> Any:
    """Public tokenised endpoint for vendor self-service links.

    Looks up the vendor by their ``registration_token`` (embedded in the
    SMS/WhatsApp link), then proxies the consignment details from
    schedule-service.  No authentication is required — the token itself
    acts as the credential.
    """
    # Resolve token → vendor
    result = await db.execute(
        select(VendorProfile).where(VendorProfile.registration_token == token)
    )
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired registration token",
        )

    http_client: httpx.AsyncClient = request.app.state.http_client
    url = f"{settings.SCHEDULE_SERVICE_URL}/api/v1/schedule/consignments"
    params = {"vendor_id": str(vendor.id), "status": "SCHEDULED"}

    try:
        resp = await http_client.get(url, params=params)
        resp.raise_for_status()
        consignments = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"schedule-service error: {exc.response.text}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach schedule-service: {exc}",
        )

    return {
        "vendor_id": str(vendor.id),
        "vendor_code": vendor.vendor_code,
        "vendor_name": vendor.name,
        "consignments": consignments,
    }
