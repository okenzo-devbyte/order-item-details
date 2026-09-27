from __future__ import annotations

import pytest

from api.ratelimit import RateLimiter


@pytest.fixture(autouse=True)
def clean_rate_buckets(client_db):
    client_db.run(f'TRUNCATE "{client_db.schema_app}"."rate_buckets"')
    yield


def test_a_key_is_allowed_up_to_the_limit(client_db):
    limiter = RateLimiter(client_db, limit=3, window_seconds=60)
    assert limiter.allow("user:1") is True
    assert limiter.allow("user:1") is True
    assert limiter.allow("user:1") is True
    assert limiter.allow("user:1") is False


def test_two_limiters_share_one_budget(client_db):
    """On Vercel each warm instance is a separate object with its own memory.
    The limit only means something if the count lives in the database.
    """
    first = RateLimiter(client_db, limit=2, window_seconds=60)
    second = RateLimiter(client_db, limit=2, window_seconds=60)
    assert first.allow("ip:10.0.0.1") is True
    assert second.allow("ip:10.0.0.1") is True
    assert first.allow("ip:10.0.0.1") is False
    assert second.allow("ip:10.0.0.1") is False


def test_different_keys_do_not_share_a_budget(client_db):
    limiter = RateLimiter(client_db, limit=1, window_seconds=60)
    assert limiter.allow("user:1") is True
    assert limiter.allow("user:2") is True


def test_the_budget_resets_in_the_next_window(client_db):
    from datetime import datetime, timezone

    limiter = RateLimiter(client_db, limit=1, window_seconds=60)
    first = datetime(2026, 9, 27, 10, 0, 30, tzinfo=timezone.utc)
    second = datetime(2026, 9, 27, 10, 1, 30, tzinfo=timezone.utc)
    assert limiter.allow("user:9", now=first) is True
    assert limiter.allow("user:9", now=first) is False
    assert limiter.allow("user:9", now=second) is True