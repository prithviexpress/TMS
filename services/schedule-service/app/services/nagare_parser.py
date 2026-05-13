"""Parse Excel/CSV Nagare schedule files into consignment dicts.

Expected columns map to real MSIL Nagare export field names:

    Schedule_no   — Nagare system's own unique ID (e.g. "16P6412043310WR1")
    Vendor_code   — MSIL vendor code (e.g. "K056")
    Unloading_loc — target unloading bay (e.g. "WR-10"), also accepts bay_code
    SupplyTime    — slot start time HH:MM (24-hour)
    Nag_qty       — planned delivery quantity
    Item          — part number (e.g. "64130M60T00")
    Item_name     — part description (optional)
    Type          — always "NAGARE", used for validation

slot_end is not present in the source file; it defaults to slot_start + 1 hour
unless overridden via the `default_slot_duration_minutes` parameter.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, time, timedelta

import openpyxl

logger = logging.getLogger(__name__)

_COLUMN_ALIASES: dict[str, str] = {
    # Schedule number
    "schedule_no": "schedule_no",
    "schedule no": "schedule_no",
    "scheduleno": "schedule_no",
    "schedule_no.": "schedule_no",
    # Vendor
    "vendor_code": "vendor_code",
    "vendor code": "vendor_code",
    "vendorcode": "vendor_code",
    # Bay / unloading location
    "unloading_loc": "bay_code",
    "unloading loc": "bay_code",
    "unloadingloc": "bay_code",
    "bay_code": "bay_code",
    "bay code": "bay_code",
    "baycode": "bay_code",
    "bay": "bay_code",
    "location": "bay_code",
    # Supply time (slot start)
    "supplytime": "slot_start",
    "supply_time": "slot_start",
    "supply time": "slot_start",
    "slot_start": "slot_start",
    "slot start": "slot_start",
    "start_time": "slot_start",
    "start": "slot_start",
    # Slot end (optional — usually absent, derived from slot_start + 1h)
    "slot_end": "slot_end",
    "slot end": "slot_end",
    "end_time": "slot_end",
    "end": "slot_end",
    # Quantities
    "nag_qty": "nag_qty",
    "nag qty": "nag_qty",
    "nagqty": "nag_qty",
    "planned_qty": "nag_qty",
    "qty": "nag_qty",
    # Item / part
    "item": "item_code",
    "item_code": "item_code",
    "part_no": "item_code",
    "part no": "item_code",
    "partno": "item_code",
    "item_name": "item_name",
    "item name": "item_name",
    "itemname": "item_name",
    "description": "item_name",
    "part_name": "item_name",
    # Schedule type (informational, not stored)
    "type": "schedule_type",
}

_REQUIRED = {"vendor_code", "slot_start"}


def _parse_time(value: object) -> time:
    """Convert a cell value to :class:`datetime.time`.

    Accepts datetime.time, datetime.datetime, str (HH:MM / HH:MM:SS),
    and float Excel serial fractions (e.g. 0.375 = 09:00).
    """
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, float):
        total_seconds = int(round(value * 86400))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return time(hour=hours % 24, minute=minutes, second=seconds)
    if isinstance(value, str):
        value = value.strip()
        for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
    raise ValueError(f"Cannot parse time from {value!r}")


def _normalise_headers(raw_headers: list[str | None]) -> dict[int, str]:
    """Map column index → canonical key; skip unrecognised columns."""
    mapping: dict[int, str] = {}
    for idx, header in enumerate(raw_headers):
        if header is None:
            continue
        canonical = _COLUMN_ALIASES.get(str(header).strip().lower())
        if canonical:
            mapping[idx] = canonical
    return mapping


def _row_to_dict(
    row_values: list[object],
    col_map: dict[int, str],
    schedule_date: date,
    row_num: int,
    default_slot_duration_minutes: int = 60,
) -> dict | None:
    """Convert a raw row to a consignment dict. Returns None for blank rows."""
    record: dict[str, object] = {}
    for idx, key in col_map.items():
        if idx < len(row_values):
            record[key] = row_values[idx]

    if not any(v not in (None, "") for v in record.values()):
        return None

    missing = _REQUIRED - set(record.keys())
    if missing:
        logger.warning("Row %d: missing columns %s — skipped", row_num, missing)
        return None

    vendor_code = str(record["vendor_code"]).strip()
    if not vendor_code:
        logger.warning("Row %d: empty vendor_code — skipped", row_num)
        return None

    try:
        t_start = _parse_time(record["slot_start"])
    except (ValueError, TypeError) as exc:
        logger.warning("Row %d: bad SupplyTime value — %s — skipped", row_num, exc)
        return None

    slot_start = datetime.combine(schedule_date, t_start)

    if "slot_end" in record and record["slot_end"] not in (None, ""):
        try:
            t_end = _parse_time(record["slot_end"])
            slot_end = datetime.combine(schedule_date, t_end)
            if slot_end <= slot_start:
                slot_end += timedelta(days=1)
        except (ValueError, TypeError):
            slot_end = slot_start + timedelta(minutes=default_slot_duration_minutes)
    else:
        slot_end = slot_start + timedelta(minutes=default_slot_duration_minutes)

    schedule_no_raw = record.get("schedule_no")
    schedule_no = str(schedule_no_raw).strip() if schedule_no_raw else None

    nag_qty_raw = record.get("nag_qty")
    nag_qty: int | None = None
    if nag_qty_raw not in (None, ""):
        try:
            nag_qty = int(float(str(nag_qty_raw)))
        except (ValueError, TypeError):
            pass

    item_code_raw = record.get("item_code")
    item_code = str(item_code_raw).strip() if item_code_raw else None

    item_name_raw = record.get("item_name")
    item_name = str(item_name_raw).strip() if item_name_raw else None

    return {
        "schedule_no": schedule_no,
        "vendor_code": vendor_code,
        "bay_code": str(record.get("bay_code") or "").strip() or None,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "item_code": item_code,
        "item_name": item_name,
        "nag_qty": nag_qty,
    }


def parse_nagare_excel(
    file_bytes: bytes,
    schedule_date: date,
    default_slot_duration_minutes: int = 60,
) -> list[dict]:
    """Parse an Excel (.xlsx) or CSV Nagare file into a list of consignment dicts.

    Each returned dict has keys:
        schedule_no, vendor_code, bay_code, slot_start, slot_end,
        item_code, item_name, nag_qty

    Args:
        file_bytes: Raw bytes of the uploaded file.
        schedule_date: The date this schedule applies to.
        default_slot_duration_minutes: Duration used when slot_end is absent
            (default 60 minutes — one Nagare slot).

    Returns:
        A list of consignment dicts ready for DB insertion.
    """
    if file_bytes[:4] == b"PK\x03\x04":
        return _parse_excel(file_bytes, schedule_date, default_slot_duration_minutes)
    return _parse_csv(file_bytes, schedule_date, default_slot_duration_minutes)


def _parse_excel(
    file_bytes: bytes,
    schedule_date: date,
    default_slot_duration_minutes: int,
) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        logger.warning("Excel file appears empty")
        return []

    header_row = [str(c).strip() if c is not None else None for c in rows[0]]
    col_map = _normalise_headers(header_row)

    if not _REQUIRED.issubset(col_map.values()):
        found = set(col_map.values())
        raise ValueError(
            f"Missing required columns: {_REQUIRED - found}. Found: {found}"
        )

    results: list[dict] = []
    for row_num, row in enumerate(rows[1:], start=2):
        record = _row_to_dict(list(row), col_map, schedule_date, row_num, default_slot_duration_minutes)
        if record:
            results.append(record)

    logger.info("Parsed %d consignment rows from Excel", len(results))
    return results


def _parse_csv(
    file_bytes: bytes,
    schedule_date: date,
    default_slot_duration_minutes: int,
) -> list[dict]:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Could not decode CSV file — unsupported encoding")

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        logger.warning("CSV file appears empty")
        return []

    col_map = _normalise_headers(rows[0])

    if not _REQUIRED.issubset(col_map.values()):
        found = set(col_map.values())
        raise ValueError(
            f"Missing required columns: {_REQUIRED - found}. Found: {found}"
        )

    results: list[dict] = []
    for row_num, row in enumerate(rows[1:], start=2):
        record = _row_to_dict(row, col_map, schedule_date, row_num, default_slot_duration_minutes)
        if record:
            results.append(record)

    logger.info("Parsed %d consignment rows from CSV", len(results))
    return results
