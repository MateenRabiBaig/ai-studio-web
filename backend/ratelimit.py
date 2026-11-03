"""Simple in-memory sliding-window rate limiter.

Limitation: state lives in this process's memory only. It resets on restart
and is not shared across workers, so limits are per-process. If the backend
is scaled out or limits must survive restarts, swap `check` for a Redis
implementation (e.g. a sorted set of timestamps per key) — the call sites
do not need to change.
"""

import time
from collections import defaultdict, deque

_buckets: dict[str, deque[float]] = defaultdict(deque)


def check(key: str, limit: int, window_seconds: float) -> bool:
    """Record a hit for `key` and return False if the limit is exceeded."""
    now = time.monotonic()
    bucket = _buckets[key]

    while bucket and bucket[0] <= now - window_seconds:
        bucket.popleft()

    if len(bucket) >= limit:
        return False

    bucket.append(now)
    return True


def retry_after(key: str, window_seconds: float) -> int:
    """Seconds (rounded up) until the oldest hit in `key` leaves the window."""
    bucket = _buckets[key]
    if not bucket:
        return 1
    remaining = bucket[0] + window_seconds - time.monotonic()
    return max(1, int(remaining) + 1)
