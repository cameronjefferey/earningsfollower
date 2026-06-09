from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Rule-of-thumb factor converting an ATM straddle into a ~1 std-dev expected move.
STRADDLE_TO_MOVE = 0.85


@dataclass
class ImpliedMoveResult:
    expiry: date | None
    underlying_price: float | None
    atm_strike: float | None
    straddle_price: float | None
    expected_move_pct: float | None


def _to_date(value: Any) -> date | None:
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def get_prices(symbol: str, start: date, end: date) -> list[dict[str, Any]]:
    """Daily OHLCV bars from Yahoo. Keeps both raw and adjusted close."""
    try:
        df = yf.Ticker(symbol).history(
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=False,
            actions=False,
        )
    except Exception as exc:  # network / delisted / bad symbol
        logger.warning("yfinance price fetch failed for %s: %s", symbol, exc)
        return []
    if df is None or df.empty:
        return []

    bars: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        d = _to_date(ts)
        if d is None:
            continue
        close = _safe_float(row.get("Close"))
        adj = _safe_float(row.get("Adj Close"))
        bars.append(
            {
                "date": d,
                "open": _safe_float(row.get("Open")),
                "high": _safe_float(row.get("High")),
                "low": _safe_float(row.get("Low")),
                "close": close,
                "adj_close": adj if adj is not None else close,
                "volume": _safe_float(row.get("Volume")),
            }
        )
    return bars


def get_earnings_dates(symbol: str, limit: int = 24) -> list[dict[str, Any]]:
    """Historical + upcoming earnings dates as a yfinance fallback for FMP."""
    try:
        df = yf.Ticker(symbol).get_earnings_dates(limit=limit)
    except Exception as exc:
        logger.warning("yfinance earnings dates failed for %s: %s", symbol, exc)
        return []
    if df is None or df.empty:
        return []

    out: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        d = _to_date(ts)
        if d is None:
            continue
        out.append(
            {
                "date": d,
                "eps_estimate": _safe_float(row.get("EPS Estimate")),
                "eps_actual": _safe_float(row.get("Reported EPS")),
            }
        )
    return out


def get_implied_move(symbol: str, after_date: date | None = None) -> ImpliedMoveResult:
    """Compute the options-implied move from the nearest post-earnings expiry.

    Uses the ATM straddle (call + put) x 0.85 as a ~1 std-dev expected move,
    the standard market approximation.
    """
    empty = ImpliedMoveResult(None, None, None, None, None)
    try:
        tk = yf.Ticker(symbol)
        expiries = list(tk.options or [])
    except Exception as exc:
        logger.warning("yfinance options list failed for %s: %s", symbol, exc)
        return empty
    if not expiries:
        return empty

    cutoff = after_date or date.today()
    expiry = _pick_expiry(expiries, cutoff)
    if expiry is None:
        return empty

    underlying = _current_price(tk)
    if underlying is None or underlying <= 0:
        return empty

    try:
        chain = tk.option_chain(expiry.isoformat())
    except Exception as exc:
        logger.warning("yfinance option_chain failed for %s %s: %s", symbol, expiry, exc)
        return empty

    atm_strike = _nearest_strike(chain.calls, chain.puts, underlying)
    if atm_strike is None:
        return empty

    call_price = _leg_price(chain.calls, atm_strike)
    put_price = _leg_price(chain.puts, atm_strike)
    if call_price is None or put_price is None:
        return empty

    straddle = call_price + put_price
    move_pct = (straddle * STRADDLE_TO_MOVE) / underlying
    return ImpliedMoveResult(
        expiry=expiry,
        underlying_price=round(underlying, 4),
        atm_strike=round(atm_strike, 4),
        straddle_price=round(straddle, 4),
        expected_move_pct=round(move_pct, 6),
    )


# --- helpers -----------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pick_expiry(expiries: list[str], cutoff: date) -> date | None:
    parsed = sorted(d for d in (_parse_expiry(e) for e in expiries) if d is not None)
    for d in parsed:
        if d >= cutoff:
            return d
    return parsed[-1] if parsed else None


def _parse_expiry(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _current_price(tk: "yf.Ticker") -> float | None:
    try:
        fi = tk.fast_info
        for key in ("last_price", "lastPrice", "regular_market_price"):
            val = _safe_float(_fast_info_get(fi, key))
            if val:
                return val
    except Exception:
        pass
    try:
        hist = tk.history(period="5d", auto_adjust=False)
        if hist is not None and not hist.empty:
            return _safe_float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def _fast_info_get(fast_info: Any, key: str) -> Any:
    try:
        return fast_info[key]
    except Exception:
        return getattr(fast_info, key, None)


def _nearest_strike(
    calls: pd.DataFrame, puts: pd.DataFrame, underlying: float
) -> float | None:
    strikes = set()
    for df in (calls, puts):
        if df is not None and "strike" in df:
            strikes.update(float(s) for s in df["strike"].tolist())
    if not strikes:
        return None
    return min(strikes, key=lambda s: abs(s - underlying))


def _leg_price(df: pd.DataFrame, strike: float) -> float | None:
    if df is None or "strike" not in df:
        return None
    row = df[df["strike"] == strike]
    if row.empty:
        return None
    record = row.iloc[0]
    last = _safe_float(record.get("lastPrice"))
    bid = _safe_float(record.get("bid"))
    ask = _safe_float(record.get("ask"))
    # Prefer the bid/ask midpoint when both sides are quoted; it is less stale
    # than lastPrice, which can be hours old.
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2
    return last
