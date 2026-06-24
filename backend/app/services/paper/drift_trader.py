"""Build a directional debit spread from a live post-earnings drift (PEAD) setup.

The drift screen (`app.services.drift`) surfaces names that just reported, beat
(or missed) and reacted strongly, with their own history showing the move tends
to keep drifting the same way for ~5 trading days. Here we turn that lean into a
defined-risk options trade:

  - long  drift  -> bull call spread  (buy near-the-money call, sell an OTM call)
  - short drift  -> bear put  spread  (buy near-the-money put,  sell an OTM put)

A debit spread (vs. a single long option) caps cost, cuts theta drag, and the
short leg is placed near the expected drift target so we pay for exactly the move
the history predicts. We hold a short-dated expiry (the print is already past, so
there's no IV-crush risk to dodge) and exit on time, a take-profit, or a stop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.clients.alpaca import AlpacaClient
from app.services.paper.contracts import SpecLeg

logger = logging.getLogger(__name__)

# Floor on the spread width as a % of spot, so a tiny historical edge still
# produces a tradeable (not razor-thin) spread.
MIN_TARGET_MOVE = 0.04


@dataclass
class DriftSpec:
    legs: list[SpecLeg]      # [long leg, short leg]
    net_debit: float         # per share, what we pay to open (max loss)
    width: float             # strike distance, per share (max value)
    expiration: date
    spot: float
    stop_level: float | None  # underlying close beyond this breaks the thesis


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def build_drift_spec(
    client: AlpacaClient, setup: dict
) -> tuple[DriftSpec | None, str]:
    """Return (spec, reason). Picks a near-the-money long leg and an OTM short
    leg sized to the historical drift target, priced from live quotes."""
    ticker = setup["ticker"]
    long = setup.get("direction") == "long"
    otype = "call" if long else "put"

    live = setup.get("live") or {}
    spot = client.stock_price(ticker) or live.get("last_close")
    if not spot:
        return None, "no live underlying price"

    history = setup.get("history") or {}
    edge = abs(history.get("avg_drift_5d_pct") or 0.0)
    target_move = max(edge, MIN_TARGET_MOVE)

    today = date.today()
    contracts = client.option_contracts(
        ticker,
        expiration_gte=(today + timedelta(days=10)).isoformat(),
        expiration_lte=(today + timedelta(days=45)).isoformat(),
        option_type=otype,
        strike_gte=spot * 0.80,
        strike_lte=spot * 1.20,
    )
    if not contracts:
        return None, "no listed contracts near the money"

    expiries = sorted(
        {d for c in contracts if (d := _parse_date(c.get("expiration_date", "")))}
    )
    if not expiries:
        return None, "could not resolve an expiration"
    expiration = expiries[0]

    pool = [
        c for c in contracts
        if _parse_date(c.get("expiration_date", "")) == expiration
    ]
    strikes = sorted({float(c["strike_price"]) for c in pool})
    if len(strikes) < 2:
        return None, "not enough listed strikes for a spread"

    # Long leg: the listed strike nearest to spot (near the money). Short leg:
    # the strike nearest the drift target, on the OTM side of the long leg.
    long_strike = min(strikes, key=lambda s: abs(s - spot))
    if long:
        target = spot * (1 + target_move)
        otm = [s for s in strikes if s > long_strike]
    else:
        target = spot * (1 - target_move)
        otm = [s for s in strikes if s < long_strike]
    if not otm:
        return None, "no OTM strike available for the short leg"
    short_strike = min(otm, key=lambda s: abs(s - target))

    def _symbol(strike: float) -> str | None:
        for c in pool:
            if float(c["strike_price"]) == strike:
                return c["symbol"]
        return None

    long_sym, short_sym = _symbol(long_strike), _symbol(short_strike)
    if not long_sym or not short_sym:
        return None, "could not map strikes to contracts"

    quotes = client.option_quotes([long_sym, short_sym])
    long_mid = float(quotes.get(long_sym, {}).get("mid") or 0.0)
    short_mid = float(quotes.get(short_sym, {}).get("mid") or 0.0)
    if long_mid <= 0 or short_mid <= 0:
        return None, "missing live quote on a leg"

    net_debit = round(long_mid - short_mid, 2)
    if net_debit <= 0:
        return None, "non-positive debit (bad quotes)"
    width = round(abs(short_strike - long_strike), 2)
    if width <= 0:
        return None, "degenerate spread width"

    legs = [
        SpecLeg(
            symbol=long_sym,
            option_type=otype,
            side="buy",
            position_intent="buy_to_open",
            strike=long_strike,
            mid=long_mid,
        ),
        SpecLeg(
            symbol=short_sym,
            option_type=otype,
            side="sell",
            position_intent="sell_to_open",
            strike=short_strike,
            mid=short_mid,
        ),
    ]
    return (
        DriftSpec(
            legs=legs,
            net_debit=net_debit,
            width=width,
            expiration=expiration,
            spot=round(spot, 2),
            stop_level=live.get("stop_level"),
        ),
        "ok",
    )


def drift_conviction(setup: dict) -> str:
    """Map the drift screen's win-rate + sample depth to a journaling tier."""
    history = setup.get("history") or {}
    wr = history.get("win_rate_5d") or 0.0
    n = history.get("sample_size") or 0
    if wr >= 0.70 and n >= 6:
        return "high"
    if wr >= 0.60 and n >= 4:
        return "medium"
    return "low"
