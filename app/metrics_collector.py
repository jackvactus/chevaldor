"""Compteurs runtime pour endpoint /api/admin/metrics."""
from __future__ import annotations

import time
from threading import Lock

_START = time.time()
_lock = Lock()
_stats = {
    "requests": 0,
    "slow": 0,
    "errors_5xx": 0,
    "last_slow_path": "",
    "last_slow_ms": 0.0,
}


def record_request(*, elapsed_ms: float, path: str, status: int) -> None:
    with _lock:
        _stats["requests"] += 1
        if elapsed_ms > 1200:
            _stats["slow"] += 1
            _stats["last_slow_path"] = path
            _stats["last_slow_ms"] = round(elapsed_ms, 2)
        if status >= 500:
            _stats["errors_5xx"] += 1


def snapshot() -> dict:
    with _lock:
        return {
            "uptime_sec": round(time.time() - _START, 1),
            **_stats.copy(),
        }
