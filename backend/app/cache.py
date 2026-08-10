"""Process-local TTL cache for expensive read endpoints.

Fine for a single API instance. Cleared on data refresh so cards don't serve
stale reaction/implied stats after ingest. Not shared across multiple workers -
use Redis later if you scale out.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}

# Earnings cards change only on refresh / day rollover; a few minutes is plenty.
DEFAULT_TTL_SECONDS = 300


def get(key: str) -> Any | None:
    now = time.monotonic()
    with _lock:
        item = _store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < now:
            del _store[key]
            return None
        return value


def set(key: str, value: Any, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
    with _lock:
        _store[key] = (time.monotonic() + ttl_seconds, value)


def clear() -> None:
    with _lock:
        _store.clear()
