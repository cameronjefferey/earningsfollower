"""Build a directional debit spread from a live waves signal.

The waves engine surfaces (trigger, target) pairs where a peer just reported and
a themed name reports soon, with a historical drift lean. Here we turn the lean
into a defined-risk trade that rides the *pre-earnings runup*:

  - bullish lean -> bull call spread (buy near-the-money call, sell an OTM call)
  - bearish lean -> bear put  spread (buy near-the-money put,  sell an OTM put)

We use a debit spread rather than a naked long option for the same reasons drift
does: it caps cost, cuts theta drag, and the short leg is placed near the
expected runup target so we pay only for the move the history predicts. Crucially
it also makes high-priced names (TSM, ASML, ...) tradeable on a small budget —
a single ATM call there can cost thousands, but a tight spread fits. The expiry
is the first one on/after the target's own print, so the option still carries the
elevated pre-print IV we plan to exit before the report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.clients.alpaca import AlpacaClient
from app.services.paper.contracts import SpecLeg

logger = logging.getLogger(__name__)

# Floor on the runup target as a % of spot, so a small historical lean still
# produces a tradeable (not razor-thin) spread.
MIN_TARGET_MOVE = 0.03


@dataclass
class WaveSpec:
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


def build_wave_spec(
    client: AlpacaClient, signal: dict, target_date: date, risk_budget: float | None = None
) -> tuple[WaveSpec | None, str]:
    """Return (spec, reason). Picks a near-the-money long leg and an OTM short leg
    sized to the signal's expected runup, at the first expiry on/after the
    target's print, priced from live quotes.

    When ``risk_budget`` (dollars of max loss for one contract) is given and the
    full-width spread's debit would exceed it, the short leg is pulled in toward
    the long leg to the widest spread whose debit fits — so high-priced names
    still size to a contract instead of skipping."""
    target = signal["target"]
    bullish = signal.get("direction") != "bearish"
    otype = "call" if bullish else "put"

    spot = client.stock_price(target)
    if not spot:
        return None, "no live underlying price"

    runup = abs(signal.get("expected_runup_pct") or 0.0)
    target_move = max(runup, MIN_TARGET_MOVE)

    # Chain around the money at the first expiry on/after the print (so it still
    # carries the pre-print IV).
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

    # Long leg: the listed strike nearest to spot (near the money).
    long_strike = min(strikes, key=lambda s: abs(s - spot))
    long_mid = _mid(long_strike)
    if long_mid <= 0:
        return None, "missing live quote on the long leg"

    # Candidate short legs out to the runup target, widest -> narrowest so we
    # keep the most upside that still fits the budget.
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
        WaveSpec(
            legs=legs,
            option_type=otype,
            net_debit=net_debit,
            width=width,
            expiration=expiration,
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
