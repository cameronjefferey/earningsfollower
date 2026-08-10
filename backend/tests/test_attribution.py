"""Unit tests for the signal-attribution stats and report assembly.

Runnable without pytest (``python tests/test_attribution.py`` from the backend
dir) and also collectable by pytest. Uses an in-memory SQLite DB.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, TradeDecision  # noqa: E402
from app.research.attribution import (  # noqa: E402
    attribution_report,
    mean_ci,
    pearson_ci,
    wilson_interval,
)


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


# --- stats primitives --------------------------------------------------------


def test_wilson_interval_bounds_and_ordering():
    lo, hi = wilson_interval(8, 10)
    assert 0.0 <= lo < 0.8 < hi <= 1.0
    # More data at the same rate tightens the interval.
    lo2, hi2 = wilson_interval(80, 100)
    assert (hi2 - lo2) < (hi - lo)
    # Degenerate n is safe.
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_mean_ci_brackets_the_mean():
    vals = np.array([100.0, 120.0, 80.0, 110.0, 90.0])
    ci = mean_ci(vals)
    assert ci is not None
    assert ci[0] < float(np.mean(vals)) < ci[1]
    assert mean_ci(np.array([5.0])) is None  # n<2


def test_pearson_ci_flags_significance():
    x = np.arange(30, dtype=float)
    y = 2 * x + 1  # perfectly correlated
    res = pearson_ci(x, y)
    assert res is not None
    assert res["r"] > 0.99 and res["significant"] is True
    # Pure noise around a constant relationship shouldn't be flagged significant.
    rng = np.random.default_rng(0)
    noise = pearson_ci(rng.normal(size=40), rng.normal(size=40))
    assert noise is not None and noise["significant"] is False


# --- end-to-end report -------------------------------------------------------


def _mk(**kw) -> TradeDecision:
    base = dict(
        decision_date=date(2026, 7, 1),
        strategy="earnings",
        ticker="AAA",
        decision="opened",
        label_status="final",
    )
    base.update(kw)
    return TradeDecision(**base)


def test_attribution_report_finds_a_planted_edge():
    """Plant a clean signal: high win_prob trades win and make money, low ones
    lose. The report should recover the cohort split and a positive win_prob
    correlation with P&L."""
    db = _session()
    # 12 winners tagged high conviction / high win_prob.
    for i in range(12):
        db.add(_mk(
            ticker=f"W{i}", conviction="high", direction="bullish",
            win_prob=0.8, realized_pnl=200.0 + i, outcome="win",
        ))
    # 12 losers tagged low conviction / low win_prob.
    for i in range(12):
        db.add(_mk(
            ticker=f"L{i}", conviction="low", direction="bearish",
            win_prob=0.45, realized_pnl=-150.0 - i, outcome="loss",
        ))
    db.commit()

    rep = attribution_report(db, min_samples=5)
    assert rep["graded_trades"] == 24

    by_conv = {r["key"]: r for r in rep["cohorts"]["by_conviction"]}
    assert by_conv["high"]["win_rate"] == 1.0
    assert by_conv["low"]["win_rate"] == 0.0
    # Wilson CIs are present and ordered.
    assert by_conv["high"]["win_rate_ci"][0] < by_conv["high"]["win_rate_ci"][1]
    # Higher-conviction cohort has the better avg P&L (sorted first).
    assert rep["cohorts"]["by_conviction"][0]["key"] == "high"

    feats = {f["feature"]: f for f in rep["numeric_features"]}
    assert "win_prob" in feats
    assert feats["win_prob"]["corr_pnl"]["r"] > 0.9
    assert feats["win_prob"]["corr_pnl"]["significant"] is True
    # Tercile gradient: low third loses, high third wins.
    terc = feats["win_prob"]["terciles"]
    assert terc[0]["avg_pnl"] < 0 < terc[-1]["avg_pnl"]


def test_attribution_respects_min_samples():
    db = _session()
    for i in range(3):  # below the floor
        db.add(_mk(ticker=f"S{i}", conviction="medium", win_prob=0.6, realized_pnl=10.0))
    db.commit()
    rep = attribution_report(db, min_samples=5)
    assert rep["cohorts"]["by_conviction"] == []  # too thin to report


def test_counterfactual_compares_opened_vs_skipped():
    db = _session()
    # Opened setups drifted favorably; skipped ones drifted against - the gate
    # was right to skip. Both cohorts need >= min_samples.
    for i in range(6):
        db.add(_mk(
            ticker=f"O{i}", decision="opened", realized_pnl=50.0,
            fav_move_5d=0.04, direction="bullish",
        ))
    for i in range(6):
        db.add(_mk(
            ticker=f"K{i}", decision="skipped", realized_pnl=None,
            label_status="final", fav_move_5d=-0.03, direction="bullish",
        ))
    db.commit()
    rep = attribution_report(db, min_samples=5)
    cf = {c["strategy"]: c for c in rep["counterfactual"]}
    assert "earnings" in cf
    assert cf["earnings"]["opened"]["up_rate"] == 1.0
    assert cf["earnings"]["skipped"]["up_rate"] == 0.0


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
