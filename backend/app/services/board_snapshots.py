"""Persist / serve Waves & Drift boards so cold pages don't re-score the universe."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BoardSnapshot, RefreshLog
from app.services import drift, waves

logger = logging.getLogger(__name__)

DEFAULT_WAVES = (14, 21)
DEFAULT_DRIFT_LOOKBACK = 12
FULL_WAVES_LIMIT = 40
FULL_DRIFT_LIMIT = 30


def _upsert(db: Session, kind: str, params_key: str, payload: dict) -> BoardSnapshot:
    row = db.scalars(
        select(BoardSnapshot).where(
            BoardSnapshot.kind == kind, BoardSnapshot.params_key == params_key
        )
    ).first()
    now = datetime.utcnow()
    body = json.dumps(payload, default=str)
    if row is None:
        row = BoardSnapshot(
            kind=kind, params_key=params_key, payload_json=body, computed_at=now
        )
        db.add(row)
    else:
        row.payload_json = body
        row.computed_at = now
    return row


def refresh_board_snapshots(db: Session) -> dict[str, Any]:
    """Recompute default Waves/Drift boards and store them."""
    recent, upcoming = DEFAULT_WAVES
    wave_signals, _ = waves.current_waves(
        db, recent_days=recent, upcoming_days=upcoming, limit=FULL_WAVES_LIMIT
    )
    wave_payload = {
        "recent_days": recent,
        "upcoming_days": upcoming,
        "limit": FULL_WAVES_LIMIT,
        "count": len(wave_signals),
        "has_more": False,
        "signals": wave_signals,
        "preview": False,
        "preview_note": None,
    }
    _upsert(db, "waves", f"{recent}:{upcoming}", wave_payload)

    drift_setups, _ = drift.drift_setups(
        db, lookback_days=DEFAULT_DRIFT_LOOKBACK, limit=FULL_DRIFT_LIMIT
    )
    drift_payload = {
        "lookback_days": DEFAULT_DRIFT_LOOKBACK,
        "limit": FULL_DRIFT_LIMIT,
        "count": len(drift_setups),
        "has_more": False,
        "setups": drift_setups,
        "preview": False,
        "preview_note": None,
    }
    _upsert(db, "drift", str(DEFAULT_DRIFT_LOOKBACK), drift_payload)

    db.commit()
    logger.info(
        "Board snapshots refreshed: waves=%d drift=%d",
        len(wave_signals),
        len(drift_setups),
    )
    return {
        "waves": len(wave_signals),
        "drift": len(drift_setups),
    }


def get_snapshot(db: Session, kind: str, params_key: str) -> dict | None:
    row = db.scalars(
        select(BoardSnapshot).where(
            BoardSnapshot.kind == kind, BoardSnapshot.params_key == params_key
        )
    ).first()
    if row is None:
        return None
    try:
        payload = json.loads(row.payload_json)
    except json.JSONDecodeError:
        return None
    payload["updated_at"] = row.computed_at.isoformat() if row.computed_at else None
    return payload


def slice_list_payload(
    payload: dict, *, list_key: str, limit: int, strip_plans: bool = False
) -> dict:
    """Return a limited copy of a snapshot list payload with has_more."""
    items = list(payload.get(list_key) or [])
    if strip_plans:
        items = [{**s, "plan": None} for s in items]
    has_more = len(items) > limit
    page = items[:limit]
    out = {**payload, list_key: page, "count": len(page), "limit": limit, "has_more": has_more}
    return out


def last_refresh_finished(db: Session) -> str | None:
    log = db.scalars(select(RefreshLog).order_by(RefreshLog.id.desc())).first()
    if log is None or log.finished_at is None:
        return None
    return log.finished_at.isoformat()
