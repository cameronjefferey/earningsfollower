"""Signal attribution over the trade-decision feature store (learning loop phase 2).

Answers "which signals actually predict winners?" from the ``trade_decisions``
table — honestly, with sample sizes and confidence intervals front and centre so
a two-trade cohort can't masquerade as an edge. Deliberately statistics, not an
LLM: at this scale the right tool is proportion/mean CIs and correlations, which
are calibrated and reproducible.

What it computes:
  - Cohort scorecards (by strategy / conviction / direction / structure / pump
    risk / scorer / regime): n, win rate + Wilson 95% CI, total & avg P&L with a
    mean CI, and a calibration gap (avg predicted win_prob vs. realized win rate).
  - Numeric-feature attribution: for each entry feature, its correlation with the
    win/loss outcome and with P&L (Pearson r + Fisher 95% CI), plus a tercile
    split showing win rate / avg P&L across low→high values.
  - Calibration: predicted win_prob vs. realized win rate, bucketed.
  - Counterfactual: opened vs. skipped setups compared on the underlying's
    direction-adjusted +5d move — i.e. did the gate reject would-be winners?

Pure numpy (no scipy/sklearn) so it adds no deployment weight.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import TradeDecision

# Don't report a cohort/feature thinner than this — it's noise, not signal.
DEFAULT_MIN_SAMPLES = 5

# Numeric entry features worth attributing, with a human label. Only those with
# enough non-null values are reported.
_NUMERIC_FEATURES: list[tuple[str, str]] = [
    ("win_prob", "Model win prob"),
    ("expected_move_pct", "Implied move %"),
    ("seller_edge", "Seller edge"),
    ("seller_edge_at_strike", "Seller edge @ strike"),
    ("exceed_rate", "Exceed rate"),
    ("richness", "IV richness"),
    ("dir_score", "Direction score"),
    ("edge_sample", "Edge sample size"),
    ("drift_edge_5d", "Drift edge 5d"),
    ("surprise_pct", "Earnings surprise %"),
    ("move_pct", "Post-earnings move %"),
    ("trigger_move_pct", "Wave trigger move %"),
    ("expected_runup_pct", "Wave expected run-up %"),
    ("hist_win_rate", "Historical win rate"),
    ("hist_samples", "Historical samples"),
    ("sentiment", "Reddit sentiment"),
    ("mention_velocity", "Reddit mention velocity"),
    ("max_risk", "Max risk $"),
]

# Categorical dimensions to build cohort scorecards over.
_COHORT_DIMS: list[tuple[str, str]] = [
    ("strategy", "Strategy"),
    ("conviction", "Conviction"),
    ("direction", "Direction"),
    ("structure", "Structure"),
    ("pump_risk", "Reddit pump risk"),
    ("scored_by", "Reddit scorer"),
    ("playbook_version", "Playbook version"),
]


# --- stats primitives (numpy only) -------------------------------------------


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion — well-behaved for the
    small, lopsided samples a trade journal produces (unlike the normal approx)."""
    if n <= 0:
        return (0.0, 0.0)
    phat = wins / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


# t critical values (two-sided 95%) for small df; ~1.96 asymptote beyond.
_T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 25: 2.060,
    30: 2.042,
}


def _t_crit(df: int) -> float:
    if df <= 0:
        return float("nan")
    if df in _T95:
        return _T95[df]
    if df > 30:
        return 1.96
    keys = sorted(_T95)
    lo = max(k for k in keys if k <= df)
    return _T95[lo]


def mean_ci(values: np.ndarray) -> tuple[float, float] | None:
    """95% CI for a mean via the t-distribution (honest for small n)."""
    n = len(values)
    if n < 2:
        return None
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1))
    se = sd / math.sqrt(n)
    half = _t_crit(n - 1) * se
    return (round(mean - half, 2), round(mean + half, 2))


def pearson_ci(x: np.ndarray, y: np.ndarray) -> dict | None:
    """Pearson r with a Fisher z-transform 95% CI. ``significant`` is True when the
    CI excludes 0 (a defensible 'this feature actually moves the needle' flag)."""
    n = len(x)
    if n < 4 or np.std(x) == 0 or np.std(y) == 0:
        return None
    r = float(np.corrcoef(x, y)[0, 1])
    if not math.isfinite(r):
        return None
    r = max(min(r, 0.999999), -0.999999)
    z = math.atanh(r)
    se = 1 / math.sqrt(n - 3)
    lo, hi = math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)
    return {
        "r": round(r, 3),
        "ci": [round(lo, 3), round(hi, 3)],
        "n": n,
        "significant": lo > 0 or hi < 0,
    }


# --- data loading ------------------------------------------------------------


def _closed(db: Session) -> list[TradeDecision]:
    """Opened decisions with a realized P&L label — the trades we can grade."""
    return db.scalars(
        select(TradeDecision).where(
            TradeDecision.decision == "opened",
            TradeDecision.realized_pnl.is_not(None),
        )
    ).all()


def _is_win(row: TradeDecision) -> bool:
    if row.outcome in ("win", "loss"):
        return row.outcome == "win"
    return (row.realized_pnl or 0) > 0


# --- report sections ---------------------------------------------------------


def _cohort_rows(rows: list[TradeDecision], attr: str, min_samples: int) -> list[dict]:
    buckets: dict[str, list[TradeDecision]] = {}
    for r in rows:
        key = getattr(r, attr, None)
        if key is None:
            continue
        buckets.setdefault(str(key), []).append(r)

    out: list[dict] = []
    for key, items in buckets.items():
        n = len(items)
        if n < min_samples:
            continue
        wins = sum(1 for r in items if _is_win(r))
        pnls = np.array([r.realized_pnl for r in items], dtype=float)
        win_probs = [r.win_prob for r in items if r.win_prob is not None]
        win_rate = wins / n
        avg_pred = float(np.mean(win_probs)) if win_probs else None
        out.append({
            "key": key,
            "n": n,
            "wins": wins,
            "win_rate": round(win_rate, 3),
            "win_rate_ci": list(wilson_interval(wins, n)),
            "total_pnl": round(float(np.sum(pnls)), 2),
            "avg_pnl": round(float(np.mean(pnls)), 2),
            "avg_pnl_ci": mean_ci(pnls),
            "avg_win_prob": round(avg_pred, 3) if avg_pred is not None else None,
            # Positive gap = we won more than the model predicted (under-confident).
            "calibration_gap": (
                round(win_rate - avg_pred, 3) if avg_pred is not None else None
            ),
        })
    out.sort(key=lambda d: d["avg_pnl"], reverse=True)
    return out


def _numeric_attribution(rows: list[TradeDecision], min_samples: int) -> list[dict]:
    out: list[dict] = []
    for attr, label in _NUMERIC_FEATURES:
        pairs = [
            (getattr(r, attr), r.realized_pnl, 1.0 if _is_win(r) else 0.0)
            for r in rows
            if getattr(r, attr, None) is not None and r.realized_pnl is not None
        ]
        if len(pairs) < max(min_samples, 4):
            continue
        feat = np.array([p[0] for p in pairs], dtype=float)
        pnl = np.array([p[1] for p in pairs], dtype=float)
        win = np.array([p[2] for p in pairs], dtype=float)
        if np.std(feat) == 0:
            continue
        corr_win = pearson_ci(feat, win)
        corr_pnl = pearson_ci(feat, pnl)
        out.append({
            "feature": attr,
            "label": label,
            "n": len(pairs),
            "corr_win": corr_win,
            "corr_pnl": corr_pnl,
            "terciles": _terciles(feat, pnl, win),
        })
    # Surface the most decisive first: significant P&L correlations, by |r|.
    out.sort(
        key=lambda d: (
            (d["corr_pnl"] or {}).get("significant", False),
            abs((d["corr_pnl"] or {}).get("r", 0.0)),
        ),
        reverse=True,
    )
    return out


def _terciles(feat: np.ndarray, pnl: np.ndarray, win: np.ndarray) -> list[dict]:
    """Split the feature into low/mid/high thirds and report each third's win rate
    and avg P&L — a monotone gradient is the visual 'this signal matters' tell."""
    order = np.argsort(feat)
    thirds = np.array_split(order, 3)
    labels = ["low", "mid", "high"]
    out: list[dict] = []
    for lab, idx in zip(labels, thirds):
        if len(idx) == 0:
            continue
        fv = feat[idx]
        out.append({
            "band": lab,
            "range": [round(float(fv.min()), 4), round(float(fv.max()), 4)],
            "n": int(len(idx)),
            "win_rate": round(float(np.mean(win[idx])), 3),
            "avg_pnl": round(float(np.mean(pnl[idx])), 2),
        })
    return out


def _calibration(rows: list[TradeDecision]) -> dict:
    """Predicted win_prob vs. realized win rate, in fixed probability buckets."""
    graded = [(r.win_prob, _is_win(r)) for r in rows if r.win_prob is not None]
    edges = [0.0, 0.45, 0.55, 0.65, 0.8, 1.01]
    buckets: list[dict] = []
    for lo, hi in zip(edges, edges[1:]):
        items = [w for p, w in graded if lo <= p < hi]
        if not items:
            continue
        n = len(items)
        wins = sum(1 for w in items if w)
        preds = [p for p, w in graded if lo <= p < hi]
        buckets.append({
            "range": [lo, round(hi, 2)],
            "n": n,
            "avg_predicted": round(float(np.mean(preds)), 3),
            "realized_win_rate": round(wins / n, 3),
        })
    n_all = len(graded)
    return {
        "n": n_all,
        "avg_predicted": (
            round(float(np.mean([p for p, _ in graded])), 3) if graded else None
        ),
        "realized_win_rate": (
            round(sum(1 for _, w in graded if w) / n_all, 3) if n_all else None
        ),
        "buckets": buckets,
    }


def _counterfactual(db: Session, min_samples: int) -> list[dict]:
    """Compare opened vs. skipped setups on the underlying's direction-adjusted
    +5d move, per strategy. If skipped setups moved favorably about as often as
    opened ones, the gate may be rejecting winners (worth a look)."""
    rows = db.scalars(
        select(TradeDecision).where(TradeDecision.fav_move_5d.is_not(None))
    ).all()
    by: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        strat = r.strategy or "?"
        side = "opened" if r.decision == "opened" else "skipped"
        by.setdefault(strat, {"opened": [], "skipped": []})[side].append(r.fav_move_5d)

    def _summ(vals: list[float]) -> dict | None:
        if len(vals) < min_samples:
            return None
        arr = np.array(vals, dtype=float)
        return {
            "n": len(vals),
            "avg_fav_move_5d": round(float(np.mean(arr)), 4),
            "up_rate": round(float(np.mean(arr > 0)), 3),
        }

    out: list[dict] = []
    for strat, sides in sorted(by.items()):
        opened = _summ(sides["opened"])
        skipped = _summ(sides["skipped"])
        if opened is None and skipped is None:
            continue
        out.append({"strategy": strat, "opened": opened, "skipped": skipped})
    return out


def _overall(rows: list[TradeDecision]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0, "wins": 0, "win_rate": None, "total_pnl": 0.0, "avg_pnl": None}
    pnls = np.array([r.realized_pnl for r in rows], dtype=float)
    wins = sum(1 for r in rows if _is_win(r))
    return {
        "n": n,
        "wins": wins,
        "win_rate": round(wins / n, 3),
        "total_pnl": round(float(np.sum(pnls)), 2),
        "avg_pnl": round(float(np.mean(pnls)), 2),
    }


def attribution_report(db: Session, min_samples: int = DEFAULT_MIN_SAMPLES) -> dict:
    """Assemble the full signal-attribution report from the feature store."""
    rows = _closed(db)
    n = len(rows)

    notes: list[str] = []
    if n < 20:
        notes.append(
            f"Only {n} graded trades so far — treat every number as directional, "
            "not conclusive. Confidence intervals will tighten as more trades close."
        )
    notes.append(
        "Correlations are associations, not proof of causation, and cohorts overlap "
        "(a high-conviction earnings trade appears in several). Use this to form "
        "hypotheses, then confirm as the sample grows."
    )

    cohorts = {
        f"by_{attr}": _cohort_rows(rows, attr, min_samples)
        for attr, _label in _COHORT_DIMS
    }
    cohort_labels = {f"by_{attr}": label for attr, label in _COHORT_DIMS}

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "graded_trades": n,
        "overall": _overall(rows),
        "min_samples": min_samples,
        "cohort_labels": cohort_labels,
        "cohorts": cohorts,
        "numeric_features": _numeric_attribution(rows, min_samples),
        "calibration": _calibration(rows),
        "counterfactual": _counterfactual(db, min_samples),
        "notes": notes,
    }


def _print_report(report: dict) -> None:
    print(f"\nSignal attribution — {report['graded_trades']} graded trades\n" + "=" * 60)
    for note in report["notes"]:
        print(f"  note: {note}")
    for key, rows in report["cohorts"].items():
        if not rows:
            continue
        print(f"\n{report['cohort_labels'].get(key, key)}")
        for r in rows:
            lo, hi = r["win_rate_ci"]
            print(
                f"  {r['key']:<28} n={r['n']:<4} win={r['win_rate']:.0%} "
                f"[{lo:.0%},{hi:.0%}]  avg P&L ${r['avg_pnl']:>8.2f}  "
                f"total ${r['total_pnl']:>9.2f}"
            )
    print("\nNumeric features (corr with P&L)")
    for f in report["numeric_features"]:
        cp = f["corr_pnl"] or {}
        sig = "*" if cp.get("significant") else " "
        print(
            f"  {sig} {f['label']:<26} n={f['n']:<4} "
            f"r={cp.get('r', float('nan')):+.2f} ci={cp.get('ci')}"
        )
    print()


def main() -> None:
    from app.db.session import SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        _print_report(attribution_report(db))


if __name__ == "__main__":
    main()
