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
            products=f'"{item}"."products"',
            product_barcodes=f'"{item}"."product_barcodes"',
            customers=f'"{sales}"."customers"',
            orders=f'"{sales}"."orders"',
            order_items=f'"{sales}"."order_items"',
        )


def app_table(schema: str, name: str) -> str:
    return f'"{schema}"."{name}"'
