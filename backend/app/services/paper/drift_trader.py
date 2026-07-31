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

from app.clients.alpaca import AlpacaClient, AlpacaError
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
    client: AlpacaClient, setup: dict, risk_budget: float | None = None
) -> tuple[DriftSpec | None, str]:
    """Return (spec, reason). Picks a near-the-money long leg and an OTM short
    leg sized to the historical drift target, priced from live quotes.

    When ``risk_budget`` (dollars of max loss for one contract) is given and the
    full-width spread's debit would exceed it, the short leg is pulled in toward
    the long leg to the widest spread whose debit fits — so high-priced names
    (where one target-width spread can cost thousands) still size to a contract
    instead of skipping."""
    ticker = setup["ticker"]
    long = setup.get("direction") == "long"
    otype = "call" if long else "put"

    live = setup.get("live") or {}
    spot = client.stock_price(ticker) or live.get("last_close")
    if not spot:
        return None, "no live underlying price"

    # Live broken-thesis guard. The screen evaluates its stop against the prior
    # daily close, so on a sharp intraday reversal it can still flag a setup whose
    # thesis the live tape has already killed (e.g. a long that has round-tripped
    # back below its earnings-day pivot). Don't open into that.
    stop_level = live.get("stop_level")
    if stop_level:
        if long and spot < stop_level:
            return None, (
                f"thesis broken: live ${spot:.2f} is below the earnings-day "
                f"pivot ${stop_level:.2f}"
            )
        if not long and spot > stop_level:
            return None, (
                f"thesis broken: live ${spot:.2f} is above the earnings-day "
                f"pivot ${stop_level:.2f}"
            )

    history = setup.get("history") or {}
    edge = abs(history.get("avg_drift_5d_pct") or 0.0)
    target_move = max(edge, MIN_TARGET_MOVE)

    today = date.today()
    try:
        contracts = client.option_contracts(
            ticker,
            expiration_gte=(today + timedelta(days=10)).isoformat(),
            expiration_lte=(today + timedelta(days=45)).isoformat(),
            option_type=otype,
            strike_gte=spot * 0.80,
            strike_lte=spot * 1.20,
        )
    except AlpacaError as e:
        return None, f"alpaca chain error: {e}"
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

    # Candidate short legs out to the drift target, ordered widest -> narrowest
    # so we keep the most upside that still fits the budget.
    if long:
        target = spot * (1 + target_move)
        cands = sorted([s for s in strikes if long_strike < s <= target], reverse=True)
        if not cands:
            cands = sorted([s for s in strikes if s > long_strike])[:1]
    else:
        target = spot * (1 - target_move)
        cands = sorted([s for s in strikes if target <= s < long_strike])
        if not cands:
            cands = sorted([s for s in strikes if s < long_strike], reverse=True)[:1]
    if not cands:
        return None, "no OTM strike available for the short leg"

    # Step through candidates (cap lookups on dense chains) and take the widest
    # spread whose debit fits the budget.
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

    short_sym = _symbol(short_strike)
    long_sym = _symbol(long_strike)
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
        DriftSpec(
            legs=legs,
            net_debit=net_debit,
            width=width,
            expiration=expiration,
            spot=round(spot, 2),
            stop_level=stop_level,
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
