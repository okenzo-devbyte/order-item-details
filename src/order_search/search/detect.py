from __future__ import annotations

from dataclasses import dataclass

from ..db import Reader, Tables
from ..textnorm import is_barcode_like, norm

BARCODE = "barcode"
CUSTOMER = "customer"
PRODUCT = "product"
BOTH = "both"
NONE = "none"

# pg_trgm cannot match anything shorter than this.
MIN_TRIGRAM = 3


@dataclass(frozen=True)
class Detection:
    kind: str
    normalized_query: str
    customer_id: int | None = None
    product_ids: tuple[int, ...] = ()
    too_short: bool = False


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def detect(query: str, reader: Reader, tables: Tables) -> Detection:
    """Decides what the user is looking for.

    Order of tests matters: digits go to the barcode path first, an exact
    customer name wins over a product match, and a query that is neither is
    treated as product text because the product catalogue is the larger set.

    Product IDs are populated only when the query exactly matches a customer
    name AND prefixes at least one product name (the BOTH case). A pure
    product query leaves product_ids empty; the engine resolves those via
    trigram. An exact `=` cannot be used for the product side because stored
    product names are always longer than a customer name that prefixes them.

    The query is coerced with str() rather than assumed to be text, so a
    numeric query from a JSON payload degrades to a product search instead of
    raising AttributeError on .strip().
    """
    text = str(query or "").strip()
    normalized = norm(text)

    if not normalized:
        return Detection(NONE, "")

    if is_barcode_like(text):
        return Detection(BARCODE, normalized)

    exact_customer = reader.one(
        f"SELECT id FROM {tables.customers} WHERE name_norm = %s"
        " ORDER BY id LIMIT 1",
        (normalized,),
    )
    if exact_customer is not None:
        prefixed_products = reader.all(
            f"SELECT id FROM {tables.products} WHERE name_norm LIKE %s"
            " ESCAPE '\\' ORDER BY id",
            (_escape_like(normalized) + "%",),
        )
        product_ids = tuple(row["id"] for row in prefixed_products)
        kind = BOTH if product_ids else CUSTOMER
        return Detection(kind, normalized, exact_customer["id"], product_ids)

    if len(normalized) < MIN_TRIGRAM:
        return Detection(PRODUCT, normalized, too_short=True)

    return Detection(PRODUCT, normalized)
