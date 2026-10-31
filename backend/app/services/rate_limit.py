"""In-memory, per-client sliding-window rate limiter (single process, thread-safe)."""
from __future__ import annotations

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request

WINDOW_SECONDS = 3600.0


class RateLimiter:
    def __init__(self, per_hour: int, what: str):
        self.per_hour = per_hour  # 0 disables the limit
        self._what = what
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, client: str) -> None:
        """Records one request, or raises 429 when the client is over its limit."""
        if self.per_hour <= 0:
            return
        now = time.time()
        with self._lock:
            recent = [t for t in self._hits[client] if t > now - WINDOW_SECONDS]
            if len(recent) >= self.per_hour:
                self._hits[client] = recent
                wait_min = max(1, int((recent[0] + WINDOW_SECONDS - now) / 60) + 1)
                raise HTTPException(
                    429, f"Demo limit reached ({self.per_hour} {self._what} per hour). "
                         f"Please try again in about {wait_min} min.",
                )
            recent.append(now)
            self._hits[client] = recent


def client_ip(request: Request, trusted_proxy_hops: int) -> str:
    """The caller's IP behind `trusted_proxy_hops` reverse proxies.

    Each proxy appends the address it received the request from to
    X-Forwarded-For, so the real client is the entry `hops` positions from the
    end; anything further left was sent by the client and cannot be trusted.
    """
    direct = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0:
        return direct
    forwarded = [ip.strip() for ip in request.headers.get("x-forwarded-for", "").split(",")
                 if ip.strip()]
    return forwarded[-trusted_proxy_hops] if len(forwarded) >= trusted_proxy_hops else direct
