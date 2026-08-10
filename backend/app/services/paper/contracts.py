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

from app.clients.alpaca import AlpacaClient, AlpacaError

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
    risk_budget: float | None = None,
    min_credit_ratio: float | None = None,
) -> tuple[TradeSpec | None, str]:
    """Return (spec, reason). spec is None when we can't responsibly build the
    trade; reason explains why (for logging/journaling).

    When ``risk_budget`` (dollars of max loss for one contract) is given and the
    playbook's full-width wings would put a single contract over budget, the
    wings are pulled in to the widest spread whose per-contract risk fits - so
    pricey / high-IV names size to at least one contract instead of skipping.

    ``min_credit_ratio`` is the reward/risk gate: the minimum credit collected as
    a fraction of the spread width. Pulling the wings in raises this ratio (the
    width shrinks faster than the credit), so the same inward walk that fits the
    budget is used to meet the ratio; if no width can satisfy it we skip the
    trade rather than book a lopsided max-loss:profit."""
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
    try:
        contracts = client.option_contracts(
            ticker,
            expiration_gte=earnings_date.isoformat(),
            expiration_lte=(earnings_date + timedelta(days=45)).isoformat(),
            strike_gte=strike_lo,
            strike_lte=strike_hi,
        )
    except AlpacaError as e:
        return None, f"alpaca chain error: {e}"
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

    sell_legs = [l for l in legs if l["action"] == "Sell"]
    buy_legs = [l for l in legs if l["action"] == "Buy"]

    def _nearest(cands: list[dict], target: float) -> dict | None:
        return min(cands, key=lambda c: abs(float(c["strike_price"]) - target)) if cands else None

    # Resolve the short (Sell) legs nearest the playbook targets.
    short_call = next(
        (_nearest(calls, l["strike"]) for l in sell_legs if l["option"] == "call" and l["strike"] is not None),
        None,
    )
    short_put = next(
        (_nearest(puts, l["strike"]) for l in sell_legs if l["option"] == "put" and l["strike"] is not None),
        None,
    )
    want_call = any(l["option"] == "call" for l in buy_legs) and short_call is not None
    want_put = any(l["option"] == "put" for l in buy_legs) and short_put is not None
    if not want_call and not want_put:
        return None, "no defined-risk wing legs to build"

    # Candidate wings beyond each short, ordered nearest -> farthest from it.
    call_wings = (
        [c for c in calls if float(c["strike_price"]) > float(short_call["strike_price"])]
        if want_call
        else []
    )
    put_wings = (
        [c for c in reversed(puts) if float(c["strike_price"]) < float(short_put["strike_price"])]
        if want_put
        else []
    )
    if (want_call and not call_wings) or (want_put and not put_wings):
        return None, "no listed wing strikes beyond the short(s) to cap risk"

    # Price lazily in tiny batches (Alpaca caps symbols/request), caching mids so
    # each candidate width only fetches the few legs it actually needs.
    _mid_cache: dict[str, float] = {}

    def _mid(contract: dict) -> float:
        sym = contract["symbol"]
        if sym not in _mid_cache:
            q = client.option_quotes([sym]).get(sym, {})
            _mid_cache[sym] = float(q.get("mid") or 0.0)
        return _mid_cache[sym]

    # The playbook's intended (widest) wing is the candidate nearest its target.
    def _default_idx(wings: list[dict], target: float | None) -> int | None:
        if not wings or target is None:
            return None
        return min(range(len(wings)), key=lambda i: abs(float(wings[i]["strike_price"]) - target))

    call_target = next((l["strike"] for l in buy_legs if l["option"] == "call"), None)
    put_target = next((l["strike"] for l in buy_legs if l["option"] == "put"), None)
    call_def = _default_idx(call_wings, call_target) if want_call else None
    put_def = _default_idx(put_wings, put_target) if want_put else None

    def _build(ci: int | None, pi: int | None) -> list[SpecLeg]:
        spec_legs: list[SpecLeg] = []
        if want_call:
            spec_legs.append(
                SpecLeg(short_call["symbol"], "call", "sell", "sell_to_open",
                        float(short_call["strike_price"]), _mid(short_call))
            )
            lc = call_wings[ci]
            spec_legs.append(
                SpecLeg(lc["symbol"], "call", "buy", "buy_to_open",
                        float(lc["strike_price"]), _mid(lc))
            )
        if want_put:
            spec_legs.append(
                SpecLeg(short_put["symbol"], "put", "sell", "sell_to_open",
                        float(short_put["strike_price"]), _mid(short_put))
            )
            lp = put_wings[pi]
            spec_legs.append(
                SpecLeg(lp["symbol"], "put", "buy", "buy_to_open",
                        float(lp["strike_price"]), _mid(lp))
            )
        return spec_legs

    def _evaluate(spec_legs: list[SpecLeg]) -> tuple[float, float, float] | None:
        if any(l.mid <= 0 for l in spec_legs):
            return None
        net_credit = round(
            sum(l.mid for l in spec_legs if l.side == "sell")
            - sum(l.mid for l in spec_legs if l.side == "buy"),
            2,
        )
        cs = [l.strike for l in spec_legs if l.option_type == "call"]
        ps = [l.strike for l in spec_legs if l.option_type == "put"]
        cw = (max(cs) - min(cs)) if len(cs) > 1 else 0
        pw = (max(ps) - min(ps)) if len(ps) > 1 else 0
        width = round(max(cw, pw), 2)
        if width <= 0:
            return None
        risk = round((width - net_credit) * 100, 2)
        if risk <= 0:
            return None
        return net_credit, width, risk

    # Walk from the playbook's intended width inward, taking the widest spread
    # whose one-contract risk fits the budget *and* whose credit clears the
    # reward/risk floor (or just the intended width when neither is constrained).
    # Narrowing improves both - risk drops and credit/width rises - so the same
    # inward walk satisfies them together. Step with a stride so dense chains
    # stay to a couple dozen quote lookups at most.
    kmax = max(call_def or 0, put_def or 0)
    stride = max(1, (kmax + 1) // 24)
    ks = sorted(set(list(range(0, kmax + 1, stride)) + [kmax]))
    chosen: tuple[list[SpecLeg], float, float, float] | None = None
    tightest: tuple[list[SpecLeg], float, float, float] | None = None
    for k in ks:
        ci = max(0, call_def - k) if want_call else None
        pi = max(0, put_def - k) if want_put else None
        spec_legs = _build(ci, pi)
        ev = _evaluate(spec_legs)
        if ev is None:
            continue
        net_credit, width, risk = ev
        tightest = (spec_legs, net_credit, width, risk)
        within_budget = risk_budget is None or risk <= risk_budget
        ratio_ok = min_credit_ratio is None or net_credit >= min_credit_ratio * width
        if within_budget and ratio_ok:
            chosen = (spec_legs, net_credit, width, risk)
            break

    if chosen is None:
        if tightest is not None:
            _, tc, tw, tr = tightest
            if risk_budget is not None and tr > risk_budget:
                return None, (
                    f"spread too wide for budget even at min width "
                    f"(${tr:.0f}/ct vs ${risk_budget:.0f})"
                )
            if min_credit_ratio is not None and tw > 0 and tc < min_credit_ratio * tw:
                return None, (
                    f"reward/risk too thin even at min width "
                    f"(credit ${tc:.2f} on ${tw:.0f}-wide = {tc / tw:.0%}, "
                    f"need {min_credit_ratio:.0%})"
                )
        return None, "missing live quotes on one or more legs"

    spec_legs, net_credit, width, max_risk = chosen
    spec = TradeSpec(
        expiration=expiration,
        legs=spec_legs,
        net_credit=net_credit,
        width=width,
        max_risk_per_contract=max_risk,
        occ_symbols=[l.symbol for l in spec_legs],
    )
    return spec, "ok"
