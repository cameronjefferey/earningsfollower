"""Unit tests for the strike-level win-prob recompute and the earnings-equity
share sizing / exit logic.

Runnable without pytest (``python tests/test_earnings_equity.py`` from the
backend dir) and also collectable by pytest. Uses lightweight fakes so no DB or
Alpaca connection is needed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, PaperTrade  # noqa: E402
from app.services.implied import compute_vol_edge  # noqa: E402
from app.services.paper.executor import (  # noqa: E402
    EQUITY_LONG,
    EQUITY_SHORT,
    NEAR_MISS_PREFIX,
    _close_client_order_id,
    _earnings_equity_exit_reason,
    _earnings_equity_shares,
    _exit_is_urgent,
    _near_miss,
    _walk_mleg_to_fill,
    earnings_equity_trailing_halt,
)


@dataclass
class FakeSettings:
    paper_earnings_equity_take_profit_pct: float = 0.10
    paper_earnings_equity_stop_pct: float = 0.07
    # Global learned take-profit off here so these cases test the book's own band.
    paper_take_profit_enabled: bool = False
    paper_force_close_id_set: set = field(default_factory=set)
    paper_walk_limit_enabled: bool = True
    paper_walk_step: float = 0.01
    paper_walk_interval_seconds: float = 0.0  # no real sleeping in tests
    paper_walk_max_seconds: float = 5.0
    paper_earnings_equity_halt_enabled: bool = True
    paper_earnings_equity_halt_window: int = 12


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


def _trade(structure: str, spot_entry: float, earnings_date=None, note=None,
           signal_id="EE-1", entry_credit=None):
    return SimpleNamespace(
        signal_id=signal_id,
        structure=structure,
        spot_entry=spot_entry,
        # Exits anchor to the real fill; default it to spot_entry for the simple
        # cases where the pre-fill estimate and the fill agree.
        entry_credit=spot_entry if entry_credit is None else entry_credit,
        earnings_date=earnings_date,
        note=note,
    )


def test_long_equity_take_profit_and_stop():
    s = FakeSettings()
    t = _trade(EQUITY_LONG, 100.0)
    assert _earnings_equity_exit_reason(t, 111.0, date.today(), s, 0.03).startswith("take-profit")
    assert _earnings_equity_exit_reason(t, 92.0, date.today(), s, 0.03).startswith("stop")
    assert _earnings_equity_exit_reason(t, 103.0, date.today(), s, 0.03) is None


def test_global_learned_clip_does_not_bank_earnings_stock():
    """Live settings have the 3% clip on. Earnings stock must still wait for 10%."""
    s = FakeSettings(paper_take_profit_enabled=True)
    t = _trade(EQUITY_LONG, 100.0)
    t.direction = "bullish"
    assert _earnings_equity_exit_reason(t, 103.0, date.today(), s, 0.03) is None
    assert _earnings_equity_exit_reason(t, 111.0, date.today(), s, 0.03).startswith("take-profit")


def test_short_equity_take_profit_and_stop():
    s = FakeSettings()
    t = _trade(EQUITY_SHORT, 100.0)
    # Short profits when the stock falls.
    assert _earnings_equity_exit_reason(t, 89.0, date.today(), s, 0.03).startswith("take-profit")
    assert _earnings_equity_exit_reason(t, 108.0, date.today(), s, 0.03).startswith("stop")


def test_exit_move_anchors_to_fill_not_stale_spot_entry():
    """Regression: a stale pre-fill spot_entry must not trigger a phantom stop.

    ERIC filled at 10.15 but spot_entry was recorded as 11.72; measured off the
    stale estimate the position read -13.9% and stopped out while it was actually
    flat vs its real fill. The exit must use entry_credit (the fill)."""
    s = FakeSettings()
    t = _trade(EQUITY_LONG, spot_entry=11.72, entry_credit=10.15)
    # ~flat vs the real fill -> no exit, despite -13.9% vs the stale spot_entry.
    assert _earnings_equity_exit_reason(t, 10.09, date.today(), s, 0.03) is None
    # A genuine 8% drop from the fill still stops out.
    assert _earnings_equity_exit_reason(t, 9.30, date.today(), s, 0.03).startswith("stop")


def test_post_earnings_harvest_after_print():
    s = FakeSettings()
    yesterday = date.today() - timedelta(days=1)
    t = _trade(EQUITY_LONG, 100.0, earnings_date=yesterday)
    # Small move (no TP/SL) but the print has passed -> harvest.
    assert _earnings_equity_exit_reason(t, 101.0, date.today(), s, 0.03) == "post-earnings"


def test_force_close_and_bad_fill_take_priority():
    s = FakeSettings(paper_force_close_id_set={"EE-1"})
    t = _trade(EQUITY_LONG, 100.0, signal_id="EE-1")
    assert _earnings_equity_exit_reason(t, 100.0, date.today(), s, 0.03) == "manual close"
    t2 = _trade(EQUITY_LONG, 100.0, note="bad fill: something", signal_id="EE-2")
    assert _earnings_equity_exit_reason(t2, 100.0, date.today(), s, 0.03) == "flatten: bad entry fill"


def test_earnings_equity_halt_needs_a_full_losing_window():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    s = FakeSettings(paper_earnings_equity_halt_window=12)
    assert earnings_equity_trailing_halt(db, s) is None
    for i in range(11):
        db.add(PaperTrade(
            signal_id=f"EE-H{i}", strategy="earnings", ticker=f"L{i}",
            structure=EQUITY_LONG, direction="bullish", vol_stance="neutral",
            conviction="medium", status="closed", realized_pnl=-50.0,
            outcome="loss", closed_at=datetime(2026, 8, 1) + timedelta(days=i),
        ))
    db.commit()
    assert earnings_equity_trailing_halt(db, s) is None
    db.add(PaperTrade(
        signal_id="EE-H11", strategy="earnings", ticker="L11",
        structure=EQUITY_LONG, direction="bullish", vol_stance="neutral",
        conviction="medium", status="closed", realized_pnl=-50.0,
        outcome="loss", closed_at=datetime(2026, 8, 20),
    ))
    db.commit()
    assert earnings_equity_trailing_halt(db, s) == "earnings-equity halt (0-for-12 closed)"
    db.add(PaperTrade(
        signal_id="EE-W", strategy="earnings", ticker="WIN",
        structure=EQUITY_LONG, direction="bullish", vol_stance="neutral",
        conviction="medium", status="closed", realized_pnl=40.0,
        outcome="win", closed_at=datetime(2026, 8, 21),
    ))
    db.commit()
    assert earnings_equity_trailing_halt(db, s) is None
    off = FakeSettings(paper_earnings_equity_halt_enabled=False)
    assert earnings_equity_trailing_halt(db, off) is None


def test_near_miss_prefix_tags_gate_rejects():
    tagged = _near_miss("credit too thin (0.12)")
    assert tagged.startswith(NEAR_MISS_PREFIX)
    assert tagged.endswith("credit too thin (0.12)")
    assert _near_miss(tagged) == tagged
    assert _near_miss(None).startswith(NEAR_MISS_PREFIX)


def test_close_client_order_id_is_unique_per_attempt():
    """Regression: a re-armed close must not reuse a fixed id, or Alpaca 422s
    ('client_order_id must be unique') and the position never closes."""
    a = _close_client_order_id("EE-20260714-003")
    b = _close_client_order_id("EE-20260714-003")
    assert a != b
    assert a.startswith("EE-20260714-003-x-")
    assert b.startswith("EE-20260714-003-x-")


def test_exit_urgency_classifier():
    """Manual flatten and any stop cross the market; planned exits stay patient."""
    for urgent in (
        "manual close",
        "flatten: bad entry fill",
        "stop-loss (30% of risk)",
        "late stop (25% of risk, 1DTE)",
        "stop (gave back the move)",
        "stop (-7.2%)",
    ):
        assert _exit_is_urgent(urgent), urgent
    for patient in (
        "post-earnings",
        "hold window elapsed",
        "pre-earnings exit",
        "take-profit (+8.0% underlying)",
        "drift window elapsed",
        None,
    ):
        assert not _exit_is_urgent(patient), patient


class _FakeClient:
    """Fills the Nth submitted order; records prices submitted and cancels."""

    def __init__(self, fill_after: int):
        self.fill_after = fill_after
        self.submits: list[float] = []
        self.cancels: list[str] = []
        self._n = 0
        self._orders: dict[str, dict] = {}

    def submit_mleg(self, legs, qty, limit_price, client_order_id):
        self._n += 1
        oid = f"o{self._n}"
        self.submits.append(limit_price)
        filled = self._n >= self.fill_after
        self._orders[oid] = {
            "id": oid,
            "status": "filled" if filled else "new",
            "filled_avg_price": limit_price if filled else None,
        }
        return {"id": oid, "status": "accepted"}

    def get_order(self, oid):
        return self._orders.get(oid, {})

    def cancel_order(self, oid):
        self.cancels.append(oid)


def test_walk_debit_steps_up_until_filled():
    """A debit close walks the net UP a penny at a time toward the ask; stops
    the instant it fills, conceding no more than needed."""
    s = FakeSettings()
    c = _FakeClient(fill_after=3)
    order = _walk_mleg_to_fill(c, [], 1, "EF-1", start=1.00, end=1.10, settings=s)
    assert order["status"] == "filled"
    assert c.submits == [1.00, 1.01, 1.02]  # stopped as soon as it filled
    assert len(c.cancels) == 2               # cancelled the two that didn't fill


def test_walk_credit_steps_toward_bid():
    """A credit close (negative net) walks toward the less-negative bid side."""
    s = FakeSettings()
    c = _FakeClient(fill_after=2)
    order = _walk_mleg_to_fill(c, [], 1, "RS-1", start=-1.00, end=-0.90, settings=s)
    assert order["status"] == "filled"
    assert c.submits == [-1.00, -0.99]


def test_walk_drops_final_marketable_when_unfilled():
    """If nothing fills, it walks to the marketable end and leaves that order for
    reconcile (never gives up more than the cross)."""
    s = FakeSettings()
    c = _FakeClient(fill_after=999)
    order = _walk_mleg_to_fill(c, [], 1, "EF-2", start=1.00, end=1.02, settings=s)
    assert "id" in order
    assert c.submits[-1] == 1.02           # final order sits at the cross
    assert c.submits[0] == 1.00            # but started patient at mid


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
