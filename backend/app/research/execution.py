"""Execution-quality attribution (learning loop phase 3).

The signal-attribution report (``attribution.py``) grades *closed trades* on their
realized P&L. That conflates three very different things into one number:

  1. **Signal quality** — was the directional lean right at all?
  2. **Entry timing** — did we get in before the move, or chase it late?
  3. **Exit timing** — of the move that was actually there, how much did we keep?

This module decomposes them, so "the trade lost money" can be diagnosed as a bad
signal vs. a good signal we entered late or exited badly. Nothing here needs new
data: the decision store already carries direction-adjusted forward moves
(``fav_move_1d/5d``) for *every* decision — opened and skipped — and the daily
``price_bars`` give an intraday high/low path to measure excursions against.

Sections:
  - **signal_quality**: over ALL decisions (opened + skipped), the underlying's
    direction-adjusted move at +1d/+5d — i.e. was the lean right, regardless of
    whether or how we traded it. Grouped overall / by strategy / by conviction,
    plus an opened-vs-skipped split (are we opening the good signals?).
  - **entry_timing**: for opened trades, the lag from decision to fill and how
    much of the favorable move had already happened before we got in (chasing).
  - **exit_capture**: for closed directional trades, the max favorable excursion
    (MFE) and max adverse excursion (MAE) of the underlying while we held, vs.
    what we still had at exit — a capture ratio that isolates exit timing.
  - **signal_weeks**: signal hit-rate / avg +5d move by decision vintage (the week
    the signal fired), so slow-to-close strategies aren't hidden by close-date.

Pure numpy; reuses the CI primitives from ``attribution``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PaperTrade, PriceBar, TradeDecision
from app.research.attribution import mean_ci, wilson_interval

DEFAULT_MIN_SAMPLES = 5

# Strategies whose objective is to *ride* a directional move — the ones where an
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


# --- signal quality ----------------------------------------------------------


def _signal_group(rows: list[TradeDecision], min_samples: int) -> dict | None:
    """Hit rate + avg forward move for a set of decisions (execution-agnostic)."""
    fav5 = [r.fav_move_5d for r in rows if r.fav_move_5d is not None]
    if len(fav5) < min_samples:
        return None
    fav1 = [r.fav_move_1d for r in rows if r.fav_move_1d is not None]
    arr5 = np.array(fav5, dtype=float)
    wins = int(np.sum(arr5 > 0))
    n = len(fav5)
    return {
        "n": n,
        "hit_rate": round(wins / n, 3),
        "hit_rate_ci": list(wilson_interval(wins, n)),
        "avg_fav_move_5d": round(float(np.mean(arr5)), 4),
        "avg_fav_move_5d_ci": mean_ci(arr5),
        "avg_fav_move_1d": round(float(np.mean(fav1)), 4) if fav1 else None,
    }


def _signal_quality(rows: list[TradeDecision], min_samples: int) -> dict:
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
            g = _signal_group(items, min_samples)
            if g:
                out.append({"key": key, **g})
        out.sort(key=lambda d: d["avg_fav_move_5d"], reverse=True)
        return out

    opened = [r for r in graded if r.decision == "opened"]
    skipped = [r for r in graded if r.decision == "skipped"]

    return {
        "overall": _signal_group(graded, min_samples=1),
        "by_strategy": by("strategy"),
        "by_conviction": by("conviction"),
        "opened_vs_skipped": {
            "opened": _signal_group(opened, min_samples=1),
            "skipped": _signal_group(skipped, min_samples=1),
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
        # filled — a plausible "chased it" flag.
        "chased_rate": (
            round(float(np.mean(pre_arr > 0.02)), 3) if pre_arr is not None else None
        ),
        "chased_threshold": 0.02,
    }


# --- exit timing / capture ---------------------------------------------------


def _excursions(
    db: Session, trade: PaperTrade
) -> tuple[float, float] | None:
    """(MFE, MAE) of the underlying while the position was held, direction-adjusted.

    Uses daily high/low bars from the fill date through the close date. MFE is the
    best favorable excursion available; MAE the worst adverse. Returns None when
    we can't anchor an entry price or no bars cover the hold."""
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
    favs: list[float] = []
    advs: list[float] = []
    long = trade.direction == "bullish"
    for b in bars:
        hi = b.high if b.high is not None else b.close
        lo = b.low if b.low is not None else b.close
        if hi is None or lo is None:
            continue
        if long:
            favs.append(hi / entry - 1)
            advs.append(lo / entry - 1)
        else:  # bearish: price down is favorable
            favs.append(1 - lo / entry)
            advs.append(1 - hi / entry)
    if not favs:
        return None
    return (round(max(favs), 4), round(min(advs), 4))


def _exit_capture(
    db: Session, pairs: list[tuple[TradeDecision, PaperTrade]], min_samples: int
) -> dict:
    """For closed directional trades: of the favorable move that was actually
    available while we held (MFE), how much did we still have at exit?"""
    per: list[dict] = []
    for row, trade in pairs:
        strat = (trade.strategy or row.strategy or "").lower()
        if strat not in _DIRECTIONAL:
            continue
        if trade.status != "closed" or trade.realized_move_pct is None:
            continue
        exc = _excursions(db, trade)
        if exc is None:
            continue
        mfe, mae = exc
        realized_fav = _fav(trade.realized_move_pct, trade.direction)
        if realized_fav is None:
            continue
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
        })

    n = len(per)
    caps = [p["capture_ratio"] for p in per if p["capture_ratio"] is not None]
    mfes = np.array([p["mfe"] for p in per], dtype=float) if per else None
    maes = np.array([p["mae"] for p in per], dtype=float) if per else None
    holds = [p["hold_days"] for p in per if p["hold_days"] is not None]

    summary = {
        "n": n,
        "median_capture_ratio": (round(float(np.median(caps)), 3) if caps else None),
        "avg_mfe": (round(float(np.mean(mfes)), 4) if mfes is not None else None),
        "avg_mae": (round(float(np.mean(maes)), 4) if maes is not None else None),
        # Share of trades where we kept less than half of the peak move.
        "left_on_table_rate": (
            round(float(np.mean(np.array(caps) < 0.5)), 3) if caps else None
        ),
        "avg_hold_days": (round(float(np.mean(holds)), 1) if holds else None),
    }
    # Worst offenders: biggest give-backs, for a concrete "we should have exited
    # sooner here" list. Only surfaced when we have enough samples to be fair.
    worst: list[dict] = []
    if n >= min_samples:
        worst = sorted(per, key=lambda p: p["gave_back"], reverse=True)[:5]
    return {"summary": summary, "worst_giveback": worst, "graded": n}


# --- weekly signal vintage ---------------------------------------------------


def _signal_weeks(rows: list[TradeDecision], weeks: int) -> list[dict]:
    """Signal hit-rate + avg +5d move by the week the decision fired (vintage),
    so a strategy that takes weeks to close isn't hidden by close-date bucketing."""
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
            })
            continue
        arr = np.array([r.fav_move_5d for r in items], dtype=float)
        out.append({
            "label": start.strftime("%b %d"),
            "week_start": start.isoformat(),
            "n": n,
            "hit_rate": round(float(np.mean(arr > 0)), 3),
            "avg_fav_move_5d": round(float(np.mean(arr)), 4),
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

    notes = [
        "Signal quality is the underlying's direction-adjusted move after the "
        "decision — it grades the lean itself, independent of whether or how we "
        "traded it (skips included). Entry/exit timing then explain how much of "
        "that available move our execution actually kept.",
    ]
    if graded_signals < 20:
        notes.insert(
            0,
            f"Only {graded_signals} decisions have a resolved +5d move so far — "
            "directional, not conclusive. It tightens as more bars print.",
        )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "graded_signals": graded_signals,
        "min_samples": min_samples,
        "signal_quality": _signal_quality(decisions, min_samples),
        "entry_timing": _entry_timing(pairs),
        "exit_capture": _exit_capture(db, pairs, min_samples),
        "signal_weeks": _signal_weeks(decisions, weeks),
        "notes": notes,
    }


def _print_report(report: dict) -> None:
    print(f"\nExecution quality — {report['graded_signals']} graded signals\n" + "=" * 60)
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
