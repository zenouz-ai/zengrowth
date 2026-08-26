"""App-level login brute-force backoff (SEC-04).

Defence-in-depth behind the nginx edge limiter: if the edge is bypassed (a
published port, a misconfigured proxy) the operator login would otherwise be
unthrottled against the single password. This in-process throttle counts failed
attempts per client within a sliding window and locks that client out once the
threshold is crossed, until the window passes.

It lives on ``app.state`` (one instance per app), so each app — including each
TestClient — gets its own counter and tests don't bleed into one another. The
window-based count self-prunes, so there is no unbounded growth and no cleanup
job. Generous defaults mean normal use never trips it; the edge stays the primary
rate limiter.
"""

from __future__ import annotations

import time
from collections import defaultdict


class LoginThrottle:
    def __init__(self, *, max_attempts: int, lockout_seconds: int) -> None:
        self._max_attempts = max_attempts
        self._window = lockout_seconds
        self._failures: dict[str, list[float]] = defaultdict(list)

    @property
    def enabled(self) -> bool:
        return self._max_attempts > 0 and self._window > 0

    def _recent(self, key: str, now: float) -> list[float]:
        cutoff = now - self._window
        kept = [t for t in self._failures.get(key, ()) if t >= cutoff]
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def retry_after(self, key: str, *, now: float | None = None) -> int:
        """Seconds the client must wait, or 0 if not currently locked out."""
        if not self.enabled:
            return 0
        now = time.monotonic() if now is None else now
        recent = self._recent(key, now)
        if len(recent) < self._max_attempts:
            return 0
        # Locked until the oldest counted failure ages out of the window.
        return max(1, int(recent[0] + self._window - now))

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        if not self.enabled:
            return
        now = time.monotonic() if now is None else now
        self._recent(key, now)
        self._failures[key].append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
