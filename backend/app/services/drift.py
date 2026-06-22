"""Post-earnings announcement drift (PEAD) screen.

The anomaly: stocks that beat estimates and react strongly UP tend to keep
drifting up for the next ~5-10 trading days; big misses that sell off tend to
keep drifting down. This service screens names that just reported for live,
actionable drift setups, backed by each stock's own historical drift behavior.

Everything is computed from data the refresh already ingests (earnings events
and daily price bars) - no new data pipeline.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, EarningsEvent
from app.services.peers import shared_themes
from app.services.prices import load_price_series
from app.services.reactions import _resolve_anchor, compute_reactions

# The horizon the historical edge is measured over (matches reactions.DRIFT_DAYS).
HOLD_TRADING_DAYS = 5
EXTENDED_HOLD_DAYS = 10
# Setups older than this many trading days are no longer actionable.
MAX_DAYS_IN = 7
# Minimum earnings-day reaction to qualify as a "strong" print.
MIN_REACTION = 0.02
# Minimum similar past events needed to trust the historical edge.
MIN_SAMPLE = 3
# Minimum historical average drift (in trade direction) to call it an edge.
MIN_EDGE = 0.005


@dataclass
class DriftHistory:
    """How this stock drifted after past prints similar to the current one."""

    sample_size: int
    avg_drift_5d_pct: float | None
    win_rate_5d: float | None
    avg_drift_10d_pct: float | None
    win_rate_10d: float | None


@dataclass
class DriftLive:
    """Where the trade stands right now."""

    anchor_date: str  # first close that fully reflects the report
    anchor_open: float | None
    anchor_close: float | None
    last_date: str
    last_close: float | None
    drift_so_far_pct: float | None
    trading_days_in: int
    trading_days_left: int
    # Closing beyond this level means the drift thesis is broken (exit signal).
    stop_level: float | None


@dataclass
class DriftPlan:
    """Concrete instructions: when to get in, when to get out, when to bail."""

    entry: str
    exit: str
    stop: str
    entry_quality: str  # "fresh" | "ok" | "late"


@dataclass
class DriftSetup:
    ticker: str
    name: str | None
    sector: str | None
    market_cap: float | None
    themes: list[dict]
    direction: str  # "long" | "short"
    score: float
    report_date: str
    timing: str
    beat: bool
    surprise_pct: float | None
    revenue_beat: bool | None
    move_pct: float | None
    gap_pct: float | None
    held_gap: bool | None
    history: DriftHistory
    live: DriftLive
    plan: DriftPlan
    why: list[str]


def drift_setups(db: Session, *, lookback_days: int = 12, limit: int = 30) -> list[dict]:
    """Screen everything that reported in the last `lookback_days` for live
    PEAD setups, scored and sorted by attractiveness."""
    today = date.today()
    events = db.scalars(
        select(EarningsEvent)
        .where(
            EarningsEvent.date >= today - timedelta(days=lookback_days),
            EarningsEvent.date <= today,
            EarningsEvent.eps_actual.is_not(None),
        )
        .order_by(EarningsEvent.date.desc())
    ).all()

    setups: list[DriftSetup] = []
    seen: set[str] = set()
    for ev in events:
        if ev.ticker in seen:
            continue
        seen.add(ev.ticker)
        setup = _evaluate(db, ev)
        if setup is not None:
            setups.append(setup)

    setups.sort(key=lambda s: s.score, reverse=True)
    return [asdict(s) for s in setups[:limit]]


def _evaluate(db: Session, ev: EarningsEvent) -> DriftSetup | None:
    ticker = ev.ticker.upper()
    series = load_price_series(db, ticker)
    resolved = _resolve_anchor(series, ev.date, ev.timing)
    if resolved is None:
        return None
    baseline_idx, anchor_idx = resolved

    baseline_close = series.close[baseline_idx]
    anchor_open = series.open[anchor_idx]
    anchor_close = series.close[anchor_idx]
    if not baseline_close or not anchor_close:
        return None

    move = anchor_close / baseline_close - 1.0
    gap = (anchor_open / baseline_close - 1.0) if anchor_open else None
    held_gap = (anchor_close >= anchor_open) if anchor_open else None

    beat = _beat(ev)
    if beat is None:
        return None

    # The two tradeable shapes: beat + strong up reaction (long the drift) or
    # miss + strong down reaction (short the drift). Anything else has no edge.
    if beat and move >= MIN_REACTION:
        direction = "long"
    elif not beat and move <= -MIN_REACTION:
        direction = "short"
    else:
        return None

    days_in = len(series) - 1 - anchor_idx
    if days_in > MAX_DAYS_IN:
        return None

    history = _history(db, ticker, ev.date, direction)
    if history.sample_size < MIN_SAMPLE or history.avg_drift_5d_pct is None:
        return None
    # Require the stock's own past drift to actually point the same way.
    edge = history.avg_drift_5d_pct if direction == "long" else -history.avg_drift_5d_pct
    if edge < MIN_EDGE:
        return None

    last_close = series.close[-1]
    drift_so_far = (
        last_close / anchor_close - 1.0 if last_close and anchor_close else None
    )

    # Stop reference: the earnings-day pivot. A long that closes back below it
    # (or a short back above it) has a broken thesis and is no longer a setup.
    candidates = [p for p in (anchor_open, anchor_close) if p]
    stop_level = (min(candidates) if direction == "long" else max(candidates)) if candidates else None
    if stop_level and last_close:
        if direction == "long" and last_close < stop_level:
            return None
        if direction == "short" and last_close > stop_level:
            return None

    # Past the 5-day window, the setup only stays alive if this stock's history
    # shows the drift keeps paying out to 10 days.
    extension_supported = (
        history.avg_drift_10d_pct is not None
        and history.avg_drift_5d_pct is not None
        and (
            history.avg_drift_10d_pct > history.avg_drift_5d_pct
            if direction == "long"
            else history.avg_drift_10d_pct < history.avg_drift_5d_pct
        )
    )
    if days_in >= HOLD_TRADING_DAYS and not extension_supported:
        return None

    surprise = None
    if ev.eps_actual is not None and ev.eps_estimate not in (None, 0):
        surprise = ev.eps_actual / abs(ev.eps_estimate) - 1.0

    revenue_beat = None
    if ev.revenue_actual is not None and ev.revenue_estimate not in (None, 0):
        revenue_beat = ev.revenue_actual >= ev.revenue_estimate

    live = DriftLive(
        anchor_date=series.dates[anchor_idx].isoformat(),
        anchor_open=_round(anchor_open, 2),
        anchor_close=_round(anchor_close, 2),
        last_date=series.dates[-1].isoformat(),
        last_close=_round(last_close, 2),
        drift_so_far_pct=_round(drift_so_far),
        trading_days_in=days_in,
        trading_days_left=max(0, HOLD_TRADING_DAYS - days_in),
        stop_level=_round(stop_level, 2),
    )

    score = _score(
        edge=edge,
        win_rate=(history.win_rate_5d or 0),
        sample=history.sample_size,
        move=move,
        days_in=days_in,
        held_gap=held_gap,
    )

    company = db.get(Company, ticker)
    plan = _plan(direction, history, live, extension_supported)
    why = _why(direction, ev, surprise, revenue_beat, move, held_gap, history, live)

    return DriftSetup(
        ticker=ticker,
        name=company.name if company else None,
        sector=company.sector if company else None,
        market_cap=company.market_cap if company else None,
        themes=shared_themes(db, ticker),
        direction=direction,
        score=score,
        report_date=ev.date.isoformat(),
        timing=ev.timing,
        beat=beat,
        surprise_pct=_round(surprise),
        revenue_beat=revenue_beat,
        move_pct=_round(move),
        gap_pct=_round(gap),
        held_gap=held_gap,
        history=history,
        live=live,
        plan=plan,
        why=why,
    )


def _history(
    db: Session, ticker: str, current_event: date, direction: str
) -> DriftHistory:
    """Drift stats from PAST prints with the same shape as the current one
    (beat + up reaction for longs, miss + down reaction for shorts)."""
    reactions = compute_reactions(db, ticker)
    if direction == "long":
        similar = [
            r
            for r in reactions
            if r.date != current_event.isoformat()
            and r.beat is True
            and r.move_pct is not None
            and r.move_pct > 0
        ]
    else:
        similar = [
            r
            for r in reactions
            if r.date != current_event.isoformat()
            and r.beat is False
            and r.move_pct is not None
            and r.move_pct < 0
        ]

    d5 = [r.drift_pct for r in similar if r.drift_pct is not None]
    d10 = [r.drift_10d_pct for r in similar if r.drift_10d_pct is not None]

    def _wins(values: list[float]) -> float | None:
        if not values:
            return None
        good = (lambda v: v > 0) if direction == "long" else (lambda v: v < 0)
        return sum(1 for v in values if good(v)) / len(values)

    return DriftHistory(
        sample_size=len(d5),
        avg_drift_5d_pct=_round(statistics.fmean(d5)) if d5 else None,
        win_rate_5d=_round(_wins(d5)),
        avg_drift_10d_pct=_round(statistics.fmean(d10)) if d10 else None,
        win_rate_10d=_round(_wins(d10)),
    )


def _score(
    *,
    edge: float,
    win_rate: float,
    sample: int,
    move: float,
    days_in: int,
    held_gap: bool | None,
) -> float:
    confidence = win_rate * min(sample / 6.0, 1.0)
    strength = min(abs(move) / 0.05, 1.5)  # a 5%+ print is a full-strength signal
    freshness = max(0.0, (HOLD_TRADING_DAYS - days_in) / HOLD_TRADING_DAYS)
    score = (
        (edge * 100)
        * confidence
        * (0.5 + 0.5 * strength)
        * (0.35 + 0.65 * freshness)
        * math.log1p(sample)
    )
    if held_gap:
        score *= 1.15
    return round(score, 3)


def _plan(
    direction: str,
    history: DriftHistory,
    live: DriftLive,
    extension_supported: bool,
) -> DriftPlan:
    long = direction == "long"
    verb = "Buy" if long else "Short"
    anchor = f"${live.anchor_close}" if live.anchor_close is not None else "the earnings-day close"
    stop_px = f"${live.stop_level}" if live.stop_level is not None else "the earnings-day low"

    if live.trading_days_in <= 1:
        quality = "fresh"
        entry = (
            f"{verb} now. The drift window just opened - the historical edge is "
            f"measured from the first post-earnings close ({anchor})."
        )
    elif live.trading_days_left >= 2:
        quality = "ok"
        pullback = "a dip" if long else "a bounce"
        entry = (
            f"{verb} {pullback} toward {anchor} (the earnings-day close). "
            f"{live.trading_days_in} of {HOLD_TRADING_DAYS} drift days are already gone, "
            "so don't chase an extended price."
        )
    else:
        quality = "late"
        entry = (
            "Late - most of the 5-day drift window has passed. Only enter if it's "
            f"breaking to new post-earnings {'highs' if long else 'lows'}, and size down."
        )

    if live.trading_days_left > 0:
        exit_txt = (
            f"{'Sell' if long else 'Cover'} after {live.trading_days_left} more trading "
            f"day{'s' if live.trading_days_left != 1 else ''} ({HOLD_TRADING_DAYS} trading days "
            "after the report) - that's the horizon the historical edge is measured over."
        )
        if extension_supported:
            exit_txt += (
                f" History supports holding up to {EXTENDED_HOLD_DAYS} days here "
                f"(avg {_signed(history.avg_drift_10d_pct)} vs "
                f"{_signed(history.avg_drift_5d_pct)} at 5 days)."
            )
    else:
        days_to_10 = max(0, EXTENDED_HOLD_DAYS - live.trading_days_in)
        exit_txt = (
            f"The 5-day window has closed, but this stock's drift historically keeps "
            f"paying to {EXTENDED_HOLD_DAYS} days (avg {_signed(history.avg_drift_10d_pct)} vs "
            f"{_signed(history.avg_drift_5d_pct)} at 5 days). "
            f"{'Sell' if long else 'Cover'} within {days_to_10} more trading "
            f"day{'s' if days_to_10 != 1 else ''}."
        )

    stop = (
        f"Bail early if it closes {'below' if long else 'above'} {stop_px} "
        f"(the earnings-day pivot). Giving back the whole post-earnings move "
        f"kills the drift thesis - don't wait out the full window."
    )

    return DriftPlan(entry=entry, exit=exit_txt, stop=stop, entry_quality=quality)


def _why(
    direction: str,
    ev: EarningsEvent,
    surprise: float | None,
    revenue_beat: bool | None,
    move: float,
    held_gap: bool | None,
    history: DriftHistory,
    live: DriftLive,
) -> list[str]:
    long = direction == "long"
    why: list[str] = []

    s = f" by {abs(surprise) * 100:.0f}%" if surprise is not None else ""
    if long:
        beat_txt = f"Beat EPS estimates{s}"
        if revenue_beat:
            beat_txt += " and beat on revenue"
        why.append(beat_txt + ".")
    else:
        miss_txt = f"Missed EPS estimates{s}"
        if revenue_beat is False:
            miss_txt += " and missed on revenue"
        why.append(miss_txt + ".")

    move_txt = f"Stock {'jumped' if long else 'dropped'} {_signed(move)} on the print"
    if held_gap and long:
        move_txt += " and closed above its open (buyers held control all day)"
    elif held_gap is False and not long:
        move_txt += " and closed below its open (sellers held control all day)"
    why.append(move_txt + ".")

    if history.avg_drift_5d_pct is not None and history.win_rate_5d is not None:
        why.append(
            f"After {history.sample_size} similar past prints "
            f"({'beat + up move' if long else 'miss + down move'}), this stock drifted "
            f"an average of {_signed(history.avg_drift_5d_pct)} more over the next "
            f"{HOLD_TRADING_DAYS} trading days, continuing "
            f"{'lower' if not long else 'higher'} {history.win_rate_5d * 100:.0f}% of the time."
        )

    if live.drift_so_far_pct is not None:
        days = live.trading_days_in
        why.append(
            f"{days} trading day{'s' if days != 1 else ''} in, it has drifted "
            f"{_signed(live.drift_so_far_pct)} since the earnings-day close - "
            + (
                "the move is still early."
                if abs(live.drift_so_far_pct) < abs(history.avg_drift_5d_pct or 0)
                else "a lot of the historical average drift has already happened."
            )
        )

    return why


# --- helpers -----------------------------------------------------------------


def _beat(ev: EarningsEvent) -> bool | None:
    if ev.eps_actual is None or ev.eps_estimate in (None, 0):
        return None
    return ev.eps_actual >= ev.eps_estimate


def _signed(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:+.1f}%"


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)
