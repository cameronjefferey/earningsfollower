from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EarningsEvent
from app.services.prices import PriceSeries, load_price_series

DRIFT_DAYS = 5
DRIFT_HORIZONS = (1, 5, 10)


@dataclass
class EarningsReaction:
    date: str
    timing: str
    eps_estimate: float | None
    eps_actual: float | None
    surprise_pct: float | None
    beat: bool | None
    # Close-to-close % move attributable to the report (timing-aware).
    move_pct: float | None
    # Open gap on the anchor day vs. the prior close.
    gap_pct: float | None
    # Cumulative drift over the following DRIFT_DAYS trading days.
    drift_pct: float | None
    # Post-earnings drift at multiple horizons (1 / 5 / 10 trading days).
    drift_1d_pct: float | None
    drift_10d_pct: float | None


@dataclass
class ReactionSummary:
    sample_size: int
    avg_abs_move_pct: float | None
    median_abs_move_pct: float | None
    avg_move_pct: float | None
    up_rate: float | None
    last_move_pct: float | None
    beat_rate: float | None
    beat_streak: int
    avg_move_on_beat_pct: float | None
    avg_move_on_miss_pct: float | None
    avg_drift_pct: float | None
    # Post-earnings drift (PEAD) breakdown, using the 5-day horizon.
    avg_drift_after_beat_pct: float | None
    avg_drift_after_miss_pct: float | None
    # How often the 5-day drift continued in the same direction as the
    # earnings-day move (momentum / continuation rate).
    continuation_rate: float | None


def _resolve_anchor(series: PriceSeries, event_date: date, timing: str) -> tuple[int, int] | None:
    """Return (baseline_idx, anchor_idx) for an event.

    baseline = close that does NOT yet reflect the report.
    anchor   = first close that fully reflects the report.
    """
    if len(series) < 2:
        return None

    if timing == "bmo":
        anchor = series.index_on_or_after(event_date)
        if anchor is None or anchor == 0:
            return None
        return anchor - 1, anchor

    # AMC or unknown: announcement lands after the report-day close, so the
    # baseline is the report day and the anchor is the next trading day.
    baseline = series.index_on_or_before(event_date)
    if baseline is None or baseline + 1 >= len(series):
        return None
    return baseline, baseline + 1


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator - 1.0


def compute_reactions(
    db: Session,
    ticker: str,
    *,
    series: PriceSeries | None = None,
) -> list[EarningsReaction]:
    ticker = ticker.upper()
    if series is None:
        series = load_price_series(db, ticker)
    events = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.ticker == ticker, EarningsEvent.date <= date.today())
        .order_by(EarningsEvent.date.asc())
    ).all()

    reactions: list[EarningsReaction] = []
    for ev in events:
        resolved = _resolve_anchor(series, ev.date, ev.timing)
        if resolved is None:
            continue
        baseline_idx, anchor_idx = resolved
        baseline_close = series.close[baseline_idx]
        anchor_close = series.close[anchor_idx]
        anchor_open = series.open[anchor_idx]

        move = _pct(anchor_close, baseline_close)
        gap = _pct(anchor_open, baseline_close)

        drifts = {h: _drift_at(series, anchor_idx, anchor_close, h) for h in DRIFT_HORIZONS}

        surprise = None
        beat = None
        if ev.eps_actual is not None and ev.eps_estimate not in (None, 0):
            surprise = ev.eps_actual / abs(ev.eps_estimate) - 1.0
            beat = ev.eps_actual >= ev.eps_estimate

        reactions.append(
            EarningsReaction(
                date=ev.date.isoformat(),
                timing=ev.timing,
                eps_estimate=ev.eps_estimate,
                eps_actual=ev.eps_actual,
                surprise_pct=_round(surprise),
                beat=beat,
                move_pct=_round(move),
                gap_pct=_round(gap),
                drift_pct=_round(drifts[DRIFT_DAYS]),
                drift_1d_pct=_round(drifts[1]),
                drift_10d_pct=_round(drifts[10]),
            )
        )
    return reactions


def _drift_at(
    series: PriceSeries, anchor_idx: int, anchor_close: float | None, horizon: int
) -> float | None:
    idx = anchor_idx + horizon
    if idx >= len(series):
        return None
    return _pct(series.close[idx], anchor_close)


def summarize(reactions: list[EarningsReaction]) -> ReactionSummary:
    moves = [r.move_pct for r in reactions if r.move_pct is not None]
    drifts = [r.drift_pct for r in reactions if r.drift_pct is not None]

    if not moves:
        return ReactionSummary(
            sample_size=0,
            avg_abs_move_pct=None,
            median_abs_move_pct=None,
            avg_move_pct=None,
            up_rate=None,
            last_move_pct=None,
            beat_rate=None,
            beat_streak=_beat_streak(reactions),
            avg_move_on_beat_pct=None,
            avg_move_on_miss_pct=None,
            avg_drift_pct=None,
            avg_drift_after_beat_pct=None,
            avg_drift_after_miss_pct=None,
            continuation_rate=None,
        )

    abs_moves = [abs(m) for m in moves]
    beats = [r for r in reactions if r.beat is True and r.move_pct is not None]
    misses = [r for r in reactions if r.beat is False and r.move_pct is not None]
    beat_known = [r for r in reactions if r.beat is not None]

    drift_after_beat = [
        r.drift_pct for r in reactions if r.beat is True and r.drift_pct is not None
    ]
    drift_after_miss = [
        r.drift_pct for r in reactions if r.beat is False and r.drift_pct is not None
    ]
    continuation = [
        r
        for r in reactions
        if r.move_pct not in (None, 0) and r.drift_pct is not None
    ]
    continuation_rate = (
        sum(1 for r in continuation if _same_sign(r.move_pct, r.drift_pct))
        / len(continuation)
        if continuation
        else None
    )

    return ReactionSummary(
        sample_size=len(moves),
        avg_abs_move_pct=_round(statistics.fmean(abs_moves)),
        median_abs_move_pct=_round(statistics.median(abs_moves)),
        avg_move_pct=_round(statistics.fmean(moves)),
        up_rate=_round(sum(1 for m in moves if m > 0) / len(moves)),
        last_move_pct=reactions[-1].move_pct,
        beat_rate=(
            _round(sum(1 for r in beat_known if r.beat) / len(beat_known))
            if beat_known
            else None
        ),
        beat_streak=_beat_streak(reactions),
        avg_move_on_beat_pct=(
            _round(statistics.fmean([r.move_pct for r in beats])) if beats else None
        ),
        avg_move_on_miss_pct=(
            _round(statistics.fmean([r.move_pct for r in misses])) if misses else None
        ),
        avg_drift_pct=_round(statistics.fmean(drifts)) if drifts else None,
        avg_drift_after_beat_pct=(
            _round(statistics.fmean(drift_after_beat)) if drift_after_beat else None
        ),
        avg_drift_after_miss_pct=(
            _round(statistics.fmean(drift_after_miss)) if drift_after_miss else None
        ),
        continuation_rate=_round(continuation_rate),
    )


def reaction_payload(db: Session, ticker: str) -> dict:
    reactions = compute_reactions(db, ticker)
    summary = summarize(reactions)
    return {
        "summary": asdict(summary),
        "events": [asdict(r) for r in reactions],
    }


def _beat_streak(reactions: list[EarningsReaction]) -> int:
    """Consecutive beats counting back from the most recent known result."""
    streak = 0
    for r in reversed(reactions):
        if r.beat is None:
            continue
        if r.beat:
            streak += 1
        else:
            break
    return streak


def _same_sign(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return (a > 0 and b > 0) or (a < 0 and b < 0)


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)
