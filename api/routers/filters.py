from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import security
from ..db_helpers import get_db

router = APIRouter(prefix="/api/v1", tags=["filters"])

FACET_COLUMNS = {
    "store_code": ("orders", "store_code"),
    "order_type": ("orders", "order_type"),
    "vip_group": ("orders", "vip_group"),
    "dept": ("products", "dept"),
    "class_code": ("products", "class_code"),
    "subclass_code": ("products", "subclass_code"),
}


@router.get("/filters")
def filters(request: Request, user=Depends(security.rate_limit)):
    db = get_db(request)
    out: dict[str, list] = {}
    for name, (table, column) in FACET_COLUMNS.items():
        schema = db.schema_item if table == "products" else db.schema_sales
        rows = db.all(
            f"SELECT DISTINCT {column} AS v FROM \"{schema}\".\"{table}\""
            f" WHERE {column} IS NOT NULL ORDER BY {column}"
        )
        out[name] = [row["v"] for row in rows]
    return out
