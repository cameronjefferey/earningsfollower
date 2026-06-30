"""Build a directional debit spread from a Reddit sentiment signal.

The sentiment service surfaces (ticker, direction, conviction) where Reddit
chatter is spiking with a clear lean. Here we express that as a defined-risk
options trade — never naked, so a coordinated pump that rugs can only ever cost
the debit paid:

  - bullish lean -> bull call spread (buy near-the-money call, sell an OTM call)
  - bearish lean -> bear put  spread (buy near-the-money put,  sell an OTM put)

Same shape as the waves/drift builders: a debit spread caps cost, cuts theta
drag, makes pricey names tradeable on a tiny budget, and the short leg is placed
at the move the conviction implies. The expiry is short-dated (attention fades
fast) but with enough runway for the move to play out before theta bites.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.clients.alpaca import AlpacaClient
from app.config import get_settings
from app.services.paper.contracts import SpecLeg

logger = logging.getLogger(__name__)

# Conviction -> target move (% of spot) the short leg is sized to.
_TARGET_MOVE = {"high": 0.12, "medium": 0.08, "low": 0.05}
MIN_TARGET_MOVE = 0.05


@dataclass
class RedditSpec:
    legs: list[SpecLeg]      # [long leg, short leg]
    option_type: str         # "call" | "put"
    net_debit: float         # per share, what we pay to open (max loss)
    width: float             # strike distance, per share (max value)
    expiration: date
    spot: float


def _parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def build_reddit_spec(
    client: AlpacaClient, signal: dict, risk_budget: float | None = None
) -> tuple[RedditSpec | None, str]:
    """Return (spec, reason). Near-the-money long leg + an OTM short leg sized to
    the conviction-implied move, at the first expiry in the configured DTE band,
    priced from live quotes. When ``risk_budget`` is given, the short leg is
    pulled in to the widest spread whose debit fits."""
    settings = get_settings()
    ticker = signal["ticker"]
    bullish = signal.get("direction") == "bullish"
    if signal.get("direction") not in ("bullish", "bearish"):
        return None, "no tradeable direction"
    otype = "call" if bullish else "put"

    spot = client.stock_price(ticker)
    if not spot:
        return None, "no live underlying price"

    target_move = max(
        _TARGET_MOVE.get(signal.get("conviction", "low"), MIN_TARGET_MOVE),
        MIN_TARGET_MOVE,
    )

    today = date.today()
    contracts = client.option_contracts(
        ticker,
        expiration_gte=(today + timedelta(days=settings.paper_reddit_min_dte)).isoformat(),
        expiration_lte=(today + timedelta(days=settings.paper_reddit_max_dte)).isoformat(),
        option_type=otype,
        strike_gte=spot * 0.80,
        strike_lte=spot * 1.20,
    )
    if not contracts:
        return None, "no listed contracts near the money in the DTE band"

    expiries = sorted(
        {d for c in contracts if (d := _parse_date(c.get("expiration_date", "")))}
    )
    if not expiries:
        return None, "could not resolve an expiration"
    expiration = expiries[0]

    pool = [c for c in contracts if _parse_date(c.get("expiration_date", "")) == expiration]
    strikes = sorted({float(c["strike_price"]) for c in pool})
    if len(strikes) < 2:
        return None, "not enough listed strikes for a spread"

    def _symbol(strike: float) -> str | None:
        for c in pool:
            if float(c["strike_price"]) == strike:
                return c["symbol"]
        return None

    _mid_cache: dict[float, float] = {}

    def _mid(strike: float) -> float:
        if strike not in _mid_cache:
            sym = _symbol(strike)
            q = client.option_quotes([sym]).get(sym, {}) if sym else {}
            _mid_cache[strike] = float(q.get("mid") or 0.0)
        return _mid_cache[strike]

    long_strike = min(strikes, key=lambda s: abs(s - spot))
    long_mid = _mid(long_strike)
    if long_mid <= 0:
        return None, "missing live quote on the long leg"

    if bullish:
        target_px = spot * (1 + target_move)
        cands = sorted([s for s in strikes if long_strike < s <= target_px], reverse=True)
        if not cands:
            cands = sorted([s for s in strikes if s > long_strike])[:1]
    else:
        target_px = spot * (1 - target_move)
        cands = sorted([s for s in strikes if target_px <= s < long_strike])
        if not cands:
            cands = sorted([s for s in strikes if s < long_strike], reverse=True)[:1]
    if not cands:
        return None, "no OTM strike available for the short leg"

    stride = max(1, len(cands) // 16)
    ordered = cands[::stride]
    if cands[-1] not in ordered:
        ordered.append(cands[-1])

    short_strike = short_mid = net_debit = width = None
    tightest = None
    for s in ordered:
        m = _mid(s)
        if m <= 0:
            continue
        debit = round(long_mid - m, 2)
        if debit <= 0:
            continue
        w = round(abs(s - long_strike), 2)
        tightest = (s, m, debit, w)
        if risk_budget is None or debit * 100 <= risk_budget:
            short_strike, short_mid, net_debit, width = s, m, debit, w
            break

    if short_strike is None:
        if risk_budget is not None and tightest is not None:
            return None, (
                f"debit too rich for budget even at min width "
                f"(${tightest[2] * 100:.0f}/ct vs ${risk_budget:.0f})"
            )
        return None, "no priceable short leg for the spread"

    long_sym = _symbol(long_strike)
    short_sym = _symbol(short_strike)
    if not long_sym or not short_sym:
        return None, "could not map strikes to contracts"
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
        RedditSpec(
            legs=legs,
            option_type=otype,
            net_debit=net_debit,
            width=width,
            expiration=expiration,
            spot=round(spot, 2),
        ),
        "ok",
    )


def reddit_conviction(signal: dict) -> str:
    """The sentiment scorer already assigns a conviction tier; pass it through
    (defaulting to low) so sizing maps cleanly onto the risk fractions."""
    c = signal.get("conviction", "low")
    return c if c in ("low", "medium", "high") else "low"
