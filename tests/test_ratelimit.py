from app.ratelimit import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_the_limit_per_key() -> None:
    limiter = RateLimiter(limit=2, window_seconds=60, clock=Clock())

    limiter.hit("a")
    assert not limiter.blocked("a")
    limiter.hit("a")
    assert limiter.blocked("a")
    assert not limiter.blocked("b")


def test_old_hits_expire_after_the_window() -> None:
    clock = Clock()
    limiter = RateLimiter(limit=2, window_seconds=60, clock=clock)
    limiter.hit("a")
    clock.now += 30
    limiter.hit("a")

    clock.now += 31  # The first hit is now older than the window.
    assert not limiter.blocked("a")
    clock.now += 30
    assert not limiter.blocked("a")


def test_reset_forgets_a_key() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60, clock=Clock())
    limiter.hit("a")
    limiter.hit("b")

    limiter.reset("a")

    assert not limiter.blocked("a")
    assert limiter.blocked("b")
