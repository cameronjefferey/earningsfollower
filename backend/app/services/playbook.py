"""Synthesize an explicit, opinionated earnings trade from the data the app
already computes (reaction history, implied move, post-earnings drift, analyst
trend, price action).

The goal is to be concrete: a direction, a vol stance, a specific options
structure with strikes sized to the expected move, when to put it on, and what
invalidates it - rather than a pile of stats the user has to assemble themselves.

This is research output, not financial advice; callers surface the caveats.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime


@dataclass
class PlayLeg:
    action: str          # "Sell" | "Buy"
    option: str          # "call" | "put"
    label: str           # e.g. "short call", "long call (wing)"
    strike: float | None
    note: str


@dataclass
class EarningsPlay:
    headline: str                 # one-line recommendation
    direction: str                # "bearish" | "bullish" | "neutral"
    conviction: str               # "low" | "medium" | "high"
    vol_stance: str               # "sell" | "buy" | "neutral"
    structure: str                # human name of the recommended structure
    structure_detail: str         # explicit how-to sentence
    timing: str
    legs: list[dict]
    expected_range_low: float | None
    expected_range_high: float | None
    spot: float | None
    invalidation: str
    bias_reasons: list[str]
    vol_reasons: list[str]
    caveats: list[str]


def build_playbook(
    summary: dict,
    implied: dict | None,
    analyst: dict | None,
    prices: list[dict],
    next_earnings_date: str | None,
    next_earnings_timing: str | None = None,
) -> dict | None:
    """Return a structured, explicit earnings play, or None if there isn't
    enough history to say anything responsible."""
    if not summary or summary.get("sample_size", 0) < 4:
        return None

    spot = (implied or {}).get("underlying_price")
    em = (implied or {}).get("expected_move_pct")

    direction, dir_score, bias_reasons = _direction(summary, analyst, prices)
    vol_stance, vol_reasons = _vol_stance(implied)
    conviction = _conviction(dir_score, vol_stance, summary, implied)

    structure, structure_detail, legs = _structure(
        direction, vol_stance, spot, em
    )
    timing = _timing(next_earnings_date, vol_stance)
    invalidation = _invalidation(direction, spot, em, prices)
    caveats = _caveats(summary, implied, analyst)

    rng_low = round(spot * (1 - em), 2) if (spot and em) else None
    rng_high = round(spot * (1 + em), 2) if (spot and em) else None

    headline = _headline(direction, vol_stance, structure)

    play = EarningsPlay(
        headline=headline,
        direction=direction,
        conviction=conviction,
        vol_stance=vol_stance,
        structure=structure,
        structure_detail=structure_detail,
        timing=timing,
        legs=[asdict(leg) for leg in legs],
        expected_range_low=rng_low,
        expected_range_high=rng_high,
        spot=round(spot, 2) if spot else None,
        invalidation=invalidation,
        bias_reasons=bias_reasons,
        vol_reasons=vol_reasons,
        caveats=caveats,
    )
    return asdict(play)


# --- direction ---------------------------------------------------------------


def _direction(
    summary: dict, analyst: dict | None, prices: list[dict]
) -> tuple[str, float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    trend = _trend(prices, lookback=60)
    if trend is not None:
        if trend <= -0.05:
            score -= 1
            reasons.append(f"Downtrend: {_pct(trend)} over the last ~3 months.")
        elif trend >= 0.05:
            score += 1
            reasons.append(f"Uptrend: {_pct(trend)} over the last ~3 months.")

    mob = summary.get("avg_move_on_beat_pct")
    if mob is not None:
        if mob < -0.005:
            score -= 1
            reasons.append(
                f"Sells the news: average reaction to a beat is {_pct(mob)} "
                "(priced for perfection)."
            )
        elif mob > 0.01:
            score += 0.5
            reasons.append(f"Beats get rewarded: avg reaction on a beat is {_pct(mob)}.")

    recent = _recent_move_bias(prices, summary)
    if recent is not None:
        if recent < 0:
            score -= 1
            reasons.append("Recent earnings reactions skew negative.")
        elif recent > 0:
            score += 1
            reasons.append("Recent earnings reactions skew positive.")

    dab = summary.get("avg_drift_after_beat_pct")
    if dab is not None:
        if dab < -0.005:
            score -= 0.5
            reasons.append(f"Post-beat drift fades ({_pct(dab)} over 5 days).")
        elif dab > 0.005:
            score += 0.5
            reasons.append(f"Post-beat drift continues up ({_pct(dab)} over 5 days).")

    trend_a = (analyst or {}).get("trend")
    if trend_a == "deteriorating":
        score -= 0.5
        reasons.append("Analyst sentiment is deteriorating (fewer bulls than 3mo ago).")
    elif trend_a == "improving":
        score += 0.5
        reasons.append("Analyst sentiment is improving (more bulls than 3mo ago).")

    up_rate = summary.get("up_rate")
    if up_rate is not None:
        if up_rate >= 0.6:
            score += 0.3
        elif up_rate <= 0.4:
            score -= 0.3

    if score <= -1:
        direction = "bearish"
    elif score >= 1:
        direction = "bullish"
    else:
        direction = "neutral"
    return direction, score, reasons


def _trend(prices: list[dict], lookback: int) -> float | None:
    closes = [p["close"] for p in prices if p.get("close")]
    if len(closes) <= lookback:
        if len(closes) >= 2 and closes[0]:
            return closes[-1] / closes[0] - 1.0
        return None
    past = closes[-(lookback + 1)]
    if not past:
        return None
    return closes[-1] / past - 1.0


def _recent_move_bias(prices: list[dict], summary: dict) -> float | None:
    # Use the signed average of the most recent earnings moves if present.
    last_move = summary.get("last_move_pct")
    avg_move = summary.get("avg_move_pct")
    if last_move is None and avg_move is None:
        return None
    # Weight the most recent print heavily; it's the freshest read on regime.
    parts = [v for v in (last_move, last_move, avg_move) if v is not None]
    return sum(parts) / len(parts) if parts else None


# --- vol stance --------------------------------------------------------------


def _vol_stance(implied: dict | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not implied or implied.get("expected_move_pct") is None:
        return "neutral", ["No live implied move available to judge vol."]

    em = implied.get("expected_move_pct")
    hist = implied.get("historical_avg_abs_move_pct")
    exceed = implied.get("exceed_rate")
    edge = implied.get("edge_verdict")
    richness = implied.get("richness")

    if hist and em:
        reasons.append(
            f"Options price a {_mag(em)} move vs a {_mag(hist)} historical average"
            + (f" ({richness:.2f}x)." if richness else ".")
        )
    if exceed is not None:
        only = "only " if exceed <= 0.5 else ""
        reasons.append(
            f"Realized moves reached the implied move {only}{_mag(exceed)} of the time "
            f"(n={implied.get('edge_sample')})."
        )

    if edge == "seller_edge":
        return "sell", reasons
    if edge == "buyer_edge":
        return "buy", reasons
    return "neutral", reasons


def _conviction(
    dir_score: float, vol_stance: str, summary: dict, implied: dict | None
) -> str:
    strength = abs(dir_score)
    sample = summary.get("sample_size", 0)
    edge_sample = (implied or {}).get("edge_sample", 0) or 0
    aligned = vol_stance in ("sell", "buy")
    if strength >= 2.5 and sample >= 12 and aligned and edge_sample >= 8:
        return "high"
    if strength >= 1.5 and sample >= 8:
        return "medium"
    return "low"


# --- structure ---------------------------------------------------------------


def _structure(
    direction: str, vol_stance: str, spot: float | None, em: float | None
) -> tuple[str, str, list[PlayLeg]]:
    sized = spot is not None and em is not None

    def k(mult: float) -> float | None:
        return _round_strike(spot * (1 + mult * em)) if sized else None

    # Sell premium: defined-risk credit spreads / condor sized to the move.
    if vol_stance == "sell":
        if direction == "bearish":
            short, long = k(+1.0), k(+1.6)
            legs = [
                PlayLeg("Sell", "call", "short call", short,
                        "just above the expected-move high"),
                PlayLeg("Buy", "call", "long call (wing)", long, "defines max risk"),
            ]
            detail = (
                "Sell a call near the top of the expected move and buy a higher call "
                "to cap risk. Net credit; wins if the stock falls, stays flat, or "
                "rises less than the expected move. IV crush after the print helps."
            )
            return "Bear call (call credit) spread", detail, legs
        if direction == "bullish":
            short, long = k(-1.0), k(-1.6)
            legs = [
                PlayLeg("Sell", "put", "short put", short,
                        "just below the expected-move low"),
                PlayLeg("Buy", "put", "long put (wing)", long, "defines max risk"),
            ]
            detail = (
                "Sell a put near the bottom of the expected move and buy a lower put "
                "to cap risk. Net credit; wins if the stock rises, stays flat, or "
                "falls less than the expected move. IV crush after the print helps."
            )
            return "Bull put (put credit) spread", detail, legs
        # neutral + sell vol -> iron condor
        legs = [
            PlayLeg("Sell", "call", "short call", k(+1.0), "expected-move high"),
            PlayLeg("Buy", "call", "long call (wing)", k(+1.6), "caps upside risk"),
            PlayLeg("Sell", "put", "short put", k(-1.0), "expected-move low"),
            PlayLeg("Buy", "put", "long put (wing)", k(-1.6), "caps downside risk"),
        ]
        detail = (
            "Sell both an out-of-the-money call and put at the edges of the expected "
            "move, with long wings outside them. Net credit; wins if the stock stays "
            "inside the expected move through the print."
        )
        return "Iron condor", detail, legs

    # Buy premium: directional debit spreads (cheaper than naked, defined risk).
    if vol_stance == "buy":
        if direction == "bearish":
            buy, sell = k(0.0), k(-1.0)
            legs = [
                PlayLeg("Buy", "put", "long put", buy, "near the money"),
                PlayLeg("Sell", "put", "short put", sell,
                        "at the expected-move low, cheapens the trade"),
            ]
            detail = (
                "Buy a near-the-money put and sell a put at the expected-move low. "
                "Defined risk, directional bearish; profits if the move is bigger than "
                "priced to the downside."
            )
            return "Bear put (put debit) spread", detail, legs
        if direction == "bullish":
            buy, sell = k(0.0), k(+1.0)
            legs = [
                PlayLeg("Buy", "call", "long call", buy, "near the money"),
                PlayLeg("Sell", "call", "short call", sell,
                        "at the expected-move high, cheapens the trade"),
            ]
            detail = (
                "Buy a near-the-money call and sell a call at the expected-move high. "
                "Defined risk, directional bullish; profits if the move is bigger than "
                "priced to the upside."
            )
            return "Bull call (call debit) spread", detail, legs
        # neutral + buy vol -> long straddle
        legs = [
            PlayLeg("Buy", "call", "long call", k(0.0), "at the money"),
            PlayLeg("Buy", "put", "long put", k(0.0), "at the money"),
        ]
        detail = (
            "Buy the at-the-money call and put. Profits if the realized move is bigger "
            "than the (cheap) implied move, in either direction."
        )
        return "Long straddle", detail, legs

    # Neutral vol: lean on direction only, defined-risk vertical.
    if direction == "bearish":
        buy, sell = k(0.0), k(-1.0)
        legs = [
            PlayLeg("Buy", "put", "long put", buy, "near the money"),
            PlayLeg("Sell", "put", "short put", sell, "expected-move low"),
        ]
        return (
            "Bear put (put debit) spread",
            "Directional bearish, defined risk; vol looks fairly priced so a debit "
            "spread is reasonable.",
            legs,
        )
    if direction == "bullish":
        buy, sell = k(0.0), k(+1.0)
        legs = [
            PlayLeg("Buy", "call", "long call", buy, "near the money"),
            PlayLeg("Sell", "call", "short call", sell, "expected-move high"),
        ]
        return (
            "Bull call (call debit) spread",
            "Directional bullish, defined risk; vol looks fairly priced so a debit "
            "spread is reasonable.",
            legs,
        )
    return (
        "Stand aside",
        "No clear directional or volatility edge right now - the cleanest trade is no "
        "trade. Re-check closer to the print.",
        [],
    )


def _timing(next_earnings_date: str | None, vol_stance: str) -> str:
    d = _parse(next_earnings_date)
    if d is None:
        return (
            "No earnings date scheduled yet - treat this as a directional/vol read, "
            "not an event trade, until a date is set."
        )
    dte = (d - date.today()).days
    when = d.strftime("%b %d, %Y")
    if vol_stance == "sell":
        return (
            f"Put it on 1-3 trading days before the {when} print ({dte} days out) to "
            "capture peak premium, then let the post-earnings IV crush work for you. "
            "Selling vol earlier just adds days of directional risk before the catalyst."
        )
    if vol_stance == "buy":
        return (
            f"Buy premium a week or two ahead of the {when} print ({dte} days out), "
            "before IV fully ramps - buying the day before earnings means paying peak vol."
        )
    return f"Next print is {when} ({dte} days out)."


def _invalidation(
    direction: str, spot: float | None, em: float | None, prices: list[dict]
) -> str:
    if direction == "bearish":
        level = _round_strike(spot * (1 + 0.5 * em)) if (spot and em) else None
        lvl = f" (≈${level})" if level else ""
        return (
            f"Thesis breaks if it reclaims the broken trend and closes higher{lvl} "
            "before the print - stand down or flip the structure."
        )
    if direction == "bullish":
        level = _round_strike(spot * (1 - 0.5 * em)) if (spot and em) else None
        lvl = f" (≈${level})" if level else ""
        return (
            f"Thesis breaks if it loses the trend and closes lower{lvl} before the "
            "print - stand down or flip the structure."
        )
    return (
        "If a clear trend develops before the print, switch from the neutral structure "
        "to a directional one."
    )


def _caveats(summary: dict, implied: dict | None, analyst: dict | None) -> list[str]:
    caveats = ["Research from your own data - not financial advice. Size your own risk."]

    sample = summary.get("sample_size", 0)
    if sample < 8:
        caveats.append(f"Small sample: only {sample} past prints in the history.")

    # Flag a price-scale mismatch between the options spot and the analyst target
    # (e.g. a split-adjusted price feed vs. unadjusted consensus), which makes the
    # headline "upside vs target" unreliable.
    spot = (implied or {}).get("underlying_price")
    target = (analyst or {}).get("price_target")
    if spot and target:
        ratio = target / spot
        if ratio > 1.4 or ratio < 0.6:
            caveats.append(
                "Spot and analyst-target price scales diverge (likely a split "
                "adjustment) - ignore the headline upside-vs-target figure; the "
                "percentage-based signals here are unaffected."
            )

    if (implied or {}).get("expected_move_pct") is None:
        caveats.append(
            "No live implied move - strikes can't be sized to the expected move; "
            "treat the structure as directional guidance only."
        )
    return caveats


def _headline(direction: str, vol_stance: str, structure: str) -> str:
    if structure == "Stand aside":
        return "No clear edge - stand aside"
    vol_txt = {
        "sell": "sell the rich premium",
        "buy": "buy the cheap premium",
        "neutral": "vol fairly priced",
    }[vol_stance]
    return f"{direction.capitalize()} lean, {vol_txt}: {structure}"


# --- helpers -----------------------------------------------------------------


def _round_strike(price: float | None) -> float | None:
    if price is None or price <= 0:
        return None
    if price < 100:
        step = 1.0
    elif price < 250:
        step = 5.0
    elif price < 1000:
        step = 10.0
    else:
        step = 25.0
    return round(price / step) * step


def _pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.1f}%"


def _mag(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _parse(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
