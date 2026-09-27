from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from ..db import Reader, Tables
from ..textnorm import digits_only, fold_light
from .detect import BARCODE, BOTH, CUSTOMER, MIN_TRIGRAM, NONE, PRODUCT, detect
from .filters import Filters, order_filter_sql
from .fuzzy import best_customers, best_products

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
FUZZY_FALLBACK_THRESHOLD = 5
CUSTOMER_FUZZY_CUTOFF = 70
CUSTOMERS_PER_PRODUCT = 50
PRODUCTS_PER_CUSTOMER = 50


def _encode_cursor(offset: int) -> str:
    raw = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return max(0, int(payload["offset"]))
    except (ValueError, KeyError, TypeError, binascii.Error):
        return 0


def _as_filters(filters: Any) -> Filters:
    if filters is None:
        return Filters()
    if isinstance(filters, Filters):
        return filters
    allowed = set(Filters.__dataclass_fields__)
    return Filters(
        **{k: v for k, v in dict(filters).items() if k in allowed and v is not None}
    )


def _coerce_limit(value: Any, default: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(number, maximum))


def _clean_list(values: Any) -> list[str]:
    if not values:
        return []
    out = []
    for value in values:
        text = str(value).strip()
        if text:
            out.append(text)
    return sorted(set(out))


def _escape_like(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def _iso_date(value):
    return value.isoformat() if value is not None else None


class SearchEngine:
    """Answers 'what has this customer bought?' and 'who bought this product?'.

    Layer order, cheapest first:
      1 barcode lookup on an indexed column
      2 exact customer name, then fuzzy over customer names
      3 trigram substring match on products
      3b the same, on the light-folded column with a light-folded query
      4 fuzzy WRatio over product names, only when layer 3 found too little
    """

    def __init__(self, reader: Reader, tables: Tables) -> None:
        self.reader = reader
        self.tables = tables

    # ------------------------------------------------------------------ public

    def search(
        self,
        query: str,
        mode: str = "auto",
        filters: Any = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if mode not in ("auto", "customer", "product"):
            raise ValueError(
                "mode must be 'auto', 'customer' or 'product',"
                f" got {mode!r}"
            )
        limit = _coerce_limit(limit, DEFAULT_LIMIT, MAX_LIMIT)
        active = _as_filters(filters)
        offset = _decode_cursor(cursor)
        detection = detect(query, self.reader, self.tables)

        payload: dict[str, Any] = {
            "query": query or "",
            "normalized_query": detection.normalized_query,
            "detected": detection.kind,
            "mode": "none",
            "customers": [],
            "products": [],
            "next_cursor": None,
        }
        if detection.kind == NONE:
            return payload

        wants_customer = mode in ("auto", "customer")
        wants_product = mode in ("auto", "product") and detection.kind in (
            BARCODE,
            PRODUCT,
            BOTH,
        )

        customer_id = (
            self._resolve_customer_id(detection) if wants_customer else None
        )
        if customer_id is not None:
            payload["customers"] = self._customer_results([customer_id], active)
            payload["mode"] = "customer"

        if wants_product:
            product_ids = self._product_ids(detection)
            products = self._product_results(product_ids, active, limit, offset)
            payload["products"] = products
            if products:
                payload["mode"] = (
                    "mixed" if payload["mode"] == "customer" else "product"
                )
            total = self._count_products(product_ids, active)
            if offset + len(products) < total:
                payload["next_cursor"] = _encode_cursor(offset + len(products))

        return payload

    def suggest(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        """Prefix suggestions for the autocomplete box.

        Uses a plain prefix match rather than the fuzzy layers on purpose: a
        dropdown that invents near-misses is worse than one that waits.
        """
        text = (query or "").strip()
        if not text:
            return []
        limit = _coerce_limit(limit, 8, 20)
        normalized = detect(text, self.reader, self.tables).normalized_query
        if not normalized:
            return []
        pattern = _escape_like(normalized) + "%"
        rows = self.reader.all(
            f"SELECT id, name, name_norm FROM {self.tables.products}"
            " WHERE name_norm LIKE %s ESCAPE '\\' ORDER BY name_norm LIMIT %s",
            (pattern, limit),
        )
        return [
            {"type": "product", "id": row["id"], "name": row["name"]}
            for row in rows
        ]

    def customer_history(
        self, customer_id: int, filters: Any = None
    ) -> list[dict[str, Any]]:
        """Public wrapper for a single customer's purchase history."""
        return self._customer_results([customer_id], _as_filters(filters))

    def product_customers(
        self, product_id: int, filters: Any = None
    ) -> list[dict[str, Any]]:
        """Public wrapper for the customers of a single product."""
        return self._product_results([product_id], _as_filters(filters), 1, 0)

    # ------------------------------------------------------------- layer 2 / 4

    def _product_ids(self, detection) -> list[int]:
        if detection.kind == BARCODE:
            return self._product_ids_by_barcode(
                digits_only(detection.normalized_query)
            )
        if detection.kind in (PRODUCT, BOTH) and detection.product_ids:
            return list(detection.product_ids)

        if detection.too_short:
            return self._product_ids_by_prefix(detection.normalized_query)

        # Layer 3: the base form against the base column.
        found = self._product_ids_by_trigram(
            detection.normalized_query, "name_norm"
        )
        if len(found) >= FUZZY_FALLBACK_THRESHOLD:
            return found

        # Layer 3b: the light-folded query against the light-folded column.
        # The pairing is load-bearing: name_norm pairs with norm(),
        # name_fold_light with fold_light(). A mark-carrying query is not a
        # substring of a tone-stripped column, so passing the raw query here
        # silently returns nothing.
        light_query = fold_light(detection.normalized_query)
        for product_id in self._product_ids_by_trigram(
            light_query, "name_fold_light"
        ):
            if product_id not in found:
                found.append(product_id)
        if len(found) >= FUZZY_FALLBACK_THRESHOLD:
            return found

        # Layer 4: fuzzy, only when both exact paths found too little.
        for product_id, _text, _score in best_products(
            detection.normalized_query, self.reader, self.tables
        ):
            if product_id not in found:
                found.append(product_id)
        return found

    def _resolve_customer_id(self, detection) -> int | None:
        """Layer 2. An exact name match wins; otherwise fall back to fuzzy
        matching over the customer list.

        The 70 cutoff is measured, not guessed: across all 20 real customer
        names it recognised every genuine typo tried (lowest score 72.7) and
        matched none of the non-name queries. Raising it only loses recall.
        """
        if detection.customer_id is not None:
            return detection.customer_id
        if detection.kind == BARCODE:
            return None
        matches = best_customers(
            detection.normalized_query, self.reader, self.tables
        )
        if not matches:
            return None
        customer_id, _text, score = matches[0]
        return customer_id if score >= CUSTOMER_FUZZY_CUTOFF else None

    # ------------------------------------------------------------- layer 1 / 3

    def _product_ids_by_barcode(self, barcode: str) -> list[int]:
        if not barcode:
            return []
        rows = self.reader.all(
            f"SELECT DISTINCT product_id FROM {self.tables.product_barcodes}"
            " WHERE barcode = %s ORDER BY product_id",
            (barcode,),
        )
        return [row["product_id"] for row in rows]

    def _product_ids_by_prefix(self, normalized: str) -> list[int]:
        rows = self.reader.all(
            f"SELECT id FROM {self.tables.products}"
            " WHERE name_norm LIKE %s ESCAPE '\\' ORDER BY name_norm",
            (_escape_like(normalized) + "%",),
        )
        return [row["id"] for row in rows]

    def _product_ids_by_trigram(
        self, query: str, column: str, limit: int = 200
    ) -> list[int]:
        if len(query) < MIN_TRIGRAM:
            if column == "name_norm":
                return self._product_ids_by_prefix(query)
            return []
        pattern = "%" + _escape_like(query) + "%"
        prefix = _escape_like(query) + "%"
        rows = self.reader.all(
            f"SELECT id FROM {self.tables.products}"
            f" WHERE {column} LIKE %s ESCAPE '\\'"
            " ORDER BY ("
            f"   {column} LIKE %s ESCAPE '\\'"
            " ) DESC, id"
            " LIMIT %s",
            (pattern, prefix, limit),
        )
        return [row["id"] for row in rows]

    # ------------------------------------------------------------- aggregation

    def _count_products(self, product_ids: list[int], filters: Filters) -> int:
        if not product_ids:
            return 0
        where, params = order_filter_sql(filters)
        placeholders = ",".join("%s" for _ in product_ids)
        row = self.reader.one(
            "SELECT COUNT(DISTINCT oi.product_id) AS total"
            f" FROM {self.tables.order_items} oi"
            f" JOIN {self.tables.orders} o ON o.id = oi.order_id"
            f" JOIN {self.tables.products} p ON p.id = oi.product_id"
            f" WHERE oi.product_id IN ({placeholders})"
            + (f" AND {where}" if where else ""),
            (*product_ids, *params),
        )
        return int(row["total"])

    def _product_results(
        self,
        product_ids: list[int],
        filters: Filters,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        if not product_ids:
            return []
        where, params = order_filter_sql(filters)
        placeholders = ",".join("%s" for _ in product_ids)
        clause = f" AND {where}" if where else ""
        rows = self.reader.all(
            "SELECT oi.product_id AS product_id,"
            " COUNT(*) AS order_count,"
            " COUNT(DISTINCT o.customer_id) AS customer_count,"
            " MAX(COALESCE(o.date_to, o.date_from)) AS last_date"
            f" FROM {self.tables.order_items} oi"
            f" JOIN {self.tables.orders} o ON o.id = oi.order_id"
            f" JOIN {self.tables.products} p ON p.id = oi.product_id"
            f" WHERE oi.product_id IN ({placeholders}){clause}"
            " GROUP BY oi.product_id"
            " ORDER BY order_count DESC, oi.product_id ASC"
            " LIMIT %s OFFSET %s",
            (*product_ids, *params, limit, offset),
        )
        if not rows:
            return []

        page_ids = [row["product_id"] for row in rows]
        details = {
            row["id"]: row
            for row in self.reader.all(
                "SELECT id, name, dept, class_code, subclass_code, pack_size, unit"
                f" FROM {self.tables.products} WHERE id IN ("
                + ",".join("%s" for _ in page_ids)
                + ")",
                tuple(page_ids),
            )
        }
        breakdown = self._customer_breakdown(page_ids, filters)

        out: list[dict[str, Any]] = []
        for row in rows:
            meta = details.get(row["product_id"])
            if meta is None:
                continue
            out.append(
                {
                    "product_id": row["product_id"],
                    "name": meta["name"],
                    "dept": meta["dept"],
                    "class_code": meta["class_code"],
                    "subclass_code": meta["subclass_code"],
                    "pack_size": meta["pack_size"],
                    "unit": meta["unit"],
                    "order_count": row["order_count"],
                    "customer_count": row["customer_count"],
                    "last_date": _iso_date(row["last_date"]),
                    "customers": breakdown.get(row["product_id"], []),
                }
            )
        return out

    def _customer_breakdown(
        self, product_ids: list[int], filters: Filters
    ) -> dict[int, list[dict[str, Any]]]:
        if not product_ids:
            return {}
        where, params = order_filter_sql(filters)
        placeholders = ",".join("%s" for _ in product_ids)
        clause = f" AND {where}" if where else ""
        rows = self.reader.all(
            "SELECT oi.product_id AS product_id,"
            " o.customer_id AS customer_id,"
            " c.name AS customer_name,"
            " COUNT(*) AS order_count,"
            " MAX(COALESCE(o.date_to, o.date_from)) AS last_date,"
            " string_agg(DISTINCT o.store_code, ','"
            " ORDER BY o.store_code) AS stores,"
            " string_agg(DISTINCT o.vip_group, ','"
            " ORDER BY o.vip_group) AS vip_groups"
            f" FROM {self.tables.order_items} oi"
            f" JOIN {self.tables.orders} o ON o.id = oi.order_id"
            f" JOIN {self.tables.customers} c ON c.id = o.customer_id"
            f" JOIN {self.tables.products} p ON p.id = oi.product_id"
            f" WHERE oi.product_id IN ({placeholders}){clause}"
            " GROUP BY oi.product_id, o.customer_id, c.name"
            " ORDER BY oi.product_id ASC, order_count DESC, o.customer_id ASC",
            (*product_ids, *params),
        )

        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            bucket = grouped.setdefault(row["product_id"], [])
            if len(bucket) >= CUSTOMERS_PER_PRODUCT:
                continue
            bucket.append(
                {
                    "customer_id": row["customer_id"],
                    "name": row["customer_name"],
                    "order_count": row["order_count"],
                    "last_date": _iso_date(row["last_date"]),
                    "stores": _clean_list(
                        row["stores"].split(",") if row["stores"] else []
                    ),
                    "vip_groups": _clean_list(
                        row["vip_groups"].split(",") if row["vip_groups"] else []
                    ),
                }
            )
        return grouped

    def _customer_results(
        self, customer_ids: list[int], filters: Filters
    ) -> list[dict[str, Any]]:
        if not customer_ids:
            return []
        where, params = order_filter_sql(filters)
        placeholders = ",".join("%s" for _ in customer_ids)
        clause = f" AND {where}" if where else ""
        # Joins through order_items to products so that product-attribute
        # filters (p.dept and friends) always have a `p` to bind to, whether
        # or not the caller filtered on one. Counts distinct orders rather
        # than rows so a future multi-item order is not double-counted.
        heads = self.reader.all(
            "SELECT c.id AS customer_id, c.name AS name,"
            " COUNT(DISTINCT o.id) AS order_count,"
            " MAX(COALESCE(o.date_to, o.date_from)) AS last_date"
            f" FROM {self.tables.orders} o"
            f" JOIN {self.tables.customers} c ON c.id = o.customer_id"
            f" JOIN {self.tables.order_items} oi ON oi.order_id = o.id"
            f" JOIN {self.tables.products} p ON p.id = oi.product_id"
            f" WHERE o.customer_id IN ({placeholders}){clause}"
            " GROUP BY c.id, c.name"
            " ORDER BY order_count DESC, c.id ASC",
            (*customer_ids, *params),
        )

        out: list[dict[str, Any]] = []
        for head in heads:
            out.append(
                {
                    "customer_id": head["customer_id"],
                    "name": head["name"],
                    "order_count": head["order_count"],
                    "last_date": _iso_date(head["last_date"]),
                    "products": self._products_for_customer(
                        head["customer_id"], filters
                    ),
                }
            )
        return out

    def _products_for_customer(
        self, customer_id: int, filters: Filters
    ) -> list[dict[str, Any]]:
        where, params = order_filter_sql(filters)
        clause = f" AND {where}" if where else ""
        rows = self.reader.all(
            "SELECT p.id AS product_id, p.name AS name, p.pack_size AS pack_size,"
            " COUNT(*) AS order_count,"
            " MAX(COALESCE(o.date_to, o.date_from)) AS last_date"
            f" FROM {self.tables.order_items} oi"
            f" JOIN {self.tables.orders} o ON o.id = oi.order_id"
            f" JOIN {self.tables.products} p ON p.id = oi.product_id"
            " WHERE o.customer_id = %s"
            f"{clause}"
            " GROUP BY p.id, p.name, p.pack_size"
            " ORDER BY order_count DESC, p.id ASC"
            " LIMIT %s",
            (customer_id, *params, PRODUCTS_PER_CUSTOMER),
        )
        if not rows:
            return []
        product_ids = [row["product_id"] for row in rows]
        facets = self._order_facets_for_products(
            product_ids, customer_id, filters
        )
        return [
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "pack_size": row["pack_size"],
                "order_count": row["order_count"],
                "last_date": _iso_date(row["last_date"]),
                "stores": facets.get(row["product_id"], {}).get("stores", []),
                "order_types": facets.get(row["product_id"], {}).get(
                    "order_types", []
                ),
                "item_remarks": facets.get(row["product_id"], {}).get(
                    "item_remarks", []
                ),
                "vip_groups": facets.get(row["product_id"], {}).get(
                    "vip_groups", []
                ),
                "vip_remarks": facets.get(row["product_id"], {}).get(
                    "vip_remarks", []
                ),
            }
            for row in rows
        ]

    def _order_facets_for_products(
        self, product_ids: list[int], customer_id: int, filters: Filters
    ) -> dict[int, dict[str, list[str]]]:
        if not product_ids:
            return {}
        where, params = order_filter_sql(filters)
        placeholders = ",".join("%s" for _ in product_ids)
        clause = f" AND {where}" if where else ""
        rows = self.reader.all(
            "SELECT oi.product_id AS product_id, o.store_code AS store_code,"
            " o.order_type AS order_type, o.item_remark AS item_remark,"
            " o.vip_group AS vip_group, o.vip_remark AS vip_remark"
            f" FROM {self.tables.order_items} oi"
            f" JOIN {self.tables.orders} o ON o.id = oi.order_id"
            f" JOIN {self.tables.products} p ON p.id = oi.product_id"
            f" WHERE oi.product_id IN ({placeholders})"
            f" AND o.customer_id = %s{clause}",
            (*product_ids, customer_id, *params),
        )

        names = {
            "stores": "store_code",
            "order_types": "order_type",
            "item_remarks": "item_remark",
            "vip_groups": "vip_group",
            "vip_remarks": "vip_remark",
        }
        out: dict[int, dict[str, list[str]]] = {}
        for row in rows:
            bucket = out.setdefault(
                row["product_id"], {key: [] for key in names}
            )
            for key, column in names.items():
                value = row[column]
                if value and value not in bucket[key]:
                    bucket[key].append(value)
        for bucket in out.values():
            for key in names:
                bucket[key].sort()
        return out