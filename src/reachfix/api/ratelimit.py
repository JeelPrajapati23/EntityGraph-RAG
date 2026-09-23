"""In-memory rate limit for /query, the one endpoint that spends Groq tokens.

A public deployment shares one set of Groq free-tier keys (about 200K
tokens/day each) among every visitor, so /query is capped per client IP per
hour and globally per day. /scan and /graph/explore make no LLM calls and
are not limited. State lives in the process: a restart resets it, which is
fine for a single-instance demo.

Configured from the environment (unset or 0 disables that cap):
    REACHFIX_QUERY_LIMIT_PER_IP_HOUR
    REACHFIX_QUERY_LIMIT_PER_DAY
"""

import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request

HOUR = 3600.0
DAY = 86400.0


class QueryLimiter:
    def __init__(self, per_ip_hour: int = 0, per_day: int = 0, clock: Callable[[], float] = time.monotonic):
        self.per_ip_hour = per_ip_hour
        self.per_day = per_day
        self._clock = clock
        self._lock = threading.Lock()  # handlers run in FastAPI's threadpool
        self._by_ip: dict[str, deque[float]] = defaultdict(deque)
        self._all: deque[float] = deque()

    @classmethod
    def from_env(cls) -> "QueryLimiter | None":
        per_ip_hour = int(os.environ.get("REACHFIX_QUERY_LIMIT_PER_IP_HOUR") or 0)
        per_day = int(os.environ.get("REACHFIX_QUERY_LIMIT_PER_DAY") or 0)
        return cls(per_ip_hour, per_day) if per_ip_hour or per_day else None

    def acquire(self, ip: str) -> str | None:
        """Record one query for `ip`, or return why it is refused (nothing is recorded then)."""
        now = self._clock()
        with self._lock:
            _expire(self._all, now - DAY)
            hits = self._by_ip[ip]
            _expire(hits, now - HOUR)
            if self.per_day and len(self._all) >= self.per_day:
                return (f"this demo has used its {self.per_day} questions for today; "
                        f"try again in {_wait(self._all[0] + DAY - now)} (Explore and Scan still work)")
            if self.per_ip_hour and len(hits) >= self.per_ip_hour:
                return (f"limit of {self.per_ip_hour} questions per hour reached; "
                        f"try again in {_wait(hits[0] + HOUR - now)}")
            hits.append(now)
            self._all.append(now)
            if len(self._by_ip) > 10_000:  # drop idle IPs so the map can't grow without bound
                for key in [k for k, v in self._by_ip.items() if not v]:
                    del self._by_ip[key]
            return None


def client_ip(request: Request) -> str:
    # Behind the host's proxy the socket peer is the proxy; the client is the first X-Forwarded-For hop.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _expire(hits: deque[float], cutoff: float) -> None:
    while hits and hits[0] <= cutoff:
        hits.popleft()


def _wait(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} min" if minutes < 90 else f"{round(minutes / 60)} h"
