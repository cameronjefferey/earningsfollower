"""Unit tests for the Learning-page account-value / counterfactual path.

Runnable without pytest (``python tests/test_equity_path.py``) and via pytest.
In-memory SQLite; Alpaca is never contacted — tests pass an explicit series.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, PaperTrade  # noqa: E402
from app.services.paper.equity_path import (  # noqa: E402
    STARTING_EQUITY,
    allowed_books,
    book_of,
    equity_path_report,
)


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _settings(**overrides):
    base = dict(
        paper_earnings_equity_enabled=True,
        paper_drift_enabled=False,
        paper_waves_enabled=False,
        paper_reddit_enabled=False,
        paper_reversal_enabled=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _trade(
    db,
    *,
    sid: str,
    strategy: str,
    structure: str,
    pnl: float,
    closed: datetime,
    ticker: str = "X",
):
    db.add(
        PaperTrade(
            signal_id=sid,
            strategy=strategy,
            ticker=ticker,
            structure=structure,
            direction="bullish",
            vol_stance="sell",
            conviction="high",
            status="closed",
            contracts=1,
            realized_pnl=pnl,
            outcome="win" if pnl > 0 else "loss",
            closed_at=closed,
        )
    )


def _seed_mixed(db):
    # Allowed books.
    _trade(
        db,
        sid="E1",
        strategy="earnings",
        structure="Bear call (call credit) spread",
        pnl=500,
        closed=datetime(2026, 7, 20, 20, 0),
        ticker="AAA",
    )
    _trade(
        db,
        sid="EQ1",
        strategy="earnings",
        structure="Long shares",
        pnl=300,
        closed=datetime(2026, 8, 3, 20, 0),
        ticker="BBB",
    )
    _trade(
        db,
        sid="E2",
        strategy="earnings",
        structure="Bull put (put credit) spread",
        pnl=-200,
        closed=datetime(2026, 8, 10, 20, 0),
        ticker="CCC",
    )
    # Retired books.
    _trade(
        db,
        sid="R1",
        strategy="reddit",
        structure="Debit call spread",
        pnl=-400,
        closed=datetime(2026, 7, 25, 20, 0),
        ticker="RDDT",
    )
    _trade(
        db,
        sid="D1",
        strategy="drift",
        structure="Debit call spread",
        pnl=-1000,
        closed=datetime(2026, 8, 15, 20, 0),
        ticker="DRFT",
    )
    _trade(
        db,
        sid="W1",
        strategy="waves",
        structure="Debit put spread",
        pnl=-800,
        closed=datetime(2026, 8, 18, 20, 0),
        ticker="WAVE",
    )
    db.commit()


def test_book_of_splits_earnings_stock_from_options():
    db = _session()
    _seed_mixed(db)
    rows = {t.signal_id: t for t in db.scalars(select(PaperTrade)).all()}
    assert book_of(rows["E1"]) == "earnings"
    assert book_of(rows["EQ1"]) == "earnings_equity"
    assert book_of(rows["R1"]) == "reddit"
    assert book_of(rows["D1"]) == "drift"


def test_allowed_books_follow_live_flags():
    assert allowed_books(_settings()) == frozenset(
        {"earnings", "earnings_equity", "reversal"}
    )
    on = allowed_books(_settings(paper_drift_enabled=True, paper_waves_enabled=True))
    assert "drift" in on and "waves" in on
    reddit = allowed_books(_settings(paper_reddit_enabled=True))
    assert "reddit" in reddit and "reddit_equity" in reddit
    off = allowed_books(_settings(paper_reversal_enabled=False))
    assert "reversal" not in off


def test_counterfactual_drops_retired_books():
    db = _session()
    _seed_mixed(db)
    report = equity_path_report(db, _settings(), alpaca_points=[])
    assert report["actual_source"] == "journal"
    assert report["allowed"]["n"] == 3
    assert report["allowed"]["total_pnl"] == 600.0  # 500 + 300 - 200
    assert report["retired"]["n"] == 3
    assert report["retired"]["total_pnl"] == -2200.0  # -400 -1000 -800
    assert report["latest_allowed"] == STARTING_EQUITY + 600
    # Journal actual includes every closed book.
    assert report["latest_actual"] == STARTING_EQUITY + 600 - 2200
    by_date = {p["date"]: p for p in report["points"]}
    # After the Aug 3 stock win, allowed is $100,800 and stays there through
    # the reddit/drift/waves dumps (those only hit `actual`).
    assert by_date["2026-08-03"]["allowed"] == 100_800.0
    assert by_date["2026-08-18"]["allowed"] == 100_600.0
    assert by_date["2026-08-18"]["actual"] == 98_400.0


def test_events_snap_to_a_session_on_the_curve():
    db = _session()
    _seed_mixed(db)
    report = equity_path_report(db, _settings(), alpaca_points=[])
    events = {e["title"]: e for e in report["events"]}
    # Aug 5 was a Wednesday — already a weekday on the journal curve.
    assert events["Reddit retired"]["chart_date"] == "2026-08-05"
    # Aug 25 is a weekday and on the journal curve (extended through today).
    assert events["Drift and waves retired"]["chart_date"] == "2026-08-25"


def test_alpaca_series_is_the_actual_line():
    db = _session()
    _seed_mixed(db)
    alpaca = [
        {"date": "2026-07-20", "actual": 100_500.0},
        {"date": "2026-08-03", "actual": 90_000.0},
        {"date": "2026-08-18", "actual": 74_000.0},
    ]
    report = equity_path_report(db, _settings(), alpaca_points=alpaca)
    assert report["actual_source"] == "alpaca"
    by_date = {p["date"]: p for p in report["points"]}
    assert by_date["2026-08-18"]["actual"] == 74_000.0
    # Counterfactual still ignores retired books and starts at $100k.
    assert by_date["2026-08-18"]["allowed"] == 100_600.0


def test_alpaca_without_journal_still_charts_actual():
    db = _session()
    alpaca = [
        {"date": "2026-07-20", "actual": 100_000.0},
        {"date": "2026-08-18", "actual": 74_000.0},
    ]
    report = equity_path_report(db, _settings(), alpaca_points=alpaca)
    assert report["actual_source"] == "alpaca"
    assert report["latest_actual"] == 74_000.0
    assert report["latest_allowed"] == STARTING_EQUITY
    assert report["all"]["n"] == 0


def test_empty_journal_is_safe():
    db = _session()
    report = equity_path_report(db, _settings(), alpaca_points=[])
    assert report["points"] == []
    assert report["allowed"]["n"] == 0
    assert report["latest_actual"] is None


def _run_all() -> int:
    tests = [
        test_book_of_splits_earnings_stock_from_options,
        test_allowed_books_follow_live_flags,
        test_counterfactual_drops_retired_books,
        test_events_snap_to_a_session_on_the_curve,
        test_alpaca_series_is_the_actual_line,
        test_alpaca_without_journal_still_charts_actual,
        test_empty_journal_is_safe,
    ]
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
