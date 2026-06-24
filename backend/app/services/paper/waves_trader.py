"""Build a directional long-option trade from a live waves signal.

The waves engine surfaces (trigger, target) pairs where a peer just reported and
a themed name reports soon, with a historical drift lean. Here we turn the lean
into a concrete trade: a slightly-ITM call (bullish) or put (bearish) on the
target, at the first expiry on/after its own earnings (so the option still
carries the elevated pre-print IV we plan to sell back before the report).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.clients.alpaca import AlpacaClient

logger = logging.getLogger(__name__)


@dataclass
class WaveSpec:
    symbol: str
    option_type: str   # "call" | "put"
    strike: float
    expiration: date
    premium: float     # per share (mid)
    spot: float


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def build_wave_spec(
    client: AlpacaClient, signal: dict, target_date: date
) -> tuple[WaveSpec | None, str]:
    """Return (spec, reason). Picks a slightly-ITM option in the signal's
    direction for the target, priced from live quotes."""
    target = signal["target"]
    bullish = signal.get("direction") != "bearish"
    otype = "call" if bullish else "put"

    spot = client.stock_price(target)
    if not spot:
        return None, "no live underlying price"

    # Pull the chain around the money at the first expiry on/after the print.
    contracts = client.option_contracts(
        target,
        expiration_gte=target_date.isoformat(),
        expiration_lte=(target_date + timedelta(days=45)).isoformat(),
        option_type=otype,
        strike_gte=spot * 0.80,
        strike_lte=spot * 1.20,
    )
    if not contracts:
        return None, "no listed contracts near the money"

    expiries = sorted(
        {d for c in contracts if (d := _parse_date(c.get("expiration_date", "")))}
    )
    after = [e for e in expiries if e >= target_date]
    expiration = after[0] if after else (expiries[-1] if expiries else None)
    if expiration is None:
        return None, "could not resolve an expiration"

    pool = [
        c for c in contracts
        if _parse_date(c.get("expiration_date", "")) == expiration
    ]
    # Slightly ITM: for calls that's the listed strike just below spot; for puts
    # the strike just above spot. Fall back to the nearest strike to spot.
    if bullish:
        itm = [c for c in pool if float(c["strike_price"]) <= spot]
        pick = (
            max(itm, key=lambda c: float(c["strike_price"]))
            if itm
            else min(pool, key=lambda c: abs(float(c["strike_price"]) - spot))
        )
    else:
        itm = [c for c in pool if float(c["strike_price"]) >= spot]
        pick = (
            min(itm, key=lambda c: float(c["strike_price"]))
            if itm
            else min(pool, key=lambda c: abs(float(c["strike_price"]) - spot))
        )

    sym = pick["symbol"]
    quote = client.option_quotes([sym]).get(sym, {})
    premium = float(quote.get("mid") or 0.0)
    if premium <= 0:
        return None, "no live quote on the chosen contract"

    return (
        WaveSpec(
            symbol=sym,
            option_type=otype,
            strike=float(pick["strike_price"]),
            expiration=expiration,
            premium=round(premium, 2),
            spot=round(spot, 2),
        ),
        "ok",
    )


def wave_conviction(signal: dict) -> str:
    """Map the historical lead-lag quality to a journaling conviction tier."""
    stats = signal.get("stats") or {}
    wr = stats.get("win_rate") or 0.0
    n = stats.get("sample_size") or 0
    if wr >= 0.75 and n >= 6:
        return "high"
    if wr >= 0.65:
        return "medium"
    return "low"
