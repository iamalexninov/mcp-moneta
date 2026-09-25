"""In-process sliding-window rate limiter.

Good enough for one instance. For several instances put the same limits in
the reverse proxy / WAF (Azure Front Door, nginx limit_req) or back this with
Redis - the interface stays the same.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_s: int) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                retry = int(window_s - (now - q[0])) + 1
                raise HTTPException(429, "Too many requests", headers={"Retry-After": str(retry)})
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    # Behind a proxy run uvicorn with --proxy-headers --forwarded-allow-ips=<proxy ip>
    # so request.client.host is the real client address (never trust raw XFF).
    return request.client.host if request.client else "unknown"


def limit(bucket: str, limit_: int, window_s: int):
    """FastAPI dependency factory: per-IP limit for a route."""

    def _dep(request: Request) -> None:
        limiter.check(f"{bucket}:{client_ip(request)}", limit_, window_s)

    return _dep
