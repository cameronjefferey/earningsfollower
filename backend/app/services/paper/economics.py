"""Trade-economics gate: decides whether a defined-risk options spread is worth
opening at a *given executable price*. Pure and dependency-free (like risk.py)
so it can be imported by the executor and unit-tested in isolation.

A signal telling us the direction is not enough. The price we can actually get
has to leave real profit relative to the risk, the market has to be liquid
enough that the round-trip cross doesn't swamp the edge, and the expected value
(win_prob x max_profit - loss_prob x max_loss) has to be positive. Every check
runs on the *executable* price -- the marketable-cross limit at entry, and the
actual fill afterward -- never the modeled mid, because that's the number we
truly trade at. That divergence (modeled 12.92, filled 21.55) is what bled the
book: the old gates all looked at the mid.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EntryMetrics:
    """The per-share economics of a candidate at its executable price."""

    max_profit: float
    max_loss: float
    reward_risk: float | None
    expected_value: float | None
    win_prob: float | None


def spread_pnl(is_credit: bool, width: float, price: float) -> tuple[float, float]:
    """Per-share ``(max_profit, max_loss)`` for a defined-risk vertical.

    Credit spread: we collect ``price`` up front; keep all of it if it expires
    out of the money (max profit), lose ``width - price`` if it goes fully in the
    money (max loss). Debit spread: we pay ``price`` and that debit is the entire
    risk (max loss); the most the spread can ever be worth is ``width`` so the
    max profit is ``width - price``.
    """
    width = max(width or 0.0, 0.0)
    price = max(price or 0.0, 0.0)
    if is_credit:
        return round(price, 4), round(max(width - price, 0.0), 4)
    return round(max(width - price, 0.0), 4), round(price, 4)


def reward_risk(max_profit: float, max_loss: float) -> float | None:
    """max_profit : max_loss. ``None`` when there's no defined loss to divide by."""
    if max_loss <= 0:
        return None
    return max_profit / max_loss


def expected_value(win_prob: float, max_profit: float, max_loss: float) -> float:
    """EV per share assuming a binary max-profit / max-loss outcome.

    A defined-risk spread rarely settles exactly at either extreme, but pricing
    the two tails bounds the edge and reliably rejects lopsided setups (tiny
    upside, huge downside) regardless of how confident the signal is."""
    win_prob = min(max(win_prob, 0.0), 1.0)
    return win_prob * max_profit - (1 - win_prob) * max_loss


def leg_liquidity_ok(
    legs: list[dict], quotes: dict, max_spread_frac: float
) -> tuple[bool, str | None]:
    """Every leg must have a two-sided market whose bid/ask width is a small
    fraction of its mid. A wide (or one-sided) quote means the true price is
    unknowable and crossing it bleeds more than the trade can make -- exactly the
    illiquid meme options (25-45 wide MU/AMD spreads) that drained the book."""
    for leg in legs:
        sym = leg.get("symbol")
        q = quotes.get(sym) or {}
        bid = q.get("bid") or 0.0
        ask = q.get("ask") or 0.0
        mid = q.get("mid") or ((bid + ask) / 2 if bid and ask else 0.0)
        if bid <= 0 or ask <= 0 or mid <= 0:
            return False, f"no two-sided market on {sym}"
        if (ask - bid) / mid > max_spread_frac:
            return False, (
                f"{sym} bid/ask too wide "
                f"({(ask - bid) / mid:.0%} > {max_spread_frac:.0%})"
            )
    return True, None


def _fair_price_reason(
    is_credit: bool, width: float, price: float, settings
) -> str | None:
    """The executable price has to leave real room relative to the width.

    Debit: never pay more than ``paper_max_debit_width_frac`` of the width, so
    there's always meaningful upside left (paying 0.90 of a wide spread leaves
    almost none). Credit: never collect less than ``paper_min_credit_width_ratio``
    of the width, so the premium is worth the tail risk."""
    if width <= 0:
        return None
    if is_credit:
        floor = settings.paper_min_credit_width_ratio * width
        if price < floor:
            return (
                f"credit too thin ({price:.2f} < {floor:.2f}, "
                f"{settings.paper_min_credit_width_ratio:.0%} of {width:.0f}-wide)"
            )
    else:
        cap = settings.paper_max_debit_width_frac * width
        if price > cap:
            return (
                f"debit too rich ({price:.2f} > {cap:.2f}, "
                f"{settings.paper_max_debit_width_frac:.0%} of {width:.0f}-wide)"
            )
    return None


def entry_metrics(
    is_credit: bool, width: float, price: float, win_prob: float | None
) -> EntryMetrics:
    max_profit, max_loss = spread_pnl(is_credit, width, price)
    rr = reward_risk(max_profit, max_loss)
    ev = expected_value(win_prob, max_profit, max_loss) if win_prob is not None else None
    return EntryMetrics(
        max_profit=max_profit,
        max_loss=max_loss,
        reward_risk=round(rr, 3) if rr is not None else None,
        expected_value=round(ev, 3) if ev is not None else None,
        win_prob=round(win_prob, 3) if win_prob is not None else None,
    )


def fill_within_plan(
    is_credit: bool, width: float | None, price: float | None, settings
) -> tuple[bool, str | None]:
    """Post-fill safety net: verify the *actual fill* still honors the fair-price
    band and the reward:risk floor. Alpaca paper can fill worse than the limit we
    sent, so a fill that blows past the plan (e.g. a debit filled at 90% of width)
    should be flattened rather than held. Liquidity and EV are not re-checked here
    -- they were validated pre-submit and we can't cheaply re-quote at fill time.
    """
    if width is None or price is None or width <= 0:
        return True, None  # equity or unknown structure: nothing to check
    reason = _fair_price_reason(is_credit, width, price, settings)
    if reason is not None:
        return False, reason
    max_profit, max_loss = spread_pnl(is_credit, width, price)
    rr = reward_risk(max_profit, max_loss)
    if rr is None or rr < settings.paper_min_reward_risk:
        pretty = "n/a" if rr is None else f"{rr:.2f}"
        return False, f"reward:risk too thin ({pretty} < {settings.paper_min_reward_risk})"
    return True, None


def evaluate_entry(
    *,
    is_credit: bool,
    width: float,
    price: float,
    win_prob: float | None,
    legs: list[dict],
    quotes: dict,
    settings,
) -> tuple[bool, str | None, EntryMetrics]:
    """Full entry gate on the executable price. Returns
    ``(ok, reject_reason, metrics)``; ``ok=False`` means do not open the trade.

    Order of checks (cheapest / most decisive first):
      1. Liquidity   -- two-sided, tight per-leg markets.
      2. Fair price  -- debit <= cap of width / credit >= floor of width.
      3. Reward:risk -- max_profit:max_loss above the floor.
      4. Expected value -- win_prob-weighted EV above the floor (when we have a
         win-probability estimate; skipped when None so we never block on missing
         history, the other three gates still apply).
    """
    metrics = entry_metrics(is_credit, width, price, win_prob)

    ok, why = leg_liquidity_ok(legs, quotes, settings.paper_max_leg_spread_frac)
    if not ok:
        return False, f"illiquid: {why}", metrics

    reason = _fair_price_reason(is_credit, width, price, settings)
    if reason is not None:
        return False, reason, metrics

    if metrics.reward_risk is None or metrics.reward_risk < settings.paper_min_reward_risk:
        pretty = "n/a" if metrics.reward_risk is None else f"{metrics.reward_risk}"
        return False, (
            f"reward:risk too thin ({pretty} < {settings.paper_min_reward_risk})"
        ), metrics

    if metrics.expected_value is not None and (
        metrics.expected_value < settings.paper_min_expected_value
    ):
        return False, (
            f"negative expected value ({metrics.expected_value} < "
            f"{settings.paper_min_expected_value}, win_prob {metrics.win_prob})"
        ), metrics

    return True, None, metrics
