"""Persist + optionally Telegram-notify product/ops events."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AppEvent
from app.services.signup_alerts import notify_signup

logger = logging.getLogger(__name__)


def log_event(
    db: Session,
    *,
    kind: str,
    message: str,
    email: str | None = None,
    meta: dict[str, Any] | None = None,
    telegram: bool = True,
    debounce_s: int = 0,
    debounce_key: str | None = None,
) -> AppEvent | None:
    """Write an AppEvent and optionally ping Telegram.

    Never raises. Does not commit — the caller owns the transaction. On a DB
    write failure we expunge the row (no full-session rollback) so the caller's
    work is preserved.
    """
    row = AppEvent(
        kind=kind,
        email=(email or "").strip().lower() or None,
        message=message[:2000],
        meta_json=json.dumps(meta) if meta else None,
    )
    try:
        db.add(row)
        db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist app_event kind=%s: %s", kind, exc)
        try:
            db.expunge(row)
        except Exception:  # noqa: BLE001
            pass
        row = None

    if telegram:
        notify_signup(
            kind,
            message,
            debounce_key=debounce_key
            or (f"{kind}:{row.id}" if row is not None else f"{kind}:{email or 'none'}"),
            debounce_s=debounce_s,
        )
    return row
