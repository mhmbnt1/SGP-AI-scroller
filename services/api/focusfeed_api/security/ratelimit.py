"""In-process sliding-window rate limiter.

Limitation (documented): state is per API process. For a multi-process
deployment move the buckets to PostgreSQL or Redis. Keys are hashed so IPs and
emails are not kept in plain text in memory dumps.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    @staticmethod
    def _k(bucket: str, key: str) -> str:
        return hashlib.sha256(f"{bucket}:{key}".encode()).hexdigest()

    def check(self, bucket: str, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        """Record a hit and return True when allowed, False when over the limit."""
        now = time.monotonic()
        k = self._k(bucket, key)
        with self._lock:
            q = self._hits.setdefault(k, deque())
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            # opportunistic cleanup to bound memory
            if len(self._hits) > 50_000:
                stale = [kk for kk, qq in self._hits.items() if not qq or now - qq[-1] > window_seconds]
                for kk in stale:
                    self._hits.pop(kk, None)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
