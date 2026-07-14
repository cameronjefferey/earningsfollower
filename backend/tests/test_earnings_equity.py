"""Unit tests for the strike-level win-prob recompute and the earnings-equity
share sizing / exit logic.

Runnable without pytest (``python tests/test_earnings_equity.py`` from the
backend dir) and also collectable by pytest. Uses lightweight fakes so no DB or
Alpaca connection is needed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.implied import compute_vol_edge  # noqa: E402
from app.services.paper.executor import (  # noqa: E402
    EQUITY_LONG,
    EQUITY_SHORT,
    _earnings_equity_exit_reason,
    _earnings_equity_shares,
)


@dataclass
class FakeSettings:
    paper_earnings_equity_take_profit_pct: float = 0.10
    paper_earnings_equity_stop_pct: float = 0.07
    paper_force_close_id_set: set = field(default_factory=set)


# --- strike-level win probability --------------------------------------------


def test_exceed_rate_at_strike_pulls_win_prob_down():
    """Selling at 0.65x the move is breached MORE often than the full move, so
    the strike-level win-prob (1 - exceed_at_strike) is lower than the full-move
    seller edge -- the honest EV input for the closer short."""
    # Implied move 10%; realized abs moves around it.
    moves = [0.03, 0.05, 0.06, 0.07, 0.08, 0.09, 0.11, 0.12, 0.15, 0.20]
    edge = compute_vol_edge(0.10, moves, sell_strike_frac=0.65)
    # Full move (>=0.10) reached 4/10 -> seller edge 0.60.
    assert edge["exceed_rate"] == 0.4
    # 0.65x move = 0.065; reached by everything >= 0.07 -> 7/10.
    assert edge["exceed_rate_at_strike"] == 0.7
    seller_edge = 1 - edge["exceed_rate"]
    seller_edge_at_strike = 1 - edge["exceed_rate_at_strike"]
    assert seller_edge_at_strike < seller_edge


def test_exceed_rate_at_strike_none_without_frac():
    edge = compute_vol_edge(0.10, [0.05] * 10)
    assert edge["exceed_rate_at_strike"] is None


def test_vol_edge_insufficient_sample_is_safe():
    edge = compute_vol_edge(0.10, [0.05, 0.06], sell_strike_frac=0.65)
    assert edge["exceed_rate"] is None
    assert edge["exceed_rate_at_strike"] is None


# --- equity share sizing (twin vs standalone) --------------------------------


def test_twin_sizing_matches_options_max_risk():
    """Twin: notional = the spread's max loss, so the shares risk the same $."""
    options_max_risk = 1_000.0
    spot = 90.0
    shares = _earnings_equity_shares(options_max_risk, spot)
    assert shares == 11  # int(1000 // 90)


def test_standalone_sizing_uses_conviction_budget():
    """Standalone: notional = equity x conviction risk fraction."""
    equity, risk_frac, spot = 100_000.0, 0.01, 250.0
    notional = equity * risk_frac  # 1000
    shares = _earnings_equity_shares(notional, spot)
    assert shares == 4  # int(1000 // 250)


def test_sizing_rejects_when_share_unaffordable_or_unpriced():
    assert _earnings_equity_shares(100.0, 250.0) == 0  # < 1 share
    assert _earnings_equity_shares(1000.0, 0.0) == 0   # no price
    assert _earnings_equity_shares(0.0, 50.0) == 0     # no budget


# --- equity exit logic -------------------------------------------------------


def _trade(structure: str, spot_entry: float, earnings_date=None, note=None, signal_id="EE-1"):
    return SimpleNamespace(
        signal_id=signal_id,
        structure=structure,
        spot_entry=spot_entry,
        earnings_date=earnings_date,
        note=note,
    )


def test_long_equity_take_profit_and_stop():
    s = FakeSettings()
    t = _trade(EQUITY_LONG, 100.0)
    assert _earnings_equity_exit_reason(t, 111.0, date.today(), s).startswith("take-profit")
    assert _earnings_equity_exit_reason(t, 92.0, date.today(), s).startswith("stop")
    assert _earnings_equity_exit_reason(t, 103.0, date.today(), s) is None


def test_short_equity_take_profit_and_stop():
    s = FakeSettings()
    t = _trade(EQUITY_SHORT, 100.0)
    # Short profits when the stock falls.
    assert _earnings_equity_exit_reason(t, 89.0, date.today(), s).startswith("take-profit")
    assert _earnings_equity_exit_reason(t, 108.0, date.today(), s).startswith("stop")


def test_post_earnings_harvest_after_print():
    s = FakeSettings()
    yesterday = date.today() - timedelta(days=1)
    t = _trade(EQUITY_LONG, 100.0, earnings_date=yesterday)
    # Small move (no TP/SL) but the print has passed -> harvest.
    assert _earnings_equity_exit_reason(t, 101.0, date.today(), s) == "post-earnings"


def test_force_close_and_bad_fill_take_priority():
    s = FakeSettings(paper_force_close_id_set={"EE-1"})
    t = _trade(EQUITY_LONG, 100.0, signal_id="EE-1")
    assert _earnings_equity_exit_reason(t, 100.0, date.today(), s) == "manual close"
    t2 = _trade(EQUITY_LONG, 100.0, note="bad fill: something", signal_id="EE-2")
    assert _earnings_equity_exit_reason(t2, 100.0, date.today(), s) == "flatten: bad entry fill"


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
