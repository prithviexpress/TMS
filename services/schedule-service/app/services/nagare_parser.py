"""Parse Excel/CSV Nagare schedule files into consignment dicts.

Expected columns (case-insensitive, order-independent):
    vendor_code  — MSIL vendor code
    bay_code     — target unloading bay
    slot_start   — HH:MM  (24-hour)
    slot_end     — HH:MM  (24-hour)
    part_numbers — comma-separated part numbers (optional)
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, time

import openpyxl

logger = logging.getLogger(__name__)

# Canonical column names (lower-cased header → canonical key)
_COLUMN_ALIASES: dict[str, str] = {
    "vendor_code": "vendor_code",
    "vendor code": "vendor_code",
    "vendorcode": "vendor_code",
    "bay_code": "bay_code",
    "bay code": "bay_code",
    "baycode": "bay_code",
    "bay": "bay_code",
    "slot_start": "slot_start",
    "slot start": "slot_start",
    "slotstart": "slot_start",
    "start": "slot_start",
    "start_time": "slot_start",
    "slot_end": "slot_end",
    "slot end": "slot_end",
    "slotend": "slot_end",
    "end": "slot_end",
    "end_time": "slot_end",
    "part_numbers": "part_numbers",
    "part numbers": "part_numbers",
    "parts": "part_numbers",
    "part_no": "part_numbers",
}

_REQUIRED = {"vendor_code", "slot_start", "slot_end"}


def _parse_time(value: object) -> time:
    """Convert a cell value to :class:`datetime.time`.

    Accepts:
    - ``datetime.time`` (openpyxl sometimes returns these directly)
    - ``datetime.datetime``
    - ``str`` in HH:MM or HH:MM:SS format
    - ``float`` Excel serial fraction (e.g. 0.375 = 09:00)
    """
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, float):
        # Excel stores times as fractional days
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
) -> dict | None:
    """Convert a raw row to a consignment dict.  Returns None for blank rows."""
    record: dict[str, object] = {}
    for idx, key in col_map.items():
        if idx < len(row_values):
            record[key] = row_values[idx]

    # Skip blank rows
    if not any(v not in (None, "") for v in record.values()):
        return None

    # Validate required fields
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
        t_end = _parse_time(record["slot_end"])
    except (ValueError, TypeError) as exc:
        logger.warning("Row %d: bad time value — %s — skipped", row_num, exc)
        return None

    slot_start = datetime.combine(schedule_date, t_start)
    slot_end = datetime.combine(schedule_date, t_end)
    if slot_end <= slot_start:
        # Handle overnight case (e.g. 23:00 → 01:00 next day)
        from datetime import timedelta
        slot_end += timedelta(days=1)

    raw_parts = record.get("part_numbers", "") or ""
    part_numbers = [p.strip() for p in str(raw_parts).split(",") if p.strip()]

    return {
        "vendor_code": vendor_code,
        "bay_code": str(record.get("bay_code") or "").strip() or None,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "part_numbers": part_numbers,
    }


def parse_nagare_excel(file_bytes: bytes, schedule_date: date) -> list[dict]:
    """Parse an Excel (.xlsx) or CSV file into a list of consignment dicts.

    Each returned dict has keys:
        vendor_code, bay_code, slot_start, slot_end, part_numbers

    Args:
        file_bytes: Raw bytes of the uploaded file.
        schedule_date: The date this schedule applies to (used to construct
                       full slot datetimes from HH:MM times).

    Returns:
        A list of consignment dicts ready for DB insertion.
    """
    # Detect format by magic bytes
    if file_bytes[:4] == b"PK\x03\x04":
        return _parse_excel(file_bytes, schedule_date)
    return _parse_csv(file_bytes, schedule_date)


def _parse_excel(file_bytes: bytes, schedule_date: date) -> list[dict]:
    """Parse .xlsx bytes."""
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
            f"Missing required columns: {_REQUIRED - found}. "
            f"Found: {found}"
        )

    results: list[dict] = []
    for row_num, row in enumerate(rows[1:], start=2):
        record = _row_to_dict(list(row), col_map, schedule_date, row_num)
        if record:
            results.append(record)

    logger.info("Parsed %d consignment rows from Excel", len(results))
    return results


def _parse_csv(file_bytes: bytes, schedule_date: date) -> list[dict]:
    """Parse CSV bytes (UTF-8 or latin-1)."""
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
            f"Missing required columns: {_REQUIRED - found}. "
            f"Found: {found}"
        )

    results: list[dict] = []
    for row_num, row in enumerate(rows[1:], start=2):
        record = _row_to_dict(row, col_map, schedule_date, row_num)
        if record:
            results.append(record)

    logger.info("Parsed %d consignment rows from CSV", len(results))
    return results
