from __future__ import annotations

from datetime import date, datetime

BARCODE_SEPARATOR = "||"
DATE_FORMAT = "%d-%b-%Y"
DATE_RANGE_SEPARATOR = " - "


def clean_str(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def split_barcodes(value: object) -> list[str]:
    """'21464546 || 2500001464545' -> ['21464546', '2500001464545'].

    Splitting happens here, at ingest, rather than at query time: the database
    stores one barcode per row and lookup is an exact match, so a compound cell
    kept intact could never be found. 148 of the 1000 source rows are compound.

    Order is preserved and repeats inside one cell are collapsed.
    """
    parts = [part.strip() for part in clean_str(value).split(BARCODE_SEPARATOR)]
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            out.append(part)
    return out


def parse_date_range(value: object) -> tuple[date | None, date | None]:
    """'26-Sep-2026 - 26-Sep-2026' -> (date(2026, 9, 26), date(2026, 9, 26)).

    The source column is a delivery window, not an order date, and it arrives as
    a single string holding both ends.

    Returns (None, None) for empty or unparseable input. A reversed range is
    swapped rather than rejected, because the source system occasionally emits
    the later date first.
    """
    text = clean_str(value)
    if not text:
        return None, None

    parts = [
        part.strip()
        for part in text.split(DATE_RANGE_SEPARATOR)
        if part.strip()
    ]
    if not parts:
        return None, None
    if len(parts) == 1:
        parts = [parts[0], parts[0]]
    if len(parts) != 2:
        return None, None

    try:
        start = datetime.strptime(parts[0], DATE_FORMAT).date()
        end = datetime.strptime(parts[1], DATE_FORMAT).date()
    except ValueError:
        return None, None

    if start > end:
        start, end = end, start
    return start, end


def to_int(value: object) -> int | None:
    """Coerces to int, tolerating int, numeric string and float string.

    Returns None rather than raising, so a malformed cell degrades to a missing
    value instead of aborting a 1000-row import.
    """
    text = clean_str(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return int(float(text))
    except (ValueError, OverflowError):
        return None
