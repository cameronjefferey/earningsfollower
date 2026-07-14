"""Outbound notifications (currently Telegram).

Best-effort and dependency-light: if no bot token / chat id is configured the
sender is a no-op, and any network/API error is swallowed with a warning so a
notification failure can never break a paper run.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def telegram_configured() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token and s.telegram_chat_id)


def send_telegram(text: str) -> bool:
    """Send a plain-text message to the configured Telegram chat.

    Returns True on a delivered message, False if unconfigured or on any error
    (logged, never raised). Telegram caps messages at 4096 chars, so we trim.
    """
    s = get_settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        return False
    try:
        resp = httpx.post(
            _TELEGRAM_API.format(token=s.telegram_bot_token),
            json={
                "chat_id": s.telegram_chat_id,
                "text": text[:4096],
                "disable_web_page_preview": True,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001 - a notify failure must never break the caller
        logger.warning("Telegram send failed: %s", e)
        return False
