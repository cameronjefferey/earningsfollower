"""Learned take-profit - the exit half of the learning loop acting on itself.

The exit-quality backtest (``research/execution.py``) showed the directional books
reach a favorable underlying move and then give most of it back. This turns that
read into a *live* parameter: from the realized daily paths of closed directional
trades, find the take-profit threshold that would have captured the most of the
move, clamp it to a sane band, and only adopt it once there's enough evidence and
it actually beats how we exited. Guardrailed exactly like ``calibration``: opt-in,
minimum sample, banded, and a no-op fallback to the static default otherwise.

Recomputed every run from the append-only record, so it tightens as data grows -
no persisted state that can drift from the truth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PaperTrade, PriceBar

logger = logging.getLogger(__name__)

# Coarse grid of take-profit thresholds to search (favorable underlying move).
# Deliberately small to limit in-sample overfitting.
_TP_GRID = (0.02, 0.025, 0.03, 0.04, 0.05)

# Only adopt a learned TP over the static default if it beats actual capture by at
# least this margin (absolute favorable-move terms), so noise can't flip it.
_MIN_EDGE = 0.005


@dataclass
class LearnedExit:
    take_profit_pct: float       # the recommended threshold (clamped)
    n: int                       # graded directional trades it was fit on
    avg_captured: float          # avg favorable move captured under the learned TP
    actual_avg_captured: float   # avg favorable move we actually kept
    lift: float                  # avg_captured - actual
    applicable: bool             # enough evidence AND beats actual by the margin
    source: str                  # "learned"

    def as_dict(self) -> dict:
        return {
            "take_profit_pct": round(self.take_profit_pct, 4),
            "n": self.n,
            "avg_captured": round(self.avg_captured, 4),
            "actual_avg_captured": round(self.actual_avg_captured, 4),
            "lift": round(self.lift, 4),
            "applicable": self.applicable,
            "source": self.source,
        }


def _directional(t: PaperTrade) -> bool:
    """The books the underlying take-profit governs: waves/drift/reddit.

    Earnings sell-vol wins on IV crush, not direction. Earnings stock has its
    own 10%/7% band sized for a print; the 3% learned clip was built for the
    retired debit rides and would bank a move this book is meant to hold.
    """
    strat = (t.strategy or "").lower()
    return strat in ("waves", "drift", "reddit")


def _fav_path(db: Session, t: PaperTrade) -> dict | None:
    """Direction-adjusted daily path (per-day best favorable + closing move) plus
    the realized favorable move at the actual exit. None when unpriceable."""
    entry = t.spot_entry or t.entry_credit
    if not entry or entry <= 0 or not t.opened_at or t.realized_move_pct is None:
        return None
    end = (t.closed_at or datetime.utcnow()).date()
    bars = db.scalars(
        select(PriceBar)
        .where(
            PriceBar.ticker == t.ticker,
            PriceBar.date >= t.opened_at.date(),
            PriceBar.date <= end,
        )
        .order_by(PriceBar.date.asc())
    ).all()
    if not bars:
        return None
    long = t.direction == "bullish"
    days: list[tuple[float, float]] = []
    for b in bars:
        cl = b.adj_close if b.adj_close is not None else b.close
        hi = b.high if b.high is not None else cl
        lo = b.low if b.low is not None else cl
        if hi is None or lo is None or cl is None:
            continue
        if long:
            days.append((hi / entry - 1, cl / entry - 1))
        else:  # short: price down is favorable
            days.append((1 - lo / entry, 1 - cl / entry))
    if not days:
        return None
    realized = t.realized_move_pct if long else -t.realized_move_pct
    return {"days": days, "realized": realized}


def _sim_tp(days: list[tuple[float, float]], realized: float, tp: float) -> float:
    """Favorable move a resting take-profit at ``tp`` would have captured: the
    first day the intraday favorable high crosses the target, we fill at the
    target; otherwise we exit where we actually did."""
    for best, _end in days:
        if best >= tp:
            return tp
    return realized


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def compute_learned_take_profit(db: Session, settings) -> LearnedExit | None:
    """Best take-profit from the realized directional record, guardrailed. None
    when learning is off or there isn't enough graded history yet."""
    if not settings.paper_exit_learning_enabled:
        return None
    trades = db.scalars(
        select(PaperTrade).where(
            PaperTrade.status == "closed",
            PaperTrade.realized_move_pct.is_not(None),
        )
    ).all()
    paths = [
        p for t in trades if _directional(t) and (p := _fav_path(db, t)) is not None
    ]
    n = len(paths)
    if n < settings.paper_exit_learning_min_samples:
        return None

    actual = _mean([p["realized"] for p in paths])
    lo, hi = settings.paper_take_profit_min, settings.paper_take_profit_max
    grid = [tp for tp in _TP_GRID if lo <= tp <= hi] or [settings.paper_take_profit_pct]
    best_tp, best_avg = grid[0], None
    for tp in grid:
        avg = _mean([_sim_tp(p["days"], p["realized"], tp) for p in paths])
        if best_avg is None or avg > best_avg:
            best_avg, best_tp = avg, tp

    lift = round(best_avg - actual, 4)
    return LearnedExit(
        take_profit_pct=round(max(lo, min(hi, best_tp)), 4),
        n=n,
        avg_captured=round(best_avg, 4),
        actual_avg_captured=round(actual, 4),
        lift=lift,
        applicable=lift >= _MIN_EDGE,
        source="learned",
    )


def effective_take_profit(settings, learned: LearnedExit | None) -> float:
    """The take-profit the live trader should use: the learned one when it's
    trustworthy and beats actual, else the static default."""
    if learned is not None and learned.applicable:
        return learned.take_profit_pct
    return settings.paper_take_profit_pct


def exit_policy_state(db: Session, settings) -> dict:
    """Serializable view of the live take-profit policy for the API/UI."""
    learned = None
    try:
        learned = compute_learned_take_profit(db, settings)
    except Exception as e:  # noqa: BLE001 - never let the read break a page
        logger.warning("exit-learning compute failed: %s", e)
    return {
        "enabled": settings.paper_take_profit_enabled,
        "learning_enabled": settings.paper_exit_learning_enabled,
        "default_pct": settings.paper_take_profit_pct,
        "effective_pct": effective_take_profit(settings, learned),
        "band": [settings.paper_take_profit_min, settings.paper_take_profit_max],
        "min_samples": settings.paper_exit_learning_min_samples,
        "learned": learned.as_dict() if learned else None,
    }


def stop_policy_state(settings) -> dict:
    """Live hard-stop policy for sell-vol / earnings credit trades (API/UI)."""
    return {
        "enabled": bool(settings.paper_stops_enabled),
        "stop_loss_frac": settings.paper_stop_loss_frac,
        "late_dte": settings.paper_late_dte,
        "late_stop_frac": settings.paper_late_stop_frac,
        "applies_to": "earnings",
        "note": (
            "Cut sell-vol / earnings credits once unrealized loss hits this "
            "fraction of max risk; tighten near expiry. Checked each paper cron."
            if settings.paper_stops_enabled
            else "Off - losers can run to full defined risk while winners get clipped."
        ),
    }
