"""Initial schema — nagare_schedules, vendors, consignments with MSIL Nagare fields.

Revision ID: 0001
Revises: —
Create Date: 2026-05-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nagare_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("schedule_date", sa.Date(), nullable=False),
        sa.Column("shift", sa.String(10), nullable=True),
        sa.Column("uploaded_by", sa.String(255), nullable=True),
        sa.Column("raw_file_url", sa.String(1024), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("schedule_date", "shift", name="uq_nagare_date_shift"),
    )
    op.create_index("ix_nagare_schedules_schedule_date", "nagare_schedules", ["schedule_date"])

    op.create_table(
        "vendors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor_code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(20), nullable=True),
        sa.Column("whatsapp_number", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_vendors_vendor_code", "vendors", ["vendor_code"])

    op.create_table(
        "consignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nagare_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("nagare_schedules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False),
        # Nagare fields
        sa.Column("schedule_no", sa.String(30), nullable=True),
        sa.Column("item_code", sa.String(50), nullable=True),
        sa.Column("item_name", sa.String(200), nullable=True),
        sa.Column("bay_code", sa.String(20), nullable=True),
        sa.Column("bay_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("slot_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("nag_qty", sa.Integer(), nullable=True),
        # Truck / driver
        sa.Column("truck_plate", sa.String(20), nullable=True),
        sa.Column("driver_phone", sa.String(20), nullable=True),
        sa.Column("driver_name", sa.String(100), nullable=True),
        # GR / actual receipt
        sa.Column("consignment_no", sa.String(30), nullable=True),
        sa.Column("gate_entry_qty", sa.Integer(), nullable=True),
        sa.Column("received_qty", sa.Integer(), nullable=True),
        sa.Column("rejection_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("utl_qty", sa.Integer(), nullable=True),
        # Planning flags
        sa.Column("is_urgent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_emergency", sa.Boolean(), nullable=False, server_default="false"),
        # Status
        sa.Column("status", sa.String(30), nullable=False, server_default="SCHEDULED"),
        # Timestamps
        sa.Column("material_entry_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("material_entry_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_consignments_nagare_id", "consignments", ["nagare_id"])
    op.create_index("ix_consignments_vendor_id", "consignments", ["vendor_id"])
    op.create_index("ix_consignments_schedule_no", "consignments", ["schedule_no"])
    op.create_index("ix_consignments_bay_code", "consignments", ["bay_code"])
    op.create_index("ix_consignments_slot_start", "consignments", ["slot_start"])
    op.create_index("ix_consignments_truck_plate", "consignments", ["truck_plate"])
    op.create_index("ix_consignments_consignment_no", "consignments", ["consignment_no"])
    op.create_index("ix_consignments_status", "consignments", ["status"])


def downgrade() -> None:
    op.drop_table("consignments")
    op.drop_table("vendors")
    op.drop_table("nagare_schedules")
