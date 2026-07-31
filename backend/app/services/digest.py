"""Daily 'what changed' digest computed after refresh."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DailyDigest, EarningsEvent, ImpliedMoveSnapshot
from app.services import board_snapshots

logger = logging.getLogger(__name__)


def _load_snapshot_lists(db: Session) -> tuple[list[dict], list[dict]]:
    from app.services.waves import filter_by_min_peers

    waves = board_snapshots.get_snapshot(db, "waves", "14:21") or {}
    drift = board_snapshots.get_snapshot(db, "drift", "12") or {}
    return filter_by_min_peers(list(waves.get("signals") or [])), list(
        drift.get("setups") or []
    )


def _prior_digest_payload(db: Session, today: date) -> dict | None:
    row = db.scalars(
        select(DailyDigest)
        .where(DailyDigest.digest_date < today)
        .order_by(DailyDigest.digest_date.desc())
    ).first()
    if row is None:
        return None
    try:
        return json.loads(row.payload_json)
    except json.JSONDecodeError:
        return None


def build_digest(db: Session, *, as_of: date | None = None) -> dict[str, Any]:
    today = as_of or date.today()
    horizon = today + timedelta(days=7)

    upcoming = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.date >= today, EarningsEvent.date <= horizon)
        .order_by(EarningsEvent.date.asc())
    ).all()

    # New prints in the next week (first-seen names vs prior digest keys).
    prior = _prior_digest_payload(db, today) or {}
    prior_earn = set(prior.get("earnings_tickers") or [])
    earn_tickers = sorted({e.ticker for e in upcoming})
    new_earn = [t for t in earn_tickers if t not in prior_earn][:12]

    wave_signals, drift_setups = _load_snapshot_lists(db)
    wave_targets = sorted({s.get("target") for s in wave_signals if s.get("target")})
    drift_tickers = sorted({s.get("ticker") for s in drift_setups if s.get("ticker")})
    prior_waves = set(prior.get("wave_targets") or [])
    prior_drift = set(prior.get("drift_tickers") or [])
    new_waves = [t for t in wave_targets if t not in prior_waves][:10]
    new_drift = [t for t in drift_tickers if t not in prior_drift][:10]

    # Notable implied-move shifts vs yesterday's snapshot (if any).
    rich_flips: list[str] = []
    yday = today - timedelta(days=1)
    today_snaps = {
        r.ticker: r
        for r in db.scalars(
            select(ImpliedMoveSnapshot).where(ImpliedMoveSnapshot.snapshot_date == today)
        ).all()
    }
    yday_snaps = {
        r.ticker: r
        for r in db.scalars(
            select(ImpliedMoveSnapshot).where(ImpliedMoveSnapshot.snapshot_date == yday)
        ).all()
    }
    for ticker, cur in today_snaps.items():
        prev = yday_snaps.get(ticker)
        if (
            prev is None
            or cur.expected_move_pct is None
            or prev.expected_move_pct is None
            or prev.expected_move_pct == 0
        ):
            continue
        # ~25% relative move in priced-in move.
        if abs(cur.expected_move_pct / prev.expected_move_pct - 1.0) >= 0.25:
            rich_flips.append(ticker)
        if len(rich_flips) >= 8:
            break

    bullets: list[dict[str, str]] = []
    if new_earn:
        bullets.append(
            {
                "kind": "earnings",
                "text": f"{len(new_earn)} names newly on the 7-day calendar"
                + (f" (incl. {', '.join(new_earn[:4])})" if new_earn else ""),
            }
        )
    elif earn_tickers:
        bullets.append(
            {
                "kind": "earnings",
                "text": f"{len(earn_tickers)} tracked names report within 7 days",
            }
        )

    if new_waves:
        bullets.append(
            {
                "kind": "waves",
                "text": f"{len(new_waves)} new peer-wave target"
                f"{'' if len(new_waves) == 1 else 's'}: {', '.join(new_waves[:5])}",
            }
        )
    elif wave_targets:
        bullets.append(
            {
                "kind": "waves",
                "text": f"{len(wave_targets)} active peer-wave targets on the board",
            }
        )

    if new_drift:
        bullets.append(
            {
                "kind": "drift",
                "text": f"{len(new_drift)} new post-earnings drift setup"
                f"{'' if len(new_drift) == 1 else 's'}: {', '.join(new_drift[:5])}",
            }
        )
    elif drift_tickers:
        bullets.append(
            {
                "kind": "drift",
                "text": f"{len(drift_tickers)} live PEAD setups on the board",
            }
        )

    if rich_flips:
        bullets.append(
            {
                "kind": "implied",
                "text": f"Implied move shifted sharply for {', '.join(rich_flips[:5])}",
            }
        )

    if not bullets:
        bullets.append(
            {
                "kind": "none",
                "text": "Quiet day — no material calendar or board changes vs the last digest.",
            }
        )

    return {
        "date": today.isoformat(),
        "generated_at": datetime.utcnow().isoformat(),
        "bullets": bullets,
        "earnings_tickers": earn_tickers,
        "wave_targets": wave_targets,
        "drift_tickers": drift_tickers,
        "richness_flips": rich_flips,
    }


def persist_digest(db: Session, payload: dict) -> DailyDigest:
    day = date.fromisoformat(payload["date"])
    row = db.scalars(select(DailyDigest).where(DailyDigest.digest_date == day)).first()
    body = json.dumps(payload, default=str)
    now = datetime.utcnow()
    if row is None:
        row = DailyDigest(digest_date=day, payload_json=body, generated_at=now)
        db.add(row)
    else:
        row.payload_json = body
        row.generated_at = now
    db.commit()
    db.refresh(row)
    return row


def get_today(db: Session, *, preview: bool) -> dict:
    today = date.today()
    row = db.scalars(select(DailyDigest).where(DailyDigest.digest_date == today)).first()
    if row is None:
        # Fall back to most recent digest so the homepage isn't empty mid-day.
        row = db.scalars(
            select(DailyDigest).order_by(DailyDigest.digest_date.desc())
        ).first()
    if row is None:
        return {
            "date": today.isoformat(),
            "generated_at": None,
            "bullets": [
                {
                    "kind": "none",
                    "text": "Digest builds after the next data refresh.",
                }
            ],
            "preview": preview,
            "preview_note": (
                "Preview — subscribe for the full daily change list."
                if preview
                else None
            ),
            "updated_at": None,
        }

    try:
        payload = json.loads(row.payload_json)
    except json.JSONDecodeError:
        payload = {"bullets": [], "date": row.digest_date.isoformat()}

    bullets = list(payload.get("bullets") or [])
    note = None
    if preview:
        bullets = bullets[:3]
        note = "Preview — a few of today's changes. Pro unlocks the full digest."

    return {
        "date": payload.get("date") or row.digest_date.isoformat(),
        "generated_at": (
            row.generated_at.isoformat()
            if row.generated_at
            else payload.get("generated_at")
        ),
        "bullets": bullets,
        "preview": preview,
        "preview_note": note,
        "updated_at": row.generated_at.isoformat() if row.generated_at else None,
    }
