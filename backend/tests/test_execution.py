"""Unit tests for the execution-quality decomposition (signal / entry / exit).

Runnable without pytest (``python tests/test_execution.py`` from the backend dir)
and also collectable by pytest. Uses an in-memory SQLite DB with planted values so
the MFE/MAE capture math and signal hit-rate are checked against known answers.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, PaperTrade, PriceBar, TradeDecision  # noqa: E402
from app.research.execution import execution_report  # noqa: E402


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _dec(**kw) -> TradeDecision:
    base = dict(
        decision_date=date(2026, 7, 1),
        strategy="drift",
        ticker="AAA",
        decision="opened",
        label_status="final",
        direction="bullish",
    )
    base.update(kw)
    return TradeDecision(**base)


def test_signal_quality_grades_the_lean_regardless_of_execution():
    """Signal quality reads fav_move_5d over opened AND skipped, so a good lean we
    skipped still counts as a good signal."""
    db = _session()
    # 6 opened with a right lean, 6 skipped that also would have been right.
    for i in range(6):
        db.add(_dec(ticker=f"O{i}", decision="opened", fav_move_5d=0.05, fav_move_1d=0.02))
    for i in range(6):
        db.add(_dec(ticker=f"K{i}", decision="skipped", signal_id=None,
                    fav_move_5d=0.03, fav_move_1d=0.01))
    # 4 opened with a wrong lean (drifted against the thesis).
    for i in range(4):
        db.add(_dec(ticker=f"B{i}", decision="opened", fav_move_5d=-0.04))
    db.commit()

    rep = execution_report(db, min_samples=5)
    assert rep["graded_signals"] == 16
    overall = rep["signal_quality"]["overall"]
    assert overall["n"] == 16
    # 12 of 16 had a positive forward move.
    assert overall["hit_rate"] == round(12 / 16, 3)

    ovs = rep["signal_quality"]["opened_vs_skipped"]
    assert ovs["opened"]["n"] == 10
    assert ovs["skipped"]["n"] == 6
    assert ovs["skipped"]["hit_rate"] == 1.0  # every skip's lean was right


def test_exit_capture_measures_giveback_from_the_price_path():
    """Plant a bullish drift trade: entry 100, ran to 120 (MFE +20%), but we
    exited at 110 (+10% realized) - capture should be ~0.5, give-back ~0.10."""
    db = _session()
    opened_at = datetime(2026, 7, 1, 14, 30)
    trade = PaperTrade(
        signal_id="SIG1", strategy="drift", ticker="AAA", direction="bullish",
        structure="Bull call spread", vol_stance="buy", conviction="high",
        status="closed", spot_entry=100.0, spot_at_exit=110.0,
        realized_move_pct=0.10, realized_pnl=250.0, outcome="win",
        opened_at=opened_at, closed_at=opened_at + timedelta(days=4),
    )
    db.add(trade)
    db.add(_dec(ticker="AAA", decision="opened", signal_id="SIG1",
                spot=100.0, fav_move_5d=0.10))
    # Daily path: peak high of 120 on day 2, exit day at 110.
    highs = [105, 120, 112, 110]
    lows = [98, 104, 108, 106]
    for i, (hi, lo) in enumerate(zip(highs, lows)):
        db.add(PriceBar(ticker="AAA", date=date(2026, 7, 1) + timedelta(days=i),
                        open=100.0, high=float(hi), low=float(lo), close=float(hi - 2)))
    db.commit()

    rep = execution_report(db, min_samples=1)
    ec = rep["exit_capture"]
    assert ec["graded"] == 1
    worst = ec["worst_giveback"][0]
    assert worst["mfe"] == 0.20  # (120/100 - 1)
    assert worst["realized_fav_move"] == 0.10
    assert worst["capture_ratio"] == 0.5  # 0.10 / 0.20
    assert worst["gave_back"] == 0.10
    assert worst["mae"] == round(98 / 100 - 1, 4)  # worst dip to 98 => -0.02


def test_exit_policy_recovers_giveback_and_conditions_capture():
    """Entry 100, ran to 120 (MFE +20%), we exited at +10%. A trailing/time-stop
    rule should show a positive lift vs. how we actually exited, and the honest
    (played-out) capture should include this trade since MFE cleared the hurdle."""
    db = _session()
    opened_at = datetime(2026, 7, 1, 14, 30)
    trade = PaperTrade(
        signal_id="SIGP", strategy="drift", ticker="AAA", direction="bullish",
        structure="Bull call spread", vol_stance="buy", conviction="high",
        status="closed", spot_entry=100.0, spot_at_exit=110.0,
        realized_move_pct=0.10, realized_pnl=250.0, outcome="win",
        opened_at=opened_at, closed_at=opened_at + timedelta(days=4),
    )
    db.add(trade)
    db.add(_dec(ticker="AAA", decision="opened", signal_id="SIGP",
                spot=100.0, fav_move_5d=0.10))
    highs = [105, 120, 112, 110]
    lows = [98, 104, 108, 106]
    for i, (hi, lo) in enumerate(zip(highs, lows)):
        db.add(PriceBar(ticker="AAA", date=date(2026, 7, 1) + timedelta(days=i),
                        open=100.0, high=float(hi), low=float(lo), close=float(hi - 2)))
    db.commit()

    rep = execution_report(db, min_samples=1)
    ep = rep["exit_policy"]
    assert ep["n"] == 1
    baseline = next(p for p in ep["policies"] if p["label"] == "Actual (as traded)")
    assert baseline["avg_captured"] == 0.10
    assert ep["best"] is not None
    assert ep["best"]["avg_captured"] > 0.10  # a rule kept more of the move
    assert ep["best"]["lift_vs_actual"] > 0

    played = rep["exit_capture"]["played_out"]
    assert played["n"] == 1  # MFE 0.20 >= hurdle, so it counts as exit timing
    assert played["median_capture_ratio"] == 0.5


def test_played_out_capture_excludes_signal_misses():
    """A trade whose underlying never moved favorably (MFE≈0) is a signal miss, not
    an exit-timing problem - it must be excluded from the played-out capture read."""
    db = _session()
    opened_at = datetime(2026, 7, 1, 14, 30)
    trade = PaperTrade(
        signal_id="SIGM", strategy="drift", ticker="ZZZ", direction="bullish",
        structure="Bull call spread", vol_stance="buy", conviction="low",
        status="closed", spot_entry=100.0, spot_at_exit=96.0,
        realized_move_pct=-0.04, realized_pnl=-120.0, outcome="loss",
        opened_at=opened_at, closed_at=opened_at + timedelta(days=2),
    )
    db.add(trade)
    db.add(_dec(ticker="ZZZ", decision="opened", signal_id="SIGM",
                spot=100.0, fav_move_5d=-0.04))
    # Only ever fell: never a favorable excursion above the entry.
    for i, (hi, lo) in enumerate([(100, 97), (99, 95), (97, 94)]):
        db.add(PriceBar(ticker="ZZZ", date=date(2026, 7, 1) + timedelta(days=i),
                        open=100.0, high=float(hi), low=float(lo), close=float(lo + 1)))
    db.commit()

    rep = execution_report(db, min_samples=1)
    ec = rep["exit_capture"]
    assert ec["summary"]["n"] == 1  # present in the blended read
    assert ec["played_out"]["n"] == 0  # but excluded from the honest exit-timing read


def test_exit_capture_handles_bearish_direction():
    """Bearish trade: entry 100, dropped to 80 (MFE +20% favorable), exited at 90
    (+10% realized favorable) - capture ~0.5."""
    db = _session()
    opened_at = datetime(2026, 7, 1, 14, 30)
    trade = PaperTrade(
        signal_id="SIG2", strategy="drift", ticker="BBB", direction="bearish",
        structure="Bear put spread", vol_stance="buy", conviction="high",
        status="closed", spot_entry=100.0, spot_at_exit=90.0,
        realized_move_pct=-0.10, realized_pnl=200.0, outcome="win",
        opened_at=opened_at, closed_at=opened_at + timedelta(days=3),
    )
    db.add(trade)
    db.add(_dec(ticker="BBB", decision="opened", signal_id="SIG2",
                direction="bearish", spot=100.0, fav_move_5d=0.10))
    lows = [95, 80, 88]
    highs = [101, 96, 92]
    for i, (hi, lo) in enumerate(zip(highs, lows)):
        db.add(PriceBar(ticker="BBB", date=date(2026, 7, 1) + timedelta(days=i),
                        open=100.0, high=float(hi), low=float(lo), close=float(lo + 1)))
    db.commit()

    rep = execution_report(db, min_samples=1)
    worst = rep["exit_capture"]["worst_giveback"][0]
    assert worst["mfe"] == round(1 - 80 / 100, 4)  # 0.20 favorable (price fell)
    assert worst["realized_fav_move"] == 0.10
    assert worst["capture_ratio"] == 0.5


def test_market_baseline_strips_beta():
    """The universe rises ~10% over the window. A signal that just tracks it should
    show ~0 excess; one that beats it by 10pts should show ~+0.10 excess."""
    db = _session()
    # Equal-weight universe: 6 names each compounding +2%/day, with history before
    # the decision so the anchor has a prior level ⇒ 5-day index move ≈ 10.4%.
    for m in range(6):
        for k in range(13):
            db.add(PriceBar(
                ticker=f"M{m}", date=date(2026, 7, 1) + timedelta(days=k),
                open=100.0, high=None, low=None, close=round(100 * (1.02 ** k), 4),
            ))
    # A reddit signal that only matched the market, and a drift signal that beat it.
    db.add(_dec(ticker="S", strategy="reddit", decision_date=date(2026, 7, 6),
                fav_move_5d=0.104))
    db.add(_dec(ticker="T", strategy="drift", decision_date=date(2026, 7, 6),
                fav_move_5d=0.204))
    db.commit()

    rep = execution_report(db, min_samples=1)
    base = rep["market_baseline"]
    assert base is not None and base["n"] == 2
    # Mean excess ≈ (0 + 0.10) / 2 = 0.05, and NOT significant (n=2, wide CI).
    assert abs(base["avg_excess_move_5d"] - 0.05) < 0.01
    assert base["significant"] is False

    by_strat = {c["key"]: c for c in rep["signal_quality"]["by_strategy"]}
    assert abs(by_strat["reddit"]["avg_excess_move_5d"]) < 0.01  # just beta
    assert abs(by_strat["drift"]["avg_excess_move_5d"] - 0.10) < 0.01  # real excess
    # Beta-stripped ranking puts the true-excess strategy first.
    assert rep["signal_quality"]["by_strategy"][0]["key"] == "drift"


def test_entry_timing_flags_chasing():
    """Decision spot 100, filled at 105 (already +5% our way) => chased."""
    db = _session()
    opened_at = datetime(2026, 7, 2, 15, 0)
    trade = PaperTrade(
        signal_id="SIG3", strategy="drift", ticker="CCC", direction="bullish",
        structure="Bull call spread", vol_stance="buy", conviction="med",
        status="closed", spot_entry=105.0, realized_move_pct=0.02,
        opened_at=opened_at, closed_at=opened_at + timedelta(days=2),
    )
    db.add(trade)
    db.add(_dec(ticker="CCC", decision="opened", signal_id="SIG3",
                decision_date=date(2026, 7, 1), spot=100.0, fav_move_5d=0.02))
    db.commit()

    rep = execution_report(db, min_samples=1)
    et = rep["entry_timing"]
    assert et["n"] == 1
    assert et["median_lag_days"] == 1.0  # decided 7/1, filled 7/2
    assert et["avg_pre_entry_fav_move"] == round(105 / 100 - 1, 4)  # +0.05
    assert et["chased_rate"] == 1.0  # 5% > 2% threshold


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
