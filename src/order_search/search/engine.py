from __future__ import annotations

import base64
import binascii
import json
import sqlite3
from typing import Any

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


def _phrase(text: str) -> str:
    """Wraps a query so FTS5 reads it as a literal phrase.

    Without the quotes FTS5 parses characters like ':' and '*' as query
    operators, and a Thai name containing them would raise an error.
    """
    return '"' + text.replace('"', '""') + '"'


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


class SearchEngine:
    """Answers 'what has this customer bought?' and 'who bought this product?'.

    Layer order, cheapest first:
      1 barcode lookup on an indexed column
      2 exact customer name, then fuzzy over customer names
      3 FTS5 trigram substring match on products
      3b the same, on the light-folded column with a light-folded query
      4 fuzzy WRatio over product names, only when layer 3 found too little
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

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
        detection = detect(query, self.connection)

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
        normalized = detect(text, self.connection).normalized_query
        if not normalized:
            return []
        pattern = _escape_like(normalized) + "%"
        rows = self.connection.execute(
            "SELECT id, name, name_norm FROM products"
            " WHERE name_norm LIKE ? ESCAPE '\\' ORDER BY name_norm LIMIT ?",
            (pattern, limit),
        ).fetchall()
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
        found = self._product_ids_by_fts(detection.normalized_query, "name_norm")
        if len(found) >= FUZZY_FALLBACK_THRESHOLD:
            return found

        # Layer 3b: the light-folded query against the light-folded column.
        # The pairing is load-bearing: a mark-carrying query is not a substring
        # of a tone-stripped column, so passing the raw query here silently
        # returns nothing.
        light_query = fold_light(detection.normalized_query)
        for product_id in self._product_ids_by_fts(
            light_query, "name_fold_light"
        ):
            if product_id not in found:
                found.append(product_id)
        if len(found) >= FUZZY_FALLBACK_THRESHOLD:
            return found

        # Layer 4: fuzzy, only when both exact paths found too little.
        for product_id, _text, _score in best_products(
            detection.normalized_query, self.connection
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
        matches = best_customers(detection.normalized_query, self.connection)
        if not matches:
            return None
        customer_id, _text, score = matches[0]
        return customer_id if score >= CUSTOMER_FUZZY_CUTOFF else None

    # ------------------------------------------------------------- layer 1 / 3

    def _product_ids_by_barcode(self, barcode: str) -> list[int]:
        if not barcode:
            return []
        rows = self.connection.execute(
            "SELECT DISTINCT product_id FROM product_barcodes"
            " WHERE barcode = ? ORDER BY product_id",
            (barcode,),
        ).fetchall()
        return [row["product_id"] for row in rows]

    def _product_ids_by_prefix(self, normalized: str) -> list[int]:
        rows = self.connection.execute(
            "SELECT id FROM products WHERE name_norm LIKE ? ESCAPE '\\'"
            " ORDER BY name_norm",
            (_escape_like(normalized) + "%",),
        ).fetchall()
        return [row["id"] for row in rows]

    def _product_ids_by_fts(self, query: str, column: str) -> list[int]:
        """Matches `query` against one FTS column.

        The MATCH is scoped to a single column because an unscoped
        `products_fts MATCH` searches every indexed column, letting a base-form
        query accidentally match the fold column or the reverse.

        The caller must pass a query transformed by the same function that
        built the column: `name_norm` pairs with `norm()`, `name_fold_light`
        with `fold_light()`.

        The length guard is per call: folding can shorten a query, so a base
        query of exactly 3 characters can become a 2-character fold, which the
        trigram tokenizer cannot match. Only the base column falls back to a
        prefix scan; a too-short fold query contributes nothing and lets
        layer 4 do the work.
        """
        if len(query) < MIN_TRIGRAM:
            if column == "name_norm":
                return self._product_ids_by_prefix(query)
            return []
        try:
            rows = self.connection.execute(
                "SELECT product_id FROM products_fts"
                f" WHERE {column} MATCH ? ORDER BY product_id",
                (_phrase(query),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [row["product_id"] for row in rows]

    # ------------------------------------------------------------- aggregation

    def _count_products(self, product_ids: list[int], filters: Filters) -> int:
        if not product_ids:
            return 0
        where, params = order_filter_sql(filters)
        placeholders = ",".join("?" for _ in product_ids)
        row = self.connection.execute(
            "SELECT COUNT(DISTINCT oi.product_id) AS total"
            " FROM order_items oi"
            " JOIN orders o ON o.id = oi.order_id"
            " JOIN products p ON p.id = oi.product_id"
            f" WHERE oi.product_id IN ({placeholders})"
            + (f" AND {where}" if where else ""),
            (*product_ids, *params),
        ).fetchone()
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
        placeholders = ",".join("?" for _ in product_ids)
        clause = f" AND {where}" if where else ""
        rows = self.connection.execute(
            "SELECT oi.product_id AS product_id,"
            " COUNT(*) AS order_count,"
            " COUNT(DISTINCT o.customer_id) AS customer_count,"
            " MAX(COALESCE(o.date_to, o.date_from)) AS last_date"
            " FROM order_items oi"
            " JOIN orders o ON o.id = oi.order_id"
            " JOIN products p ON p.id = oi.product_id"
            f" WHERE oi.product_id IN ({placeholders}){clause}"
            " GROUP BY oi.product_id"
            " ORDER BY order_count DESC, oi.product_id ASC"
            " LIMIT ? OFFSET ?",
            (*product_ids, *params, limit, offset),
        ).fetchall()
        if not rows:
            return []

        page_ids = [row["product_id"] for row in rows]
        details = {
            row["id"]: row
            for row in self.connection.execute(
                "SELECT id, name, dept, class_code, subclass_code, pack_size, unit"
                " FROM products WHERE id IN ("
                + ",".join("?" for _ in page_ids)
                + ")",
                tuple(page_ids),
            ).fetchall()
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
                    "last_date": row["last_date"],
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
        placeholders = ",".join("?" for _ in product_ids)
        clause = f" AND {where}" if where else ""
        rows = self.connection.execute(
            "SELECT oi.product_id AS product_id,"
            " o.customer_id AS customer_id,"
            " c.name AS customer_name,"
            " COUNT(*) AS order_count,"
            " MAX(COALESCE(o.date_to, o.date_from)) AS last_date,"
            " GROUP_CONCAT(DISTINCT o.store_code) AS stores,"
            " GROUP_CONCAT(DISTINCT o.vip_group) AS vip_groups"
            " FROM order_items oi"
            " JOIN orders o ON o.id = oi.order_id"
            " JOIN customers c ON c.id = o.customer_id"
            " JOIN products p ON p.id = oi.product_id"
            f" WHERE oi.product_id IN ({placeholders}){clause}"
            " GROUP BY oi.product_id, o.customer_id, c.name"
            " ORDER BY oi.product_id ASC, order_count DESC, o.customer_id ASC",
            (*product_ids, *params),
        ).fetchall()

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
                    "last_date": row["last_date"],
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
        placeholders = ",".join("?" for _ in customer_ids)
        clause = f" AND {where}" if where else ""
        # Joins through order_items to products so that product-attribute
        # filters (p.dept and friends) always have a `p` to bind to, whether
        # or not the caller filtered on one. Counts distinct orders rather
        # than rows so a future multi-item order is not double-counted.
        heads = self.connection.execute(
            "SELECT c.id AS customer_id, c.name AS name,"
            " COUNT(DISTINCT o.id) AS order_count,"
            " MAX(COALESCE(o.date_to, o.date_from)) AS last_date"
            " FROM orders o"
            " JOIN customers c ON c.id = o.customer_id"
            " JOIN order_items oi ON oi.order_id = o.id"
            " JOIN products p ON p.id = oi.product_id"
            f" WHERE o.customer_id IN ({placeholders}){clause}"
            " GROUP BY c.id, c.name"
            " ORDER BY order_count DESC, c.id ASC",
            (*customer_ids, *params),
        ).fetchall()

        out: list[dict[str, Any]] = []
        for head in heads:
            out.append(
                {
                    "customer_id": head["customer_id"],
                    "name": head["name"],
                    "order_count": head["order_count"],
                    "last_date": head["last_date"],
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
        rows = self.connection.execute(
            "SELECT p.id AS product_id, p.name AS name, p.pack_size AS pack_size,"
            " COUNT(*) AS order_count,"
            " MAX(COALESCE(o.date_to, o.date_from)) AS last_date"
            " FROM order_items oi"
            " JOIN orders o ON o.id = oi.order_id"
            " JOIN products p ON p.id = oi.product_id"
            " WHERE o.customer_id = ?"
            f"{clause}"
            " GROUP BY p.id, p.name, p.pack_size"
            " ORDER BY order_count DESC, p.id ASC"
            " LIMIT ?",
            (customer_id, *params, PRODUCTS_PER_CUSTOMER),
        ).fetchall()
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
                "last_date": row["last_date"],
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
        placeholders = ",".join("?" for _ in product_ids)
        clause = f" AND {where}" if where else ""
        rows = self.connection.execute(
            "SELECT oi.product_id AS product_id, o.store_code AS store_code,"
            " o.order_type AS order_type, o.item_remark AS item_remark,"
            " o.vip_group AS vip_group, o.vip_remark AS vip_remark"
            " FROM order_items oi"
            " JOIN orders o ON o.id = oi.order_id"
            " JOIN products p ON p.id = oi.product_id"
            f" WHERE oi.product_id IN ({placeholders})"
            f" AND o.customer_id = ?{clause}",
            (*product_ids, customer_id, *params),
        ).fetchall()

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
