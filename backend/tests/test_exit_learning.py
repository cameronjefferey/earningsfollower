"""Unit tests for the learned take-profit (the exit half of the learning loop).

Runnable without pytest (``python tests/test_exit_learning.py`` from the backend
dir) and also collectable by pytest. Uses an in-memory SQLite DB with planted
paths so the take-profit search is checked against known answers.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, PaperTrade, PriceBar  # noqa: E402
from app.services.paper.executor import _underlying_take_profit  # noqa: E402
from app.services.paper.exit_learning import (  # noqa: E402
    compute_learned_take_profit,
    effective_take_profit,
)


@dataclass
class FakeSettings:
    paper_take_profit_enabled: bool = True
    paper_take_profit_pct: float = 0.03
    paper_exit_learning_enabled: bool = True
    paper_exit_learning_min_samples: int = 20
    paper_take_profit_min: float = 0.015
    paper_take_profit_max: float = 0.08


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


# --- the live guardrail helper ------------------------------------------------


def test_underlying_take_profit_fires_on_favorable_move_only():
    s = FakeSettings()
    bull = SimpleNamespace(spot_entry=100.0, entry_credit=100.0, direction="bullish")
    # +4% favorable clears a 3% take-profit.
    assert _underlying_take_profit(bull, 104.0, s, 0.03).startswith("take-profit")
    # +2% doesn't.
    assert _underlying_take_profit(bull, 102.0, s, 0.03) is None
    # A drop is never a take-profit for a long.
    assert _underlying_take_profit(bull, 96.0, s, 0.03) is None

    bear = SimpleNamespace(spot_entry=100.0, entry_credit=100.0, direction="bearish")
    # Short profits when price falls: -4% is favorable.
    assert _underlying_take_profit(bear, 96.0, s, 0.03).startswith("take-profit")
    assert _underlying_take_profit(bear, 104.0, s, 0.03) is None


def test_underlying_take_profit_off_or_neutral_is_noop():
    off = FakeSettings(paper_take_profit_enabled=False)
    bull = SimpleNamespace(spot_entry=100.0, entry_credit=100.0, direction="bullish")
    assert _underlying_take_profit(bull, 200.0, off, 0.03) is None
    # Neutral (iron-condor-style) trades have no directional take-profit.
    neutral = SimpleNamespace(spot_entry=100.0, entry_credit=100.0, direction="neutral")
    assert _underlying_take_profit(neutral, 104.0, FakeSettings(), 0.03) is None


# --- the learner --------------------------------------------------------------


def _plant_directional(db, n: int, peak_high: float, realized: float):
    """n closed bullish drift trades that all ran to ``peak_high`` from 100 but
    were exited at ``realized`` favorable move (a big give-back)."""
    opened_at = datetime(2026, 7, 1, 14, 30)
    for i in range(n):
        tkr = f"T{i}"
        db.add(PaperTrade(
            signal_id=f"S{i}", strategy="drift", ticker=tkr, direction="bullish",
            structure="Bull call spread", vol_stance="buy", conviction="high",
            status="closed", spot_entry=100.0, spot_at_exit=100.0 * (1 + realized),
            realized_move_pct=realized, realized_pnl=1.0, outcome="win",
            opened_at=opened_at, closed_at=opened_at + timedelta(days=3),
        ))
        highs = [103.0, peak_high, 104.0, 100.0 * (1 + realized)]
        lows = [99.0, 100.0, 101.0, 100.0]
        for d, (hi, lo) in enumerate(zip(highs, lows)):
            db.add(PriceBar(ticker=tkr, date=date(2026, 7, 1) + timedelta(days=d),
                            open=100.0, high=hi, low=lo, close=hi - 1))
    db.commit()


def test_learner_picks_banded_tp_with_positive_lift():
    """Every trade peaked at +8% but we kept only +1%. The best in-band take-profit
    (0.05, the grid max under the 0.08 ceiling) captures far more than actual."""
    db = _session()
    _plant_directional(db, n=20, peak_high=108.0, realized=0.01)
    learned = compute_learned_take_profit(db, FakeSettings())
    assert learned is not None
    assert learned.n == 20
    assert learned.take_profit_pct == 0.05
    assert learned.actual_avg_captured == 0.01
    assert learned.avg_captured == 0.05
    assert round(learned.lift, 2) == 0.04
    assert learned.applicable is True
    assert effective_take_profit(FakeSettings(), learned) == 0.05


def test_learner_waits_for_min_samples():
    db = _session()
    _plant_directional(db, n=5, peak_high=108.0, realized=0.01)
    assert compute_learned_take_profit(db, FakeSettings()) is None
    # With no learned policy, the live trader falls back to the static default.
    assert effective_take_profit(FakeSettings(), None) == 0.03


def test_learner_off_is_noop():
    db = _session()
    _plant_directional(db, n=20, peak_high=108.0, realized=0.01)
    off = FakeSettings(paper_exit_learning_enabled=False)
    assert compute_learned_take_profit(db, off) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all exit-learning tests passed")
