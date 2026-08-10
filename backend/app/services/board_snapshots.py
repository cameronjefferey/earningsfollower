"""Persist / serve Waves & Drift boards so cold pages don't re-score the universe."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BoardSnapshot, RefreshLog
from app.services import dashboard, drift, waves

logger = logging.getLogger(__name__)

DEFAULT_WAVES = (14, 21)
DEFAULT_DRIFT_LOOKBACK = 12
# Signal budget after per-target peer caps (~8 peers × ~10 cards).
FULL_WAVES_LIMIT = 80
FULL_DRIFT_LIMIT = 30


def wave_receipts_key() -> str:
    from app.services import wave_receipts

    return f"{wave_receipts.DAYS_BACK}:{wave_receipts.RECENT_DAYS}"


def persist_wave_receipts(db: Session, payload: dict) -> None:
    _upsert(db, "wave_receipts", wave_receipts_key(), payload)
    db.commit()


def earnings_snapshot_key() -> str:
    start, end = dashboard.date_range_for_window("all")
    return f"all:{start.isoformat()}:{end.isoformat()}"


def persist_earnings_snapshot(db: Session, cards: list[dict]) -> BoardSnapshot:
    """Store the full calendar span so /earnings can slice without recomputing."""
    start, end = dashboard.date_range_for_window("all")
    payload = {
        "window": "all",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "count": len(cards),
        "cards": cards,
    }
    row = _upsert(db, "earnings", earnings_snapshot_key(), payload)
    db.commit()
    return row


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
    params_key = f"{recent}:{upcoming}"
    prev_waves = get_snapshot(db, "waves", params_key)
    prev_drift = get_snapshot(db, "drift", str(DEFAULT_DRIFT_LOOKBACK))

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
    _upsert(db, "waves", params_key, wave_payload)

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

    # Receipts: how the waves that already resolved actually played out. Proof
    # for the funnel and the alert emails; cheap to serve once persisted.
    try:
        from app.services import wave_receipts

        persist_wave_receipts(db, wave_receipts.compute_wave_receipts(db))
    except Exception as exc:  # noqa: BLE001 - receipts must never break refresh
        logger.warning("Wave receipts failed: %s", exc)

    # Calendar cards for the full tab span - cold /earnings reads slice this.
    earn_cards, _ = dashboard.earnings_cards(db, "all")
    persist_earnings_snapshot(db, earn_cards)

    # persist_earnings_snapshot already commits; commit again for waves/drift.
    db.commit()
    logger.info(
        "Board snapshots refreshed: waves=%d drift=%d earnings=%d",
        len(wave_signals),
        len(drift_setups),
        len(earn_cards),
    )

    try:
        from app.services.setup_alerts import notify_new_setups

        notify_new_setups(
            prev_waves=prev_waves,
            prev_drift=prev_drift,
            new_waves=wave_payload,
            new_drift=drift_payload,
        )
    except Exception as exc:  # noqa: BLE001 - alerts must never break refresh
        logger.warning("Setup alerts failed: %s", exc)

    try:
        from app.services.wave_alerts import send_wave_alert_emails

        send_wave_alert_emails(
            db, prev_waves=prev_waves, new_waves=wave_payload
        )
    except Exception as exc:  # noqa: BLE001 - alerts must never break refresh
        logger.warning("Wave alert emails failed: %s", exc)

    return {
        "waves": len(wave_signals),
        "drift": len(drift_setups),
        "earnings": len(earn_cards),
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
    if list_key == "signals":
        # Waves: drop single-peer fan-outs and keep target groups intact.
        page, has_more = waves.page_wave_signals(items, limit=limit)
    else:
        has_more = len(items) > limit
        page = items[:limit]
    out = {**payload, list_key: page, "count": len(page), "limit": limit, "has_more": has_more}
    return out


def last_refresh_finished(db: Session) -> str | None:
    log = db.scalars(select(RefreshLog).order_by(RefreshLog.id.desc())).first()
    if log is None or log.finished_at is None:
        return None
    return log.finished_at.isoformat()
