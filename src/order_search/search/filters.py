from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Dates are stored as ISO YYYY-MM-DD text and compared lexicographically, which
# is chronological for this format. Anything else silently matches nothing, so
# it is rejected loudly here rather than producing an empty result that looks
# like "no purchases". The source format '26-Sep-2026' is deliberately NOT
# accepted: normalizing it would require importing the ingest layer, which this
# module must not depend on. Callers convert before constructing Filters.
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

_SCALAR_GROUPS = (
    ("store_code", "o.store_code"),
    ("order_type", "o.order_type"),
    ("vip_group", "o.vip_group"),
)
_PRODUCT_GROUPS = (
    ("dept", "p.dept"),
    ("class_code", "p.class_code"),
    ("subclass_code", "p.subclass_code"),
)


@dataclass(frozen=True)
class Filters:
    """Advanced filter state. Empty tuples mean 'do not filter'.

    dept / class_code / subclass_code live on the product, so the SQL fragment
    references the `p` alias; the caller must join order_items oi -> products p.
    """

    store_code: tuple[str, ...] = ()
    order_type: tuple[str, ...] = ()
    vip_group: tuple[str, ...] = ()
    dept: tuple[int, ...] = ()
    class_code: tuple[int, ...] = ()
    subclass_code: tuple[int, ...] = ()
    date_from: str | None = None
    date_to: str | None = None

    def __post_init__(self) -> None:
        for name, _column in _SCALAR_GROUPS + _PRODUCT_GROUPS:
            object.__setattr__(self, name, _clean(getattr(self, name)))
        for name in ("date_from", "date_to"):
            value = getattr(self, name)
            if value is not None and not _ISO_DATE_RE.fullmatch(value):
                raise ValueError(
                    f"{name} must be ISO YYYY-MM-DD, got {value!r}"
                )


def _clean(values: Any) -> tuple:
    if values is None:
        return ()
    if isinstance(values, (str, int, float)):
        values = [values]
    cleaned = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        cleaned.append(value)
    return tuple(cleaned)


def _in_clause(column: str, values: tuple) -> tuple[str, list]:
    placeholders = ",".join("?" for _ in values)
    return f"{column} IN ({placeholders})", list(values)


def order_filter_sql(filters: Filters) -> tuple[str, list]:
    """Builds the WHERE fragment for order-line filters.

    Semantics come straight from the spec:
      - values inside one group are OR-ed, groups are AND-ed
      - the date range is an OVERLAP test, not a containment test
      - when a date filter is present, orders with no date are excluded
      - when no date filter is present, orders with no date are kept
    """
    if filters is None:
        return "", []

    clauses: list[str] = []
    params: list = []

    for name, column in _SCALAR_GROUPS:
        values = getattr(filters, name)
        if values:
            clause, values_params = _in_clause(column, values)
            clauses.append(clause)
            params.extend(values_params)

    for name, column in _PRODUCT_GROUPS:
        values = getattr(filters, name)
        if values:
            clause, values_params = _in_clause(column, values)
            clauses.append(clause)
            params.extend(values_params)

    date_clauses: list[str] = []
    if filters.date_to:
        date_clauses.append("o.date_from <= ?")
        params.append(filters.date_to)
    if filters.date_from:
        date_clauses.append("o.date_to >= ?")
        params.append(filters.date_from)
    if date_clauses:
        date_clauses.append("o.date_from IS NOT NULL")
        clauses.append("(" + " AND ".join(date_clauses) + ")")

    if not clauses:
        return "", []
    return " AND ".join(clauses), params
