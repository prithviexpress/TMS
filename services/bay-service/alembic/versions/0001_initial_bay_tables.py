"""Initial bay-service tables.

Revision ID: 0001
Revises:
Create Date: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── bays ─────────────────────────────────────────────────────────────────
    op.create_table(
        "bays",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("bay_code", sa.String(32), nullable=False),
        sa.Column("zone", sa.String(16), nullable=True),
        sa.Column("sensor_device_eui", sa.String(32), nullable=True),
        sa.Column("light_address", sa.String(64), nullable=True),
        sa.Column("light_gateway_ip", sa.String(45), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bay_code"),
        sa.UniqueConstraint("sensor_device_eui"),
    )
    op.create_index("ix_bays_bay_code", "bays", ["bay_code"])
    op.create_index("ix_bays_zone", "bays", ["zone"])
    op.create_index("ix_bays_sensor_device_eui", "bays", ["sensor_device_eui"])

    # ── bay_occupancy ─────────────────────────────────────────────────────────
    op.create_table(
        "bay_occupancy",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("bay_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            server_default="VACANT",
            nullable=False,
        ),
        sa.Column("movement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vendor_name", sa.String(128), nullable=True),
        sa.Column("truck_plate", sa.String(32), nullable=True),
        sa.Column("occupied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_release_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["bay_id"], ["bays.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bay_id"),
    )
    op.create_index("ix_bay_occupancy_bay_id", "bay_occupancy", ["bay_id"])

    # ── sensor_readings ───────────────────────────────────────────────────────
    op.create_table(
        "sensor_readings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("device_eui", sa.String(32), nullable=False),
        sa.Column("bay_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occupied", sa.Boolean(), nullable=False),
        sa.Column("distance_mm", sa.Integer(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("raw_payload", postgresql.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["bay_id"], ["bays.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sensor_readings_device_eui", "sensor_readings", ["device_eui"])
    op.create_index("ix_sensor_readings_bay_id", "sensor_readings", ["bay_id"])

    # ── bay_occupancy_history ─────────────────────────────────────────────────
    op.create_table(
        "bay_occupancy_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("bay_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bay_code", sa.String(32), nullable=False),
        sa.Column("movement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vendor_name", sa.String(128), nullable=True),
        sa.Column("truck_plate", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["bay_id"], ["bays.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bay_occupancy_history_bay_id", "bay_occupancy_history", ["bay_id"])
    op.create_index("ix_bay_occupancy_history_bay_code", "bay_occupancy_history", ["bay_code"])
    op.create_index("ix_bay_occupancy_history_ended_at", "bay_occupancy_history", ["ended_at"])


def downgrade() -> None:
    op.drop_table("bay_occupancy_history")
    op.drop_table("sensor_readings")
    op.drop_table("bay_occupancy")
    op.drop_table("bays")
