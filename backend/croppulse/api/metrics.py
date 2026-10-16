"""In-process request metrics (latency, error counts per route template).

Single-instance only; a production deployment should export these to Prometheus or
similar (docs/OPERATIONS.md).
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any

_lock = threading.Lock()
_count: dict[str, int] = defaultdict(int)
_errors: dict[str, int] = defaultdict(int)
_lat_ms: dict[str, list[float]] = defaultdict(list)


def record(route: str, status_code: int, ms: float) -> None:
    with _lock:
        _count[route] += 1
        if status_code >= 500:
            _errors[route] += 1
        buf = _lat_ms[route]
        buf.append(ms)
        if len(buf) > 500:
            del buf[: len(buf) - 500]


def snapshot() -> dict[str, Any]:
    with _lock:
        out = {}
        for r, n in _count.items():
            lat = sorted(_lat_ms[r])
            out[r] = {
                "requests": n,
                "server_errors": _errors[r],
                "p50_ms": round(lat[len(lat) // 2], 1) if lat else None,
                "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 1) if len(lat) >= 20 else None,
            }
        return out
