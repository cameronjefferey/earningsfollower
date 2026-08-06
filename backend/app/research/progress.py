"""Week-to-week learning tracker (learning loop phase 4).

The attribution report is a point-in-time read; this reconstructs it at each past
week-end from the immutable decision store and diffs the weeks, so you can see the
exact summary of what changed and whether the model actually got better — honestly,
including the weeks it regressed. If the metrics don't improve as evidence
accumulates (and as we act on it), that's the experiment telling you something.

"Getting better" is measured on four axes, week over week:
  - calibration gap |predicted - realized| shrinking (predictions more honest),
  - realized win rate / avg P&L of trades that closed *that week*,
  - the count of statistically significant entry features rising (finding signal),
  - cumulative graded sample growing (tighter confidence in everything above).

Nothing is stored: every week is recomputed from the append-only journal, so the
series can never drift from the underlying truth.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PaperTrade, TradeDecision
from app.research.attribution import _is_win, attribution_report

# Threshold below which a delta is treated as flat (noise), not a real change.
_EPS = 0.005


def _week_windows(weeks: int, now: datetime | None = None) -> list[dict]:
    """The last ``weeks`` ISO weeks (Monday-based), oldest first. Each carries the
    week's date span and an exclusive end datetime to use as the ``as_of`` cutoff."""
    now = now or datetime.utcnow()
    monday = now.date() - timedelta(days=now.date().weekday())
    out: list[dict] = []
    for i in range(weeks - 1, -1, -1):
        start = monday - timedelta(weeks=i)
        end = start + timedelta(days=7)  # next Monday (exclusive)
        out.append({
            "start": start,
            "end": end,
            "end_dt": datetime.combine(end, time.min),
            "label": start.strftime("%b %d"),
        })
    return out


def _calibration_gap(report: dict) -> float | None:
    c = report.get("calibration") or {}
    pred, real = c.get("avg_predicted"), c.get("realized_win_rate")
    if pred is None or real is None:
        return None
    return round(abs(real - pred), 3)


def _significant_features(report: dict) -> int:
    return sum(
        1
        for f in report.get("numeric_features", [])
        if (f.get("corr_pnl") or {}).get("significant")
    )


def _window_perf(db: Session, start: date, end: date) -> dict:
    """Performance of trades whose position CLOSED within [start, end)."""
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time.min)
    rows = db.scalars(
        select(TradeDecision)
        .join(PaperTrade, PaperTrade.signal_id == TradeDecision.signal_id)
        .where(
            TradeDecision.decision == "opened",
            TradeDecision.realized_pnl.is_not(None),
            PaperTrade.closed_at.is_not(None),
            PaperTrade.closed_at >= start_dt,
            PaperTrade.closed_at < end_dt,
        )
    ).all()
    n = len(rows)
    if not n:
        return {"closed": 0, "wins": 0, "win_rate": None, "avg_pnl": None, "total_pnl": 0.0}
    pnls = np.array([r.realized_pnl for r in rows], dtype=float)
    wins = sum(1 for r in rows if _is_win(r))
    return {
        "closed": n,
        "wins": wins,
        "win_rate": round(wins / n, 3),
        "avg_pnl": round(float(np.mean(pnls)), 2),
        "total_pnl": round(float(np.sum(pnls)), 2),
    }


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _money(v) -> str:
    if v is None:
        return "—"
    sign = "-" if v < 0 else "+" if v > 0 else ""
    return f"{sign}${abs(v):,.0f}"


def _delta(cur, prev):
    if cur is None or prev is None:
        return None
    return round(cur - prev, 4)


def _week_changes(cur: dict, prev: dict | None) -> tuple[list[str], int]:
    """Plain-English 'what changed' lines plus a net improvement score."""
    changes: list[str] = []
    score = 0
    cc, cn = cur["cumulative"], cur["new_this_week"]

    if cn["closed"]:
        changes.append(
            f"{cn['closed']} trade(s) closed this week — {_pct(cn['win_rate'])} wins, "
            f"about {_money(cn['avg_pnl'])} each ({_money(cn['total_pnl'])} total)."
        )
        if cn["avg_pnl"] is not None:
            if cn["avg_pnl"] > 0:
                score += 1
            elif cn["avg_pnl"] < 0:
                score -= 1
    else:
        changes.append("No trades closed this week.")

    if prev is None:
        return changes, score
    pc = prev["cumulative"]

    gap_d = _delta(cc["calibration_gap"], pc["calibration_gap"])
    if gap_d is not None and abs(gap_d) >= _EPS:
        better = gap_d < 0
        score += 1 if better else -1
        changes.append(
            f"{'Predictions got closer to reality' if better else 'Predictions drifted further from reality'} "
            f"({_pct(pc['calibration_gap'])} → {_pct(cc['calibration_gap'])} miss)."
        )

    wr_d = _delta(cc["win_rate"], pc["win_rate"])
    if wr_d is not None and abs(wr_d) >= _EPS:
        score += 1 if wr_d > 0 else -1
        changes.append(
            f"Overall win rate moved {_pct(pc['win_rate'])} → {_pct(cc['win_rate'])}."
        )

    sf_d = cc["significant_features"] - pc["significant_features"]
    if sf_d:
        score += 1 if sf_d > 0 else -1
        changes.append(
            f"{'Found' if sf_d > 0 else 'Lost'} {abs(sf_d)} clear pattern"
            f"{'' if abs(sf_d) == 1 else 's'} linking entry clues to winners "
            f"({pc['significant_features']} → {cc['significant_features']})."
        )

    gt_d = cc["graded_trades"] - pc["graded_trades"]
    if gt_d:
        changes.append(f"+{gt_d} more closed trade(s) on the book (now {cc['graded_trades']}).")

    return changes, score


def progress_series(db: Session, weeks: int = 8, min_samples: int = 1) -> dict:
    """Reconstruct the weekly learning series with week-over-week deltas, a
    'what changed' summary per week, and an overall verdict on whether it's
    actually learning."""
    windows = _week_windows(weeks)
    series: list[dict] = []
    prev: dict | None = None
    for w in windows:
        report = attribution_report(db, min_samples=min_samples, as_of=w["end_dt"])
        overall = report.get("overall") or {}
        cumulative = {
            "graded_trades": overall.get("n", 0),
            "win_rate": overall.get("win_rate"),
            "avg_pnl": overall.get("avg_pnl"),
            "total_pnl": overall.get("total_pnl", 0.0),
            "calibration_gap": _calibration_gap(report),
            "significant_features": _significant_features(report),
        }
        week = {
            "label": w["label"],
            "week_start": w["start"].isoformat(),
            "week_end": w["end"].isoformat(),
            "cumulative": cumulative,
            "new_this_week": _window_perf(db, w["start"], w["end"]),
        }
        changes, score = _week_changes(week, prev)
        week["changes"] = changes
        week["improvement_score"] = score
        week["status"] = "improved" if score > 0 else "regressed" if score < 0 else "flat"
        # Explicit deltas for the UI.
        if prev is not None:
            pc = prev["cumulative"]
            week["deltas"] = {
                "win_rate": _delta(cumulative["win_rate"], pc["win_rate"]),
                "calibration_gap": _delta(cumulative["calibration_gap"], pc["calibration_gap"]),
                "avg_pnl": _delta(cumulative["avg_pnl"], pc["avg_pnl"]),
                "graded_trades": cumulative["graded_trades"] - pc["graded_trades"],
                "significant_features": cumulative["significant_features"] - pc["significant_features"],
            }
        else:
            week["deltas"] = None
        series.append(week)
        prev = week

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "weeks": series,
        "verdict": _verdict(series),
    }


def _verdict(series: list[dict]) -> dict:
    """An honest, high-level read: is the experiment actually learning?"""
    graded = [w for w in series if w["cumulative"]["graded_trades"] > 0]
    if len(graded) < 2:
        return {
            "learning": None,
            "summary": (
                "Too early to call a trend — need at least two weeks with closed "
                "trades. This fills in as more paper trades finish."
            ),
        }

    scored = [w for w in series if w["deltas"] is not None and w["cumulative"]["graded_trades"] > 0]
    improved = sum(1 for w in scored if w["status"] == "improved")
    regressed = sum(1 for w in scored if w["status"] == "regressed")

    gaps = [w["cumulative"]["calibration_gap"] for w in graded if w["cumulative"]["calibration_gap"] is not None]
    gap_trend = None
    if len(gaps) >= 2:
        gap_trend = round(gaps[-1] - gaps[0], 3)  # negative = calibration improved

    first_wr = graded[0]["cumulative"]["win_rate"]
    last_wr = graded[-1]["cumulative"]["win_rate"]
    wr_trend = _delta(last_wr, first_wr)

    learning = None
    if scored:
        learning = improved > regressed or (gap_trend is not None and gap_trend < -_EPS)

    parts: list[str] = []
    if scored:
        parts.append(
            f"{improved} of {len(scored)} weeks got better; {regressed} got worse."
        )
    if gap_trend is not None:
        parts.append(
            f"Our odds calls got "
            f"{'closer to reality' if gap_trend < 0 else 'further from reality' if gap_trend > 0 else 'no clearer'} "
            f"by {_pct(abs(gap_trend))} over the window."
        )
    if wr_trend is not None and abs(wr_trend) >= _EPS:
        parts.append(
            f"Overall win rate is {'up' if wr_trend > 0 else 'down'} {_pct(abs(wr_trend))}."
        )
    if learning is False:
        parts.append(
            "No steady week-to-week improvement yet — if that continues as the "
            "sample grows, the edge may not be there."
        )

    return {
        "learning": learning,
        "weeks_improved": improved,
        "weeks_regressed": regressed,
        "calibration_gap_trend": gap_trend,
        "win_rate_trend": wr_trend,
        "summary": " ".join(parts) if parts else "Steady — nothing big changed across the window.",
    }


def _print(series: dict) -> None:
    print(f"\nWeekly learning tracker — {series['verdict']['summary']}\n" + "=" * 70)
    for w in series["weeks"]:
        c = w["cumulative"]
        print(
            f"\n{w['label']} [{w['status']}]  graded={c['graded_trades']} "
            f"win={_pct(c['win_rate'])} calGap={_pct(c['calibration_gap'])} "
            f"sigFeat={c['significant_features']}"
        )
        for line in w["changes"]:
            print(f"    - {line}")


def main() -> None:
    from app.db.session import SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        _print(progress_series(db))


if __name__ == "__main__":
    main()
