"""Unit tests for the week-to-week learning tracker (learning loop phase 4).

Runnable without pytest (``python tests/test_progress.py``) and via pytest.
In-memory SQLite; seeds PaperTrades with real close dates + linked decisions so
the as-of reconstruction has a genuine timeline to walk.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, PaperTrade, TradeDecision  # noqa: E402
from app.research.attribution import attribution_report  # noqa: E402
from app.research.progress import progress_series  # noqa: E402


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db, weeks_ago: int, n: int, wins: int, win_prob: float, tag: str):
    now = datetime.utcnow()
    close_dt = now - timedelta(weeks=weeks_ago, days=1)
    dd = (close_dt - timedelta(days=3)).date()
    for i in range(n):
        won = i < wins
        sid = f"{tag}{i}"
        pnl = 100.0 if won else -100.0
        db.add(PaperTrade(
            signal_id=sid, strategy="earnings", ticker=sid,
            structure="Bear call (call credit) spread", direction="bullish",
            vol_stance="sell", conviction="high", status="closed", contracts=1,
            realized_pnl=pnl, outcome="win" if won else "loss", closed_at=close_dt,
        ))
        db.add(TradeDecision(
            decision_date=dd, strategy="earnings", ticker=sid, decision="opened",
            signal_id=sid, conviction="high", direction="bullish", win_prob=win_prob,
            realized_pnl=pnl, outcome="win" if won else "loss", label_status="final",
        ))
    db.commit()


# --- as-of attribution -------------------------------------------------------


def test_as_of_only_counts_trades_closed_by_then():
    db = _session()
    _seed(db, weeks_ago=3, n=6, wins=3, win_prob=0.6, tag="A")
    _seed(db, weeks_ago=1, n=8, wins=6, win_prob=0.6, tag="B")

    now = datetime.utcnow()
    # As of 2 weeks ago, only the first batch had closed.
    early = attribution_report(db, min_samples=1, as_of=now - timedelta(weeks=2))
    assert early["graded_trades"] == 6
    assert early["overall"]["win_rate"] == 0.5
    # As of now, both batches count.
    full = attribution_report(db, min_samples=1)
    assert full["graded_trades"] == 14


# --- weekly series -----------------------------------------------------------


def test_progress_series_tracks_cumulative_and_new_week():
    db = _session()
    _seed(db, weeks_ago=3, n=6, wins=3, win_prob=0.6, tag="A")
    _seed(db, weeks_ago=1, n=8, wins=6, win_prob=0.6, tag="B")

    ser = progress_series(db, weeks=5)
    weeks = ser["weeks"]
    assert len(weeks) == 5
    # The most recent week with closes shows the batch B stats and improvement.
    graded_last = weeks[-1]["cumulative"]["graded_trades"]
    assert graded_last == 14
    # Cumulative win rate ends up between the two batches (3/6 then 6/8 -> 9/14).
    assert weeks[-1]["cumulative"]["win_rate"] == round(9 / 14, 3)
    # Calibration gap tightened over the window (0.10 -> ~0.04).
    gaps = [w["cumulative"]["calibration_gap"] for w in weeks if w["cumulative"]["calibration_gap"] is not None]
    assert gaps[-1] < gaps[0]


def test_progress_flags_improvement_week_and_verdict():
    db = _session()
    _seed(db, weeks_ago=3, n=6, wins=3, win_prob=0.6, tag="A")
    _seed(db, weeks_ago=1, n=8, wins=6, win_prob=0.6, tag="B")

    ser = progress_series(db, weeks=5)
    improved = [w for w in ser["weeks"] if w["status"] == "improved"]
    # The batch-B week improved (higher win rate, tighter calibration, +P&L).
    assert improved, "expected at least one improved week"
    best = improved[-1]
    assert best["new_this_week"]["closed"] == 8
    assert best["new_this_week"]["win_rate"] == 0.75
    assert any("Calibration gap" in c for c in best["changes"])
    assert ser["verdict"]["learning"] is True


def test_break_even_week_is_not_a_regression():
    db = _session()
    # A single break-even week (3 win / 3 loss = $0 avg) is flat, not a regression.
    _seed(db, weeks_ago=1, n=6, wins=3, win_prob=0.5, tag="E")
    ser = progress_series(db, weeks=3)
    graded_weeks = [w for w in ser["weeks"] if w["cumulative"]["graded_trades"] > 0]
    assert graded_weeks[0]["status"] != "regressed"


def test_verdict_needs_two_weeks_of_data():
    db = _session()
    # All closes land in the CURRENT week, so only one week-end has graded data.
    now = datetime.utcnow()
    dd = now.date()
    for i in range(5):
        sid = f"S{i}"
        db.add(PaperTrade(
            signal_id=sid, strategy="earnings", ticker=sid,
            structure="Bear call (call credit) spread", direction="bullish",
            vol_stance="sell", conviction="high", status="closed", contracts=1,
            realized_pnl=100.0, outcome="win", closed_at=now,
        ))
        db.add(TradeDecision(
            decision_date=dd, strategy="earnings", ticker=sid, decision="opened",
            signal_id=sid, conviction="high", direction="bullish", win_prob=0.6,
            realized_pnl=100.0, outcome="win", label_status="final",
        ))
    db.commit()
    ser = progress_series(db, weeks=4)
    assert ser["verdict"]["learning"] is None
    assert "Not enough history" in ser["verdict"]["summary"]


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
