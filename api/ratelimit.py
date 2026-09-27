from __future__ import annotations

from datetime import datetime, timezone


class RateLimiter:
    """Fixed-window limiter whose counters live in the database.

    An in-process counter is per warm instance on a serverless platform, so
    `limit` requests per minute would quietly become `limit` times the number
    of instances. One upsert per request is the price of a limit that holds.
    """

    def __init__(self, database, limit: int, window_seconds: int = 60) -> None:
        self.db = database
        self.limit = limit
        self.window = window_seconds

    def allow(self, key: str, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        window = moment.replace(second=0, microsecond=0)
        table = f'"{self.db.schema_app}"."rate_buckets"'
        row = self.db.one(
            f"INSERT INTO {table} (key, window_start, hits) VALUES (%s, %s, 1)"
            " ON CONFLICT (key, window_start) DO UPDATE"
            " SET hits = rate_buckets.hits + 1"
            " RETURNING hits",
            (key, window),
        )
        return row is not None and row["hits"] <= self.limit