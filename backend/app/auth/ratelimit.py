import time
from collections import defaultdict

from app.core.errors import RateLimitedError


class LoginRateLimiter:
    """In-memory failed-login throttle per key (email + ip). Per-process only: a multi-instance
    deployment needs a shared store such as Redis."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 900):
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, list[float]] = defaultdict(list)

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        recent = [t for t in self._failures[key] if t > cutoff]
        self._failures[key] = recent
        return recent

    def check(self, key: str) -> None:
        if len(self._recent(key)) >= self.max_failures:
            raise RateLimitedError("Too many failed attempts. Try again later.")

    def record_failure(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._failures.clear()
        else:
            self._failures.pop(key, None)


login_limiter = LoginRateLimiter()
# Public no-login pages: at most 60 requests a minute per address. (Counts every request, not only failures.)
public_limiter = LoginRateLimiter(max_failures=60, window_seconds=60)
