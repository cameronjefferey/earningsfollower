"""Unit tests for the calibration feedback (learning loop phase 3).

Runnable without pytest (``python tests/test_calibration.py`` from the backend
dir) and also collectable by pytest. In-memory SQLite; no Alpaca/LLM needed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, TradeDecision  # noqa: E402
from app.services.paper.calibration import (  # noqa: E402
    adjust_win_prob,
    compute_calibration,
)


@dataclass
class FakeSettings:
    paper_calibration_enabled: bool = True
    paper_calibration_min_samples: int = 10
    paper_calibration_max_delta: float = 0.15


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db, strategy, n, win_prob, wins):
    for i in range(n):
        won = i < wins
        db.add(TradeDecision(
            decision_date=date(2026, 7, 1), strategy=strategy, ticker=f"{strategy}{i}",
            decision="opened", win_prob=win_prob, label_status="final",
            realized_pnl=100.0 if won else -100.0, outcome="win" if won else "loss",
        ))
    db.commit()


def test_disabled_returns_empty():
    db = _session()
    _seed(db, "earnings", 20, 0.6, 20)
    s = FakeSettings(paper_calibration_enabled=False)
    assert compute_calibration(db, s) == {}


def test_multiplier_and_sample_gating():
    db = _session()
    # Predicted 0.6, realized 1.0 over 14 trades -> multiplier ~1.67, applicable.
    _seed(db, "earnings", 14, 0.6, 14)
    # Only 4 samples -> computed but NOT applicable (below the floor).
    _seed(db, "reddit", 4, 0.5, 0)
    calib = compute_calibration(db, FakeSettings())
    assert round(calib["earnings"].multiplier, 2) == 1.67
    assert calib["earnings"].applicable is True
    assert calib["reddit"].applicable is False


def test_adjust_is_capped_by_max_delta_and_band():
    db = _session()
    _seed(db, "earnings", 14, 0.6, 14)   # optimistic realized -> mult up
    _seed(db, "reddit", 14, 0.55, 0)     # realized 0 -> mult floored
    calib = compute_calibration(db, FakeSettings())
    s = FakeSettings()
    # Upward: 0.6 * 1.67 = 1.0, but capped to +0.15 -> 0.75.
    assert adjust_win_prob(0.6, "earnings", calib, s) == 0.75
    # Downward: 0.55 * 0.2 = 0.11, but capped to -0.15 -> 0.40.
    assert adjust_win_prob(0.55, "reddit", calib, s) == 0.40


def test_adjust_is_noop_when_off_or_untrusted_or_none():
    db = _session()
    _seed(db, "reddit", 4, 0.5, 2)  # too few -> not applicable
    calib = compute_calibration(db, FakeSettings())
    s = FakeSettings()
    assert adjust_win_prob(0.5, "reddit", calib, s) == 0.5      # untrusted -> raw
    assert adjust_win_prob(0.5, "waves", calib, s) == 0.5       # no entry -> raw
    assert adjust_win_prob(None, "earnings", calib, s) is None  # no belief -> None
    assert adjust_win_prob(0.5, "earnings", {}, s) == 0.5       # empty map -> raw


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
