"""Calibration feedback - close the learning loop (phase 3).

The trade-decision store records the model's predicted win probability at entry
and the realized outcome at exit. Over time that tells us whether each strategy's
``win_prob`` has been optimistic or pessimistic. This module turns that history
into a per-strategy multiplier and applies it to the win-probability the entry
EV gate consumes, so the trader gradually stops taking trades its own track
record says are mispriced - and takes more of the ones it has underrated.

Heavily guardrailed on purpose (it changes what we trade):
  - opt-in via ``paper_calibration_enabled`` (on once the journal is thick enough),
  - only applied once a strategy has ``paper_calibration_min_samples`` graded
    trades (below that the ratio is noise and is ignored),
  - the multiplier itself is clamped to a sane band, and
  - the *movement* it can cause is hard-capped at ``paper_calibration_max_delta``
    so even a wild ratio can only nudge, never swing, the gate.

Sizing is deliberately left alone (still conviction-tiered); this touches only
the +EV gate's win-probability input.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TradeDecision

logger = logging.getLogger(__name__)

# Bound the raw ratio so a tiny predicted rate (e.g. 0.05) against a big realized
# one can't produce an absurd multiplier before the delta clamp even applies.
_MIN_MULT = 0.2
_MAX_MULT = 3.0
# Floor/ceiling on any win-probability we hand the gate.
_PROB_FLOOR = 0.05
_PROB_CEIL = 0.95


@dataclass
class CalibrationEntry:
    strategy: str
    n: int
    predicted: float          # avg model win_prob at entry
    realized: float           # realized win rate
    multiplier: float         # clamped realized / predicted
    applicable: bool          # enough samples to trust it

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "n": self.n,
            "predicted": round(self.predicted, 3),
            "realized": round(self.realized, 3),
            "multiplier": round(self.multiplier, 3),
            "applicable": self.applicable,
        }


def _is_win(row: TradeDecision) -> bool:
    if row.outcome in ("win", "loss"):
        return row.outcome == "win"
    return (row.realized_pnl or 0) > 0


def compute_calibration(db: Session, settings) -> dict[str, CalibrationEntry]:
    """Per-strategy calibration from graded decisions. Empty when disabled so the
    caller can treat "no calibration" and "feature off" identically."""
    if not settings.paper_calibration_enabled:
        return {}

    rows = db.scalars(
        select(TradeDecision).where(
            TradeDecision.decision == "opened",
            TradeDecision.realized_pnl.is_not(None),
            TradeDecision.win_prob.is_not(None),
        )
    ).all()

    grouped: dict[str, list[TradeDecision]] = {}
    for r in rows:
        grouped.setdefault(r.strategy or "earnings", []).append(r)

    min_n = settings.paper_calibration_min_samples
    out: dict[str, CalibrationEntry] = {}
    for strat, items in grouped.items():
        n = len(items)
        predicted = sum(r.win_prob for r in items) / n
        realized = sum(1 for r in items if _is_win(r)) / n
        if predicted <= 0:
            continue
        mult = max(_MIN_MULT, min(_MAX_MULT, realized / predicted))
        out[strat] = CalibrationEntry(
            strategy=strat,
            n=n,
            predicted=predicted,
            realized=realized,
            multiplier=mult,
            applicable=n >= min_n,
        )
    return out


def adjust_win_prob(
    raw: float | None,
    strategy: str,
    calib: dict[str, CalibrationEntry] | None,
    settings,
) -> float | None:
    """Recalibrate a model win-probability by the strategy's track record, within
    the guardrails. Returns ``raw`` unchanged when calibration is off, untrusted
    (too few samples), or unavailable - so it's always safe to call."""
    if raw is None or not calib:
        return raw
    entry = calib.get(strategy)
    if entry is None or not entry.applicable:
        return raw
    max_delta = settings.paper_calibration_max_delta
    adjusted = raw * entry.multiplier
    # Cap the movement, then clamp to a sane probability band.
    adjusted = max(raw - max_delta, min(raw + max_delta, adjusted))
    adjusted = max(_PROB_FLOOR, min(_PROB_CEIL, adjusted))
    if abs(adjusted - raw) >= 0.005:
        logger.info(
            "calibration: %s win_prob %.3f -> %.3f (x%.2f, n=%d)",
            strategy, raw, adjusted, entry.multiplier, entry.n,
        )
    return round(adjusted, 4)


def calibration_state(db: Session, settings) -> dict:
    """Serializable view of the current calibration, for the API/UI/narrator."""
    calib = compute_calibration(db, settings)
    return {
        "enabled": settings.paper_calibration_enabled,
        "min_samples": settings.paper_calibration_min_samples,
        "max_delta": settings.paper_calibration_max_delta,
        "strategies": [e.as_dict() for e in calib.values()],
    }
