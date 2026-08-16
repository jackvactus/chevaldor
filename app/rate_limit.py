"""Limitation de débit simple (mémoire) — login / forgot-password."""
from __future__ import annotations

import os
import time
from collections import defaultdict
from threading import Lock
from typing import Dict, List

_lock = Lock()
_buckets: Dict[str, List[float]] = defaultdict(list)

LOGIN_MAX = int(os.environ.get("PEYA_LOGIN_RATE_MAX", "15"))
LOGIN_WINDOW_SEC = int(os.environ.get("PEYA_LOGIN_RATE_WINDOW", "900"))  # 15 min


def _prune(key: str, window: float) -> None:
    now = time.time()
    _buckets[key] = [t for t in _buckets[key] if now - t < window]


def check_rate_limit(key: str, *, max_calls: int = LOGIN_MAX, window_sec: int = LOGIN_WINDOW_SEC) -> None:
    """Lève ValueError si la limite est dépassée."""
    with _lock:
        _prune(key, window_sec)
        if len(_buckets[key]) >= max_calls:
            raise ValueError(
                f"Trop de tentatives — réessayez dans quelques minutes (max {max_calls}/{window_sec // 60} min)."
            )
        _buckets[key].append(time.time())


def client_rate_key(request, prefix: str = "login") -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{prefix}:{ip}"
