from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class Reader(Protocol):
    """The only database surface the search core is allowed to use.

    It exists so `order_search` never imports psycopg and the search logic can
    be exercised against any Postgres, including a test schema.
    """

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        ...

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        ...


def _qualified(schema: str, name: str) -> str:
    """Qualifies a relation name, quoting both halves.

    This quotes and does not escape, so a `"` in the schema name would close the
    identifier. What keeps that out is `SQL_IDENTIFIER` in `api/config.py`,
    which rejects the name before it can reach a query. Both halves go through
    here so there is one place where a relation name is built.
    """
    return f'"{schema}"."{name}"'


@dataclass(frozen=True)
class Tables:
    """Schema-qualified relation names, resolved once per process.

    Every query in the search core interpolates these instead of writing bare
    table names, because the schemas are configurable so tests can run against
    `t_item`, `t_sales` and `t_app` without touching production data.
    """

    products: str
    product_barcodes: str
    customers: str
    orders: str
    order_items: str

    @classmethod
    def from_schemas(cls, item: str, sales: str) -> "Tables":
        return cls(
            products=_qualified(item, "products"),
            product_barcodes=_qualified(item, "product_barcodes"),
            customers=_qualified(sales, "customers"),
            orders=_qualified(sales, "orders"),
            order_items=_qualified(sales, "order_items"),
        )


def app_table(schema: str, name: str) -> str:
    """The same qualification for a table the search core does not own.

    The app schemas hold users and the audit log, which no search query reads,
    so they are named one call at a time rather than held on `Tables`.
    """
    return _qualified(schema, name)
