import functools
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field


class RateLimiter:
    """At most `limit` hits per key in any `window_seconds`.

    State lives in this process: it resets on restart and each worker counts on its own.
    Move it to a shared store before running several workers.
    """

    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> deque[float]:
        hits = self._hits.get(key, deque())
        cutoff = self.clock() - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def hit(self, key: str) -> None:
        with self._lock:
            hits = self._recent(key)
            hits.append(self.clock())
            self._hits[key] = hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            hits = self._recent(key)
            if not hits:
                self._hits.pop(key, None)  # Keep memory bounded by active keys.
            return len(hits) >= self.limit

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


@dataclass
class RateLimits:
    # Failed logins per email: slows password guessing against one account.
    login: RateLimiter = field(default_factory=lambda: RateLimiter(5, 15 * 60))
    # Registrations per client address: slows mass sign-ups.
    register: RateLimiter = field(default_factory=lambda: RateLimiter(10, 60 * 60))
    # Assistant requests per user: each one is a paid call to the AI provider.
    assistant: RateLimiter = field(default_factory=lambda: RateLimiter(30, 60 * 60))


@functools.cache
def get_rate_limits() -> RateLimits:
    """FastAPI dependency: the process-wide limits."""
    return RateLimits()
