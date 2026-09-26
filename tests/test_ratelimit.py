from api.ratelimit import RateLimiter


def test_allows_up_to_limit():
    limiter = RateLimiter(limit=3, window_seconds=60)
    assert limiter.allow("u1", now=0)
    assert limiter.allow("u1", now=1)
    assert limiter.allow("u1", now=2)
    assert not limiter.allow("u1", now=3)


def test_window_slides():
    limiter = RateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("u1", now=0)
    assert limiter.allow("u1", now=1)
    assert not limiter.allow("u1", now=2)
    assert limiter.allow("u1", now=61)


def test_keys_are_independent():
    limiter = RateLimiter(limit=1, window_seconds=60)
    assert limiter.allow("u1", now=0)
    assert not limiter.allow("u1", now=0)
    assert limiter.allow("u2", now=0)
