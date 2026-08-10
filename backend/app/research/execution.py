"""Execution-quality attribution (learning loop phase 3).

The signal-attribution report (``attribution.py``) grades *closed trades* on their
realized P&L. That conflates three very different things into one number:

  1. **Signal quality** - was the directional lean right at all?
  2. **Entry timing** - did we get in before the move, or chase it late?
  3. **Exit timing** - of the move that was actually there, how much did we keep?

This module decomposes them, so "the trade lost money" can be diagnosed as a bad
signal vs. a good signal we entered late or exited badly. Nothing here needs new
data: the decision store already carries direction-adjusted forward moves
(``fav_move_1d/5d``) for *every* decision - opened and skipped - and the daily
``price_bars`` give an intraday high/low path to measure excursions against.

Sections:
  - **signal_quality**: over ALL decisions (opened + skipped), the underlying's
    direction-adjusted move at +1d/+5d - i.e. was the lean right, regardless of
    whether or how we traded it. Grouped overall / by strategy / by conviction,
    plus an opened-vs-skipped split (are we opening the good signals?).
  - **entry_timing**: for opened trades, the lag from decision to fill and how
    much of the favorable move had already happened before we got in (chasing).
  - **exit_capture**: for closed directional trades, the max favorable excursion
    (MFE) and max adverse excursion (MAE) of the underlying while we held, vs.
    what we still had at exit - a capture ratio that isolates exit timing.
  - **signal_weeks**: signal hit-rate / avg +5d move by decision vintage (the week
    the signal fired), so slow-to-close strategies aren't hidden by close-date.

Pure numpy; reuses the CI primitives from ``attribution``.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PaperTrade, PriceBar, TradeDecision
from app.research.attribution import mean_ci, wilson_interval

DEFAULT_MIN_SAMPLES = 5

# A day needs at least this many names with a prior close to count as a market
# read (below it, the equal-weight return is one or two names, i.e. noise).
_MIN_BREADTH = 5

# Strategies whose objective is to *ride* a directional move - the ones where an
# underlying capture ratio is a meaningful read of exit timing. Sell-vol earnings
# trades win on IV crush / staying inside a range, so a directional capture ratio
# doesn't apply to them; they're covered by adverse excursion instead.
_DIRECTIONAL = {"waves", "drift", "reddit", "reddit_equity", "earnings_equity"}


def _fav(move: float | None, direction: str | None) -> float | None:
    """Direction-adjust a signed entry->price move so positive = thesis correct."""
    if move is None:
        return None
    if direction == "bullish":
        return move
    if direction == "bearish":
        return -move
    return None


# --- market baseline (beta strip) --------------------------------------------
#
# The naive objection to "the signal's +5d move is positive" is that equities
# drift up and a bullish-tilted book inherits that beta for free. So we net out
# a market baseline: an equal-weight index of EVERY covered name (the universe we
# actually pick from), rebuilt from the same daily bars. Excess = the signal's
# direction-adjusted move minus the index's move over the identical window -
# what's left after the market/earnings-season tailwind is removed. Using our own
# universe (rather than SPY) also strips the earnings-season selection effect and
# needs no extra data, so it works on the existing record immediately.


def _market_index(
    db: Session, start: date, end: date
) -> tuple[list[date], np.ndarray]:
    """Equal-weight daily-return index of the covered universe over [start, end],
    returned as (sorted trading dates, index levels). Each day's return is the
    mean single-day return across names that have a prior close; days with fewer
    than ``_MIN_BREADTH`` contributors still advance but are inherently noisier."""
    rows = db.execute(
        select(PriceBar.ticker, PriceBar.date, PriceBar.close)
        .where(
            PriceBar.date >= start,
            PriceBar.date <= end,
            PriceBar.close.is_not(None),
        )
        .order_by(PriceBar.ticker.asc(), PriceBar.date.asc())
    ).all()

    ret_by_date: dict[date, list[float]] = defaultdict(list)
    last_ticker = None
    last_close = None
    for tk, d, c in rows:
        if tk != last_ticker:
            last_ticker, last_close = tk, c
            continue
        if last_close and last_close > 0 and c and c > 0:
            ret_by_date[d].append(c / last_close - 1)
        last_close = c

    dates = sorted(ret_by_date)
    levels: list[float] = []
    lvl = 1.0
    for d in dates:
        vals = ret_by_date[d]
        lvl *= 1 + (float(np.mean(vals)) if vals else 0.0)
        levels.append(lvl)
    return dates, np.array(levels, dtype=float)


def _mkt_move(dates: list[date], levels: np.ndarray, ref: date, n: int) -> float | None:
    """Index return over the n trading days strictly after ``ref``, anchored on the
    last level at/just before ``ref`` - mirroring how a signal's fav_move is taken
    from its entry to the n-th bar after."""
    if not dates:
        return None
    base_i = bisect.bisect_right(dates, ref) - 1
    fwd_i = bisect.bisect_right(dates, ref) + (n - 1)
    if base_i < 0 or fwd_i >= len(dates):
        return None
    base = levels[base_i]
    if base <= 0:
        return None
    return float(levels[fwd_i] / base - 1)


def _excess_map(db: Session, decisions: list[TradeDecision]) -> dict[int, float]:
    """Per-decision excess +5d move (signal fav move minus the direction-adjusted
    market move over the same window). Only for rows with a resolved fav_move_5d
    and a computable benchmark."""
    graded = [r for r in decisions if r.fav_move_5d is not None and r.decision_date]
    if not graded:
        return {}
    start = min(r.decision_date for r in graded) - timedelta(days=10)
    end = datetime.utcnow().date()
    dates, levels = _market_index(db, start, end)
    out: dict[int, float] = {}
    for r in graded:
        mkt = _mkt_move(dates, levels, r.decision_date, 5)
        bench = _fav(mkt, r.direction)
        if bench is None:
            continue
        out[r.id] = round(r.fav_move_5d - bench, 4)
    return out


# --- signal quality ----------------------------------------------------------


def _signal_group(
    rows: list[TradeDecision], excess: dict[int, float], min_samples: int
) -> dict | None:
    """Hit rate + avg forward move for a set of decisions (execution-agnostic),
    both raw and net of the market baseline (excess)."""
    fav5 = [r.fav_move_5d for r in rows if r.fav_move_5d is not None]
    if len(fav5) < min_samples:
        return None
    fav1 = [r.fav_move_1d for r in rows if r.fav_move_1d is not None]
    arr5 = np.array(fav5, dtype=float)
    wins = int(np.sum(arr5 > 0))
    n = len(fav5)

    exc = [excess[r.id] for r in rows if r.id in excess]
    exc_arr = np.array(exc, dtype=float) if exc else None
    beat = int(np.sum(exc_arr > 0)) if exc_arr is not None else 0

    return {
        "n": n,
        "hit_rate": round(wins / n, 3),
        "hit_rate_ci": list(wilson_interval(wins, n)),
        "avg_fav_move_5d": round(float(np.mean(arr5)), 4),
        "avg_fav_move_5d_ci": mean_ci(arr5),
        "avg_fav_move_1d": round(float(np.mean(fav1)), 4) if fav1 else None,
        # Market-baseline-adjusted: what's left after netting out the universe.
        "n_excess": len(exc) if exc_arr is not None else 0,
        "avg_excess_move_5d": (
            round(float(np.mean(exc_arr)), 4) if exc_arr is not None else None
        ),
        "avg_excess_move_5d_ci": mean_ci(exc_arr) if exc_arr is not None else None,
        "beat_rate": (
            round(beat / len(exc), 3) if exc_arr is not None else None
        ),
        "beat_rate_ci": (
            list(wilson_interval(beat, len(exc))) if exc_arr is not None else None
        ),
    }


def _signal_quality(
    rows: list[TradeDecision], excess: dict[int, float], min_samples: int
) -> dict:
    graded = [r for r in rows if r.fav_move_5d is not None]

    def by(attr: str) -> list[dict]:
        buckets: dict[str, list[TradeDecision]] = {}
        for r in graded:
            key = getattr(r, attr, None)
            if key is None:
                continue
            buckets.setdefault(str(key), []).append(r)
        out = []
        for key, items in buckets.items():
            g = _signal_group(items, excess, min_samples)
            if g:
                out.append({"key": key, **g})
        # Rank by the beta-stripped edge when available, else raw.
        out.sort(
            key=lambda d: (
                d["avg_excess_move_5d"]
                if d["avg_excess_move_5d"] is not None
                else d["avg_fav_move_5d"]
            ),
            reverse=True,
        )
        return out

    opened = [r for r in graded if r.decision == "opened"]
    skipped = [r for r in graded if r.decision == "skipped"]

    return {
        "overall": _signal_group(graded, excess, min_samples=1),
        "by_strategy": by("strategy"),
        "by_conviction": by("conviction"),
        "opened_vs_skipped": {
            "opened": _signal_group(opened, excess, min_samples=1),
            "skipped": _signal_group(skipped, excess, min_samples=1),
        },
    }


# --- entry timing ------------------------------------------------------------


def _entry_timing(pairs: list[tuple[TradeDecision, PaperTrade]]) -> dict:
    """How late did we get in? Lag (decision->fill) and the favorable move that
    had already happened between the decision spot and our entry spot (chasing)."""
    lags: list[int] = []
    pre_moves: list[float] = []
    for row, trade in pairs:
        if trade.opened_at and row.decision_date:
            lags.append((trade.opened_at.date() - row.decision_date).days)
        dspot = row.spot
        espot = trade.spot_entry
        if dspot and espot and dspot > 0:
            fav = _fav(espot / dspot - 1, row.direction)
            if fav is not None:
                pre_moves.append(fav)
    n = len(pairs)
    pre_arr = np.array(pre_moves, dtype=float) if pre_moves else None
    return {
        "n": n,
        "median_lag_days": (round(float(np.median(lags)), 1) if lags else None),
        "avg_pre_entry_fav_move": (
            round(float(np.mean(pre_arr)), 4) if pre_arr is not None else None
        ),
        # Share where the underlying had already moved >2% our way before we
        # filled - a plausible "chased it" flag.
        "chased_rate": (
            round(float(np.mean(pre_arr > 0.02)), 3) if pre_arr is not None else None
        ),
        "chased_threshold": 0.02,
    }


# --- exit timing / capture ---------------------------------------------------


# A trade's thesis only "played out" if the underlying actually moved our way at
# all - capture on trades that never went favorable measures signal quality, not
# exit timing. Only trades whose MFE cleared this hurdle count toward the honest
# capture read (isolating the exit decision).
_MFE_HURDLE = 0.01


def _fav_path(db: Session, trade: PaperTrade) -> dict | None:
    """The position's direction-adjusted daily path while held: for each day the
    best (favorable), worst (adverse), and closing excursion from entry. Plus MFE,
    MAE, and the realized favorable move at the actual exit. None when unpriceable.

    Uses ``adj_close``-consistent bars (falls back to raw close) so splits during a
    hold don't fabricate a move. Favorable is sign-flipped for shorts so positive
    always means 'toward the thesis'."""
    entry = trade.spot_entry
    if not entry or entry <= 0 or not trade.opened_at:
        return None
    end = (trade.closed_at or datetime.utcnow()).date()
    bars = db.scalars(
        select(PriceBar)
        .where(
            PriceBar.ticker == trade.ticker,
            PriceBar.date >= trade.opened_at.date(),
            PriceBar.date <= end,
        )
        .order_by(PriceBar.date.asc())
    ).all()
    if not bars:
        return None
    long = trade.direction == "bullish"
    days: list[tuple[float, float, float]] = []
    for b in bars:
        cl = b.adj_close if b.adj_close is not None else b.close
        hi = b.high if b.high is not None else cl
        lo = b.low if b.low is not None else cl
        if hi is None or lo is None or cl is None:
            continue
        if long:
            best, worst, end_ = hi / entry - 1, lo / entry - 1, cl / entry - 1
        else:  # short: price down is favorable
            best, worst, end_ = 1 - lo / entry, 1 - hi / entry, 1 - cl / entry
        days.append((round(best, 4), round(worst, 4), round(end_, 4)))
    if not days:
        return None
    realized = _fav(trade.realized_move_pct, trade.direction)
    return {
        "days": days,
        "mfe": round(max(d[0] for d in days), 4),
        "mae": round(min(d[1] for d in days), 4),
        "realized": None if realized is None else round(realized, 4),
    }


def _exit_capture(
    db: Session, pairs: list[tuple[TradeDecision, PaperTrade]], min_samples: int
) -> dict:
    """For closed directional trades: of the favorable move that was actually
    available while we held (MFE), how much did we still have at exit?

    Reported two ways: over ALL directional exits (contaminated by trades that
    never worked), and - the honest read of exit *timing* - conditioned on trades
    whose MFE cleared the hurdle, so the signal actually played out and the only
    question left is whether we harvested it."""
    per: list[dict] = []
    for row, trade in pairs:
        strat = (trade.strategy or row.strategy or "").lower()
        if strat not in _DIRECTIONAL:
            continue
        if trade.status != "closed" or trade.realized_move_pct is None:
            continue
        path = _fav_path(db, trade)
        if path is None or path["realized"] is None:
            continue
        mfe, mae, realized_fav = path["mfe"], path["mae"], path["realized"]
        capture = round(realized_fav / mfe, 3) if mfe > 1e-6 else None
        hold_days = (
            (trade.closed_at.date() - trade.opened_at.date()).days
            if trade.closed_at and trade.opened_at
            else None
        )
        per.append({
            "signal_id": trade.signal_id,
            "ticker": trade.ticker,
            "strategy": strat,
            "mfe": mfe,
            "mae": mae,
            "realized_fav_move": round(realized_fav, 4),
            "gave_back": round(max(mfe - realized_fav, 0.0), 4),
            "capture_ratio": capture,
            "hold_days": hold_days,
            "played_out": mfe >= _MFE_HURDLE,
        })

    def _summ(rows: list[dict]) -> dict:
        caps = [p["capture_ratio"] for p in rows if p["capture_ratio"] is not None]
        mfes = np.array([p["mfe"] for p in rows], dtype=float) if rows else None
        maes = np.array([p["mae"] for p in rows], dtype=float) if rows else None
        holds = [p["hold_days"] for p in rows if p["hold_days"] is not None]
        return {
            "n": len(rows),
            "median_capture_ratio": (round(float(np.median(caps)), 3) if caps else None),
            "avg_capture_ratio": (round(float(np.mean(caps)), 3) if caps else None),
            "avg_mfe": (round(float(np.mean(mfes)), 4) if mfes is not None else None),
            "avg_mae": (round(float(np.mean(maes)), 4) if maes is not None else None),
            "left_on_table_rate": (
                round(float(np.mean(np.array(caps) < 0.5)), 3) if caps else None
            ),
            "avg_hold_days": (round(float(np.mean(holds)), 1) if holds else None),
        }

    played = [p for p in per if p["played_out"]]
    worst: list[dict] = []
    if len(played) >= min_samples:
        worst = sorted(played, key=lambda p: p["gave_back"], reverse=True)[:5]
    return {
        "summary": _summ(per),  # all directional exits (signal + exit blended)
        "played_out": _summ(played),  # honest exit-timing read (MFE cleared hurdle)
        "mfe_hurdle": _MFE_HURDLE,
        "worst_giveback": worst,
        "graded": len(per),
    }


# --- exit-policy backtest ----------------------------------------------------
#
# Counterfactual: replay each closed directional trade's real daily path under
# candidate exit rules and measure what each would have captured vs. how we
# actually exited. This isolates the ONE thing we fully control - when to get out
# - and quantifies the P&L left on the table. Honest caveats: (1) it's the
# underlying's path, an exact read for the equity books but a proxy for option
# spreads (capped, path-dependent payoff); (2) rule params are chosen on this same
# sample, so treat the "best" as an in-sample upper bound to confirm walk-forward,
# not a promise. Intraday order is resolved conservatively: stops/adverse checked
# before take-profits on the same day, and TP/stop fills are AT the level (resting
# limit/stop), never at the extreme tick.


def _sim_exit(
    days: list[tuple[float, float, float]],
    realized: float,
    *,
    take_profit: float | None = None,
    stop_loss: float | None = None,
    trail: float | None = None,
    time_stop: int | None = None,
) -> float:
    """Favorable move a rule would have captured on this path. Falls back to the
    actual realized move on days the rule never fires."""
    peak = float("-inf")
    for idx, (best, worst, end_) in enumerate(days):
        if stop_loss is not None and worst <= -stop_loss:
            return -stop_loss
        if trail is not None and peak > float("-inf") and (peak - worst) >= trail:
            return round(peak - trail, 4)
        if take_profit is not None and best >= take_profit:
            return take_profit
        if time_stop is not None and (idx + 1) >= time_stop:
            return end_
        peak = max(peak, best)
    return realized


# Small, deliberately coarse policy grid (limits overfitting). Each is (label,
# kwargs); "Actual" is the baseline we actually traded.
_POLICIES: list[tuple[str, dict]] = [
    ("Actual (as traded)", {}),
    ("Time-stop 2d", {"time_stop": 2}),
    ("Time-stop 3d", {"time_stop": 3}),
    ("Take-profit 3%", {"take_profit": 0.03}),
    ("Take-profit 5%", {"take_profit": 0.05}),
    ("TP 3% / stop 3%", {"take_profit": 0.03, "stop_loss": 0.03}),
    ("Trailing 2%", {"trail": 0.02}),
    ("TP 5% / trail 3%", {"take_profit": 0.05, "trail": 0.03}),
]


def _exit_policy(
    db: Session, pairs: list[tuple[TradeDecision, PaperTrade]], min_samples: int
) -> dict:
    """Backtest candidate exit rules against the real paths of closed directional
    trades, ranked by average favorable move captured, with the lift over how we
    actually exited."""
    paths: list[dict] = []
    for row, trade in pairs:
        strat = (trade.strategy or row.strategy or "").lower()
        if strat not in _DIRECTIONAL:
            continue
        if trade.status != "closed" or trade.realized_move_pct is None:
            continue
        p = _fav_path(db, trade)
        if p is None or p["realized"] is None:
            continue
        paths.append(p)

    n = len(paths)
    if n == 0:
        return {"n": 0, "policies": [], "best": None}

    results: list[dict] = []
    baseline_avg = None
    for label, kw in _POLICIES:
        if not kw:  # baseline = actual realized
            caps = np.array([p["realized"] for p in paths], dtype=float)
        else:
            caps = np.array(
                [_sim_exit(p["days"], p["realized"], **kw) for p in paths],
                dtype=float,
            )
        avg = round(float(np.mean(caps)), 4)
        if not kw:
            baseline_avg = avg
        results.append({
            "label": label,
            "avg_captured": avg,
            "median_captured": round(float(np.median(caps)), 4),
            "win_rate": round(float(np.mean(caps > 0)), 3),
            "params": kw,
        })

    for r in results:
        r["lift_vs_actual"] = (
            round(r["avg_captured"] - baseline_avg, 4)
            if baseline_avg is not None
            else None
        )

    ranked = sorted(results, key=lambda r: r["avg_captured"], reverse=True)
    # Best = top non-baseline policy, only when we have enough trades to be fair
    # and it actually beats how we traded.
    best = None
    if n >= min_samples:
        for r in ranked:
            if r["params"] and (r["lift_vs_actual"] or 0) > 0:
                best = r
                break
    return {"n": n, "policies": ranked, "best": best}


# --- weekly signal vintage ---------------------------------------------------


def _signal_weeks(
    rows: list[TradeDecision], excess: dict[int, float], weeks: int
) -> list[dict]:
    """Signal hit-rate + avg +5d move (raw and excess-of-market) by the week the
    decision fired (vintage), so a strategy that takes weeks to close isn't hidden
    by close-date bucketing. Non-overlapping weeks - each is an independent cohort,
    not a cumulative snapshot."""
    now = datetime.utcnow().date()
    monday = now - timedelta(days=now.weekday())
    out: list[dict] = []
    for i in range(weeks - 1, -1, -1):
        start = monday - timedelta(weeks=i)
        end = start + timedelta(days=7)
        items = [
            r
            for r in rows
            if r.fav_move_5d is not None and start <= r.decision_date < end
        ]
        n = len(items)
        if n == 0:
            out.append({
                "label": start.strftime("%b %d"),
                "week_start": start.isoformat(),
                "n": 0,
                "hit_rate": None,
                "avg_fav_move_5d": None,
                "avg_excess_move_5d": None,
            })
            continue
        arr = np.array([r.fav_move_5d for r in items], dtype=float)
        exc = [excess[r.id] for r in items if r.id in excess]
        out.append({
            "label": start.strftime("%b %d"),
            "week_start": start.isoformat(),
            "n": n,
            "hit_rate": round(float(np.mean(arr > 0)), 3),
            "avg_fav_move_5d": round(float(np.mean(arr)), 4),
            "avg_excess_move_5d": (
                round(float(np.mean(exc)), 4) if exc else None
            ),
        })
    return out


# --- assembly ----------------------------------------------------------------


def execution_report(
    db: Session, min_samples: int = DEFAULT_MIN_SAMPLES, weeks: int = 8
) -> dict:
    """Assemble the execution-quality report: signal vs. entry vs. exit."""
    decisions = db.scalars(select(TradeDecision)).all()

    # Opened decisions linked to their trade (for entry/exit timing).
    trades_by_sig = {
        t.signal_id: t
        for t in db.scalars(select(PaperTrade)).all()
        if t.signal_id
    }
    pairs: list[tuple[TradeDecision, PaperTrade]] = [
        (r, trades_by_sig[r.signal_id])
        for r in decisions
        if r.decision == "opened" and r.signal_id in trades_by_sig
    ]

    graded_signals = sum(1 for r in decisions if r.fav_move_5d is not None)
    excess = _excess_map(db, decisions)

    signal_quality = _signal_quality(decisions, excess, min_samples)

    # Top-line honest read: after netting out the market, is there edge at all?
    overall = signal_quality["overall"]
    baseline = None
    if overall and overall.get("avg_excess_move_5d") is not None:
        ci = overall.get("avg_excess_move_5d_ci")
        # "Edge" only if the excess CI is entirely above zero - otherwise it's
        # indistinguishable from just owning the market.
        beats = bool(ci and ci[0] > 0)
        baseline = {
            "n": overall.get("n_excess", 0),
            "avg_excess_move_5d": overall["avg_excess_move_5d"],
            "avg_excess_move_5d_ci": ci,
            "beat_rate": overall.get("beat_rate"),
            "significant": beats,
        }

    notes = [
        "Signal quality is the underlying's direction-adjusted move after the "
        "decision - it grades the lean itself, independent of whether or how we "
        "traded it (skips included). Entry/exit timing then explain how much of "
        "that available move our execution actually kept.",
        "Excess move nets out an equal-weight index of every covered name over the "
        "identical window, so a positive raw move that just tracks the market shows "
        "as zero excess. Edge = excess whose 95% CI clears zero; anything else is "
        "beta, not alpha.",
    ]
    if graded_signals < 20:
        notes.insert(
            0,
            f"Only {graded_signals} decisions have a resolved +5d move so far - "
            "directional, not conclusive. It tightens as more bars print.",
        )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "graded_signals": graded_signals,
        "min_samples": min_samples,
        "market_baseline": baseline,
        "signal_quality": signal_quality,
        "entry_timing": _entry_timing(pairs),
        "exit_capture": _exit_capture(db, pairs, min_samples),
        "exit_policy": _exit_policy(db, pairs, min_samples),
        "signal_weeks": _signal_weeks(decisions, excess, weeks),
        "notes": notes,
    }


def _print_report(report: dict) -> None:
    print(f"\nExecution quality - {report['graded_signals']} graded signals\n" + "=" * 60)
    sq = report["signal_quality"]["overall"]
    if sq:
        print(
            f"Signal (all decisions): n={sq['n']} hit={sq['hit_rate']:.0%} "
            f"avg +5d={sq['avg_fav_move_5d']:+.2%}"
        )
    et = report["entry_timing"]
    print(
        f"Entry: n={et['n']} median lag={et['median_lag_days']}d "
        f"pre-entry fav={et['avg_pre_entry_fav_move']}"
    )
    ec = report["exit_capture"]["summary"]
    print(
        f"Exit: n={ec['n']} median capture={ec['median_capture_ratio']} "
        f"avg MFE={ec['avg_mfe']} avg MAE={ec['avg_mae']}"
    )


def main() -> None:
    from app.db.session import SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        _print_report(execution_report(db))


if __name__ == "__main__":
    main()
