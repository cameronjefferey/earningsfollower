"""Simple in-process rate limit for auth email endpoints."""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
# key -> list of unix timestamps
_hits: dict[str, list[float]] = {}


def allow(key: str, *, limit: int = 5, window_sec: int = 900) -> bool:
    """Return True if the action is allowed under the sliding window."""
    now = time.time()
    cutoff = now - window_sec
    with _lock:
        stamps = [t for t in _hits.get(key, []) if t >= cutoff]
        if len(stamps) >= limit:
            _hits[key] = stamps
            return False
        stamps.append(now)
        _hits[key] = stamps
        return True
