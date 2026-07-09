"""Unit tests for the fair-trade economics gate.

Runnable without pytest (``python tests/test_economics.py`` from the backend
dir) and also collectable by pytest. The module under test is dependency-free,
so these tests just need a lightweight fake ``settings`` carrying the gate knobs.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper.economics import (  # noqa: E402
    evaluate_entry,
    expected_value,
    fill_within_plan,
    leg_liquidity_ok,
    reward_risk,
    spread_pnl,
)


@dataclass
class FakeSettings:
    """Mirrors the production defaults in app/config.py."""

    paper_min_credit_width_ratio: float = 0.20
    paper_max_debit_width_frac: float = 0.60
    paper_min_reward_risk: float = 0.25
    paper_min_expected_value: float = 0.0
    paper_max_leg_spread_frac: float = 0.15


def _tight_quotes(*prices: float) -> dict:
    """Two-sided quotes with a 2%-of-mid spread, so liquidity always passes."""
    out = {}
    for i, mid in enumerate(prices):
        sym = chr(ord("A") + i)
        out[sym] = {"bid": round(mid * 0.99, 2), "ask": round(mid * 1.01, 2), "mid": mid}
    return out


def _legs(n: int, sides: list[str]) -> list[dict]:
    return [{"symbol": chr(ord("A") + i), "side": sides[i]} for i in range(n)]


# --- primitives --------------------------------------------------------------


def test_spread_pnl_credit():
    # Sell a $5-wide for $1.50: keep 1.50 max, lose 3.50 max.
    assert spread_pnl(True, 5.0, 1.50) == (1.50, 3.50)


def test_spread_pnl_debit():
    # Pay $2.00 for a $5-wide: risk the 2.00, upside is 3.00.
    assert spread_pnl(False, 5.0, 2.00) == (3.00, 2.00)


def test_spread_pnl_clamps_negative():
    # Paying more than the width can't create negative profit.
    assert spread_pnl(False, 5.0, 6.0) == (0.0, 6.0)


def test_reward_risk():
    assert reward_risk(3.0, 2.0) == 1.5
    assert reward_risk(1.0, 0.0) is None


def test_expected_value():
    # 60% win rate on a 3:2 payoff = 0.6*3 - 0.4*2 = 1.0.
    assert round(expected_value(0.6, 3.0, 2.0), 6) == 1.0
    # Clamps out-of-range probabilities.
    assert expected_value(1.5, 3.0, 2.0) == 3.0


def test_leg_liquidity_rejects_wide_and_one_sided():
    legs = _legs(2, ["buy", "sell"])
    ok, _ = leg_liquidity_ok(legs, _tight_quotes(2.0, 1.0), 0.15)
    assert ok
    wide = {"A": {"bid": 1.0, "ask": 2.0, "mid": 1.5}, "B": {"bid": 0.9, "ask": 1.0, "mid": 0.95}}
    ok, why = leg_liquidity_ok(legs, wide, 0.15)
    assert not ok and "wide" in why
    one_sided = {"A": {"bid": 0.0, "ask": 2.0, "mid": 1.0}, "B": {"bid": 0.9, "ask": 1.0, "mid": 0.95}}
    ok, why = leg_liquidity_ok(legs, one_sided, 0.15)
    assert not ok and "two-sided" in why


# --- historical cases (the whole point) --------------------------------------


def test_rejects_the_mu_debit_disaster():
    """RS-20260706-006: paid 21.55 for a 25-wide spread (86% of width). Max
    profit 3.45 vs max loss 21.55 -- must be rejected as debit-too-rich."""
    s = FakeSettings()
    ok, reason, m = evaluate_entry(
        is_credit=False, width=25.0, price=21.55, win_prob=0.55,
        legs=_legs(2, ["buy", "sell"]), quotes=_tight_quotes(21.55, 1.0),
        settings=s,
    )
    assert not ok
    assert "debit too rich" in reason
    assert m.max_profit == 3.45 and m.max_loss == 21.55


def test_keeps_the_winning_atvi_credit():
    """EF-20260623-001: collected 41.6 on an 85-wide credit structure (the one
    trade that made money). Must pass every gate."""
    s = FakeSettings()
    ok, reason, m = evaluate_entry(
        is_credit=True, width=85.0, price=41.6, win_prob=0.80,
        legs=_legs(2, ["sell", "buy"]), quotes=_tight_quotes(50.0, 8.4),
        settings=s,
    )
    assert ok, reason
    assert m.reward_risk is not None and m.reward_risk >= s.paper_min_reward_risk
    assert m.expected_value is not None and m.expected_value > 0


def test_rejects_negative_ev_reddit_at_the_cap():
    """A debit spread priced right at the 60% cap with only a 55% win prob is
    negative-EV (0.55*0.4 - 0.45*0.6 < 0) and must be rejected on EV."""
    s = FakeSettings()
    ok, reason, m = evaluate_entry(
        is_credit=False, width=10.0, price=6.0, win_prob=0.55,
        legs=_legs(2, ["buy", "sell"]), quotes=_tight_quotes(6.0, 1.0),
        settings=s,
    )
    assert not ok
    assert "expected value" in reason
    assert m.expected_value is not None and m.expected_value < 0


def test_allows_a_cheap_high_conviction_debit():
    """Same name but the debit is only 45% of width: now +EV and it passes."""
    s = FakeSettings()
    ok, reason, _ = evaluate_entry(
        is_credit=False, width=10.0, price=4.5, win_prob=0.55,
        legs=_legs(2, ["buy", "sell"]), quotes=_tight_quotes(4.5, 1.0),
        settings=s,
    )
    assert ok, reason


def test_illiquid_rejected_before_price():
    s = FakeSettings()
    wide = {"A": {"bid": 1.0, "ask": 3.0, "mid": 2.0}, "B": {"bid": 0.9, "ask": 1.0, "mid": 0.95}}
    ok, reason, _ = evaluate_entry(
        is_credit=False, width=10.0, price=4.0, win_prob=0.6,
        legs=_legs(2, ["buy", "sell"]), quotes=wide, settings=s,
    )
    assert not ok and reason.startswith("illiquid")


def test_missing_win_prob_still_gates_on_price():
    """No win-prob (e.g. missing history) skips only the EV check; the price and
    reward:risk gates still reject a rich debit."""
    s = FakeSettings()
    ok, reason, _ = evaluate_entry(
        is_credit=False, width=25.0, price=21.55, win_prob=None,
        legs=_legs(2, ["buy", "sell"]), quotes=_tight_quotes(21.55, 1.0),
        settings=s,
    )
    assert not ok and "debit too rich" in reason


# --- post-fill enforcement ---------------------------------------------------


def test_fill_within_plan_flags_bad_debit_fill():
    s = FakeSettings()
    ok, reason = fill_within_plan(False, 25.0, 21.55, s)
    assert not ok and "debit too rich" in reason


def test_fill_within_plan_flags_thin_credit_fill():
    """EF-20260706-001: filled a 1-wide credit spread for 0.01 -- below the 0.20
    floor, so the post-fill check flags it to be flattened."""
    s = FakeSettings()
    ok, reason = fill_within_plan(True, 1.0, 0.01, s)
    assert not ok and "credit too thin" in reason


def test_fill_within_plan_passes_a_good_fill():
    s = FakeSettings()
    ok, reason = fill_within_plan(False, 10.0, 4.5, s)
    assert ok, reason


def test_fill_within_plan_skips_equity():
    s = FakeSettings()
    ok, _ = fill_within_plan(False, None, 100.0, s)
    assert ok


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
