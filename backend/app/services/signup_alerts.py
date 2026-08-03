"""Telegram alerts for the signup / billing funnel.

Best-effort: never raises. Debounces repeated failures (e.g. PKCE retries) so
one stuck user doesn't spam the chat.
"""

from __future__ import annotations

import logging
import time
from threading import Lock

from app.config import Settings, get_settings
from app.services.notify import send_telegram, telegram_configured

logger = logging.getLogger(__name__)

_DEFAULT_DEBOUNCE_S = 600
_lock = Lock()
_last_sent: dict[str, float] = {}


def notify_signup(
    kind: str,
    text: str,
    *,
    debounce_key: str | None = None,
    debounce_s: int = _DEFAULT_DEBOUNCE_S,
    settings: Settings | None = None,
) -> bool:
    """Send a signup-funnel Telegram ping. Returns True if a message was sent."""
    s = settings or get_settings()
    if not getattr(s, "telegram_notify_signup", True):
        return False
    if not telegram_configured():
        return False

    key = debounce_key or kind
    now = time.monotonic()
    with _lock:
        last = _last_sent.get(key)
        if last is not None and (now - last) < debounce_s:
            logger.info("Signup alert debounced kind=%s key=%s", kind, key)
            return False
        _last_sent[key] = now

    body = f"[earningsfollower] {text}".strip()
    ok = send_telegram(body)
    if ok:
        logger.info("Signup alert sent kind=%s", kind)
    return ok
