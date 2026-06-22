"""Map a playbook's target strikes onto real, listed Alpaca option contracts and
price the resulting multi-leg combo.

The playbook hands us idealized strikes (e.g. "sell the 145 call, buy the 160").
Here we find the actual listed contracts nearest those strikes at the first
expiry after the earnings print, pull live quotes, and compute the net credit
and width so the executor can size and submit the order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.clients.alpaca import AlpacaClient

logger = logging.getLogger(__name__)


@dataclass
class SpecLeg:
    symbol: str
    option_type: str       # "call" | "put"
    side: str              # "buy" | "sell"
    position_intent: str   # "buy_to_open" | "sell_to_open"
    strike: float
    mid: float
    ratio_qty: str = "1"


@dataclass
class TradeSpec:
    expiration: date
    legs: list[SpecLeg]
    net_credit: float       # per share (positive = we collect premium)
    width: float            # widest spread, per share
    max_risk_per_contract: float  # dollars
    note: str = ""
    occ_symbols: list[str] = field(default_factory=list)


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def build_trade_spec(
    client: AlpacaClient,
    ticker: str,
    playbook: dict,
    earnings_date: date,
) -> tuple[TradeSpec | None, str]:
    """Return (spec, reason). spec is None when we can't responsibly build the
    trade; reason explains why (for logging/journaling)."""
    legs = playbook.get("legs") or []
    if len(legs) < 2:
        return None, "playbook has no defined-risk legs"

    lo = playbook.get("expected_range_low")
    hi = playbook.get("expected_range_high")
    if not lo or not hi:
        return None, "no expected-move range to bound strikes"

    # Pull a bounded slice of the chain around the wings. The window runs ~45
    # days past the print so we still find the first expiry on names that only
    # list monthly options (next monthly can be 3-4 weeks out).
    strike_lo = lo * 0.8
    strike_hi = hi * 1.25
    contracts = client.option_contracts(
        ticker,
        expiration_gte=earnings_date.isoformat(),
        expiration_lte=(earnings_date + timedelta(days=45)).isoformat(),
        strike_gte=strike_lo,
        strike_lte=strike_hi,
    )
    if not contracts:
        return None, "no listed contracts in the expected-move range"

    # Choose the first expiry strictly after the print (captures the event + the
    # post-earnings IV crush before expiry), else the earliest available.
    expiries = sorted(
        {d for c in contracts if (d := _parse_date(c.get("expiration_date", "")))}
    )
    after = [e for e in expiries if e > earnings_date]
    expiration = after[0] if after else (expiries[0] if expiries else None)
    if expiration is None:
        return None, "could not resolve an expiration"

    pool = [
        c
        for c in contracts
        if _parse_date(c.get("expiration_date", "")) == expiration
    ]
    calls = sorted(
        (c for c in pool if c.get("type") == "call"),
        key=lambda c: float(c["strike_price"]),
    )
    puts = sorted(
        (c for c in pool if c.get("type") == "put"),
        key=lambda c: float(c["strike_price"]),
    )

    chosen: list[dict] = []
    for leg in legs:
        otype = leg["option"]
        target = leg["strike"]
        if target is None:
            return None, "playbook leg missing a strike"
        candidates = calls if otype == "call" else puts
        if not candidates:
            return None, f"no listed {otype}s at {expiration}"
        best = min(candidates, key=lambda c: abs(float(c["strike_price"]) - target))
        chosen.append(
            {
                "contract": best,
                "option_type": otype,
                "side": "sell" if leg["action"] == "Sell" else "buy",
            }
        )

    occ = [c["contract"]["symbol"] for c in chosen]
    quotes = client.option_quotes(occ)

    spec_legs: list[SpecLeg] = []
    for c in chosen:
        sym = c["contract"]["symbol"]
        q = quotes.get(sym, {})
        mid = float(q.get("mid") or 0.0)
        spec_legs.append(
            SpecLeg(
                symbol=sym,
                option_type=c["option_type"],
                side=c["side"],
                position_intent="sell_to_open" if c["side"] == "sell" else "buy_to_open",
                strike=float(c["contract"]["strike_price"]),
                mid=mid,
            )
        )

    if any(l.mid <= 0 for l in spec_legs):
        return None, "missing live quotes on one or more legs"

    net_credit = round(
        sum(l.mid for l in spec_legs if l.side == "sell")
        - sum(l.mid for l in spec_legs if l.side == "buy"),
        2,
    )

    call_strikes = [l.strike for l in spec_legs if l.option_type == "call"]
    put_strikes = [l.strike for l in spec_legs if l.option_type == "put"]
    call_width = (max(call_strikes) - min(call_strikes)) if len(call_strikes) > 1 else 0
    put_width = (max(put_strikes) - min(put_strikes)) if len(put_strikes) > 1 else 0
    width = round(max(call_width, put_width), 2)
    if width <= 0:
        return None, "could not derive a spread width from selected strikes"

    max_risk_per_contract = round((width - net_credit) * 100, 2)
    if max_risk_per_contract <= 0:
        return None, "modeled max risk is non-positive (bad quotes)"

    spec = TradeSpec(
        expiration=expiration,
        legs=spec_legs,
        net_credit=net_credit,
        width=width,
        max_risk_per_contract=max_risk_per_contract,
        occ_symbols=occ,
    )
    return spec, "ok"
