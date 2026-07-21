"""Unit tests for option expiry settlement pricing.

Runnable without pytest (``python tests/test_expiry_settlement.py`` from the
backend dir) and also collectable by pytest. Exercises the pure helpers that
mark expired paper trades closed when Alpaca quotes disappear.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper.executor import (  # noqa: E402
    _expiry_exit_value,
    _spread_intrinsic,
)


def _put(side: str, strike: float) -> dict:
    return {"symbol": f"P{strike}", "type": "put", "side": side, "strike": strike}


def _call(side: str, strike: float) -> dict:
    return {"symbol": f"C{strike}", "type": "call", "side": side, "strike": strike}


# --- intrinsic ---------------------------------------------------------------


def test_bull_put_otm_intrinsic_zero():
    # Short 100 / long 95 put credit spread, spot above short strike.
    legs = [_put("sell", 100), _put("buy", 95)]
    assert _spread_intrinsic(legs, 105.0) == 0.0


def test_bull_put_max_loss_intrinsic():
    # Fully ITM: package worth -width to the holder of the credit spread.
    legs = [_put("sell", 100), _put("buy", 95)]
    assert _spread_intrinsic(legs, 90.0) == -5.0


def test_bull_call_debit_max_value():
    # Long 95 / short 100 call debit spread, both ITM → worth the width.
    legs = [_call("buy", 95), _call("sell", 100)]
    assert _spread_intrinsic(legs, 110.0) == 5.0


def test_bull_call_debit_otm_worthless():
    legs = [_call("buy", 95), _call("sell", 100)]
    assert _spread_intrinsic(legs, 90.0) == 0.0


# --- expiry exit mark --------------------------------------------------------


def test_credit_expiry_otm_keeps_premium():
    # Cost to close at expiry = 0 → full credit kept.
    legs = [_put("sell", 100), _put("buy", 95)]
    assert _expiry_exit_value("earnings", legs, 105.0) == 0.0


def test_credit_expiry_max_loss():
    # Cost to close = width when fully ITM.
    legs = [_put("sell", 100), _put("buy", 95)]
    assert _expiry_exit_value("earnings", legs, 90.0) == 5.0


def test_credit_expiry_partial_itm():
    legs = [_put("sell", 100), _put("buy", 95)]
    assert _expiry_exit_value("earnings", legs, 97.0) == 3.0


def test_debit_expiry_otm_wipeout():
    # Proceeds at expiry = 0 when OTM.
    legs = [_call("buy", 95), _call("sell", 100)]
    assert _expiry_exit_value("drift", legs, 90.0) == 0.0


def test_debit_expiry_max_value():
    legs = [_call("buy", 95), _call("sell", 100)]
    assert _expiry_exit_value("waves", legs, 110.0) == 5.0


def test_expiry_missing_spot_treats_as_worthless():
    legs = [_put("sell", 100), _put("buy", 95)]
    assert _expiry_exit_value("earnings", legs, None) == 0.0
    assert _expiry_exit_value("reddit", legs, None) == 0.0


def test_iron_condor_otm_expires_cheap():
    # Short 110 call / long 115 call + short 90 put / long 85 put, spot mid.
    legs = [
        _call("sell", 110),
        _call("buy", 115),
        _put("sell", 90),
        _put("buy", 85),
    ]
    assert _expiry_exit_value("earnings", legs, 100.0) == 0.0


if __name__ == "__main__":
    for name, fn in sorted(
        (n, v) for n, v in globals().items() if n.startswith("test_") and callable(v)
    ):
        fn()
        print(f"ok  {name}")
    print("all passed")
