"""5-day-loser weekly paper book.

Long the N worst S&P 500 names over the last 5 sessions, hold 5 sessions
or take-profit at +10%, skip names with earnings ±5 sessions, equal-weight,
non-overlapping rebalance. Backtest (2019–2026, current S&P, 10 bps):
5-name mean +1.09%/hold, t=3.36. Long-only — shorting the winners lost.

The 10% take-profit is this book's own exit, not the 3% learned clip from
the earnings directional books (that band maxes at 8% and would bank a
bounce this sleeve is meant to ride). No earnings-equity stop, no entry
model until this book has its own sample.
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EarningsEvent

logger = logging.getLogger(__name__)

STRATEGY = "reversal"
SP500_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "master/data/constituents.csv"
)
CACHE_DIR = Path(tempfile.gettempdir()) / "earningsfollower_reversal"
WATCH_PATH = CACHE_DIR / "watch.json"
BAD_FILL_PREFIX = "bad fill:"


@dataclass(frozen=True)
class ReversalCandidate:
    ticker: str
    ret_5: float
    close: float
    dollar_vol: float
    as_of: date
    skipped_earn: bool = False

    def as_watch_dict(self) -> dict:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        d["ret_5"] = round(self.ret_5, 4)
        d["close"] = round(self.close, 2)
        d["dollar_vol"] = round(self.dollar_vol, 0)
        return d


def yahoo_symbol(ticker: str) -> str:
    """Yahoo uses BRK-B; the S&P list and Alpaca use BRK.B."""
    return ticker.replace(".", "-")


def trading_days_between(start: date, end: date) -> int:
    """Weekday count from start (exclusive) to end (exclusive of neither? numpy
    busday_count is [start, end) so Mon→next Mon = 5). Holidays count as days."""
    if end <= start:
        return 0
    return int(np.busday_count(np.datetime64(start), np.datetime64(end)))


def hold_elapsed(opened_on: date, today: date) -> int:
    return trading_days_between(opened_on, today)


def reversal_exit_reason(
    t, today: date, settings, spot_now: float | None = None,
    *,
    in_earn_window: bool = False,
) -> str | None:
    """+10% take-profit, then the 5-session hold, plus operational escapes.

    Does not use the global 3% learned take-profit — that clip is for the
    retired debit rides and would flatten a bounce this sleeve is hunting.
    Flatten if the name is discovered inside the earnings ±buffer after entry
    (calendar was incomplete at rank time).
    """
    if t.signal_id in getattr(settings, "paper_force_close_id_set", set()):
        return "manual close"
    if (t.note or "").startswith(BAD_FILL_PREFIX):
        return "flatten: bad entry fill"
    if in_earn_window:
        return "flatten: earnings window"
    tp = float(getattr(settings, "paper_reversal_take_profit_pct", 0.10) or 0)
    entry_px = getattr(t, "entry_credit", None) or getattr(t, "spot_entry", None)
    if tp > 0 and spot_now and entry_px:
        move = spot_now / entry_px - 1.0
        if move >= tp:
            return f"take-profit ({move:+.1%})"
    opened = t.opened_at or t.created_at
    if opened is None:
        return None
    start = opened.date() if hasattr(opened, "date") else opened
    hold = int(getattr(settings, "paper_reversal_hold_days", 5))
    elapsed = hold_elapsed(start, today)
    if elapsed >= hold:
        return f"5-day hold ({elapsed} sessions)"
    return None


def next_session(d: date, sessions: list[date]) -> date | None:
    for s in sessions:
        if s > d:
            return s
    return None


def reaction_dates(
    events: Iterable[tuple[str, date, str]],
    sessions_by_ticker: dict[str, list[date]] | None = None,
    all_sessions: list[date] | None = None,
) -> set[tuple[str, date]]:
    """Map an earnings print to the session the stock reacts.

    AMC → next session; BMO → same day; unknown → both (conservative).
    """
    out: set[tuple[str, date]] = set()
    for ticker, d, timing in events:
        cal = None
        if sessions_by_ticker is not None:
            cal = sessions_by_ticker.get(ticker)
        if not cal:
            cal = all_sessions
        timing = (timing or "unknown").lower()
        if timing == "amc":
            nxt = next_session(d, cal) if cal else d + timedelta(days=1)
            if nxt is not None:
                out.add((ticker, nxt))
        elif timing == "bmo":
            out.add((ticker, d))
        else:
            out.add((ticker, d))
            nxt = next_session(d, cal) if cal else None
            if nxt is not None:
                out.add((ticker, nxt))
    return out


def rank_from_panel(
    bars: pd.DataFrame,
    *,
    earn_reaction: set[tuple[str, date]] | None = None,
    as_of: date | None = None,
    lookback: int = 5,
    top_n: int = 5,
    min_price: float = 10.0,
    min_dollar_vol: float = 50_000_000.0,
    earn_buffer: int = 5,
) -> tuple[list[ReversalCandidate], list[ReversalCandidate]]:
    """Rank liquid names by trailing `lookback`-session return.

    ``bars`` needs columns ticker, date, close, volume. Dates may be timestamps.
    Returns (picks, skipped_for_earnings) — skipped names would have made the
    worst-N list but sit inside the earnings window.
    """
    if bars is None or bars.empty:
        return [], []
    df = bars.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df["ticker"] = df["ticker"].astype(str)
    df = df.sort_values(["ticker", "date"])
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        df = df[df["date"] <= cutoff]
    if df.empty:
        return [], []
    as_ts = df["date"].max()
    as_of_d = as_ts.date()

    g = df.groupby("ticker", sort=False)
    df["ret_n"] = g["close"].pct_change(lookback)
    df["dollar_vol"] = df["close"] * df["volume"]

    last = df[df["date"] == as_ts].copy()
    last = last[
        last["close"].ge(min_price)
        & last["dollar_vol"].ge(min_dollar_vol)
        & last["ret_n"].notna()
    ]
    if last.empty:
        return [], []

    earn_set = earn_reaction or set()
    last["is_earn"] = [
        (str(r.ticker), r.date.date() if hasattr(r.date, "date") else r.date) in earn_set
        for r in last.itertuples(index=False)
    ]
    # Window on the full panel so ±buffer uses this ticker's own sessions.
    df["is_earn"] = [
        (str(r.ticker), r.date.date() if hasattr(r.date, "date") else r.date) in earn_set
        for r in df.itertuples(index=False)
    ]
    ge = df.groupby("ticker")["is_earn"]
    win = ge.transform(lambda s: False)
    for k in range(-earn_buffer, earn_buffer + 1):
        win = win | ge.shift(-k).fillna(False)
    df["earn_window"] = win.astype(bool)
    last = last.merge(
        df.loc[df["date"] == as_ts, ["ticker", "earn_window"]],
        on="ticker",
        how="left",
    )
    last["earn_window"] = last["earn_window"].fillna(False).astype(bool)

    last = last.sort_values("ret_n", ascending=True)
    # Pull a deep enough loser list that earnings drops still leave `top_n`.
    deep = last.head(max(top_n * 8, 40))
    skipped: list[ReversalCandidate] = []
    picks: list[ReversalCandidate] = []
    for r in deep.itertuples(index=False):
        cand = ReversalCandidate(
            ticker=str(r.ticker),
            ret_5=float(r.ret_n),
            close=float(r.close),
            dollar_vol=float(r.dollar_vol),
            as_of=as_of_d,
            skipped_earn=bool(r.earn_window),
        )
        if cand.skipped_earn:
            skipped.append(cand)
            continue
        picks.append(cand)
        if len(picks) >= top_n:
            break
    return picks, skipped


def cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def load_sp500_tickers() -> list[str]:
    """Current S&P 500 constituents. Cached a day so a failed fetch still ranks."""
    path = cache_dir() / "sp500.json"
    if path.exists() and datetime.utcnow() - datetime.utcfromtimestamp(path.stat().st_mtime) < timedelta(hours=24):
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    tickers: list[str] = []
    try:
        req = Request(SP500_URL, headers={"User-Agent": "earningsfollower/reversal"})
        with urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        lines = text.splitlines()
        # Symbol is the first column.
        for line in lines[1:]:
            sym = line.split(",", 1)[0].strip().strip('"')
            if sym:
                tickers.append(sym)
    except (URLError, TimeoutError, OSError) as e:
        logger.warning("S&P 500 list fetch failed: %s", e)
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                return []
        return []
    if tickers:
        path.write_text(json.dumps(tickers))
    return tickers


def _flatten_yf(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["ticker", "date", "close", "volume"])
    cols = raw.columns
    if isinstance(cols, pd.MultiIndex):
        level0 = set(cols.get_level_values(0))
        # yfinance 0.2: (ticker, field) or (field, ticker).
        fields = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        ticker_first = bool(level0 - fields)
        for t in tickers:
            ysym = yahoo_symbol(t)
            try:
                if ticker_first:
                    sub = raw[ysym] if ysym in level0 else None
                else:
                    sub = raw.xs(ysym, axis=1, level=1) if ysym in cols.get_level_values(1) else None
            except (KeyError, ValueError):
                sub = None
            if sub is None or getattr(sub, "empty", True):
                continue
            close = sub.get("Close") if hasattr(sub, "get") else sub["Close"]
            vol = sub.get("Volume") if hasattr(sub, "get") else sub["Volume"]
            if close is None:
                continue
            piece = pd.DataFrame({"close": close, "volume": vol}).dropna(subset=["close"])
            piece["ticker"] = t
            piece["date"] = piece.index
            rows.append(piece.reset_index(drop=True))
    else:
        # Single ticker.
        t = tickers[0] if tickers else "UNKNOWN"
        piece = pd.DataFrame(
            {"close": raw["Close"], "volume": raw.get("Volume", 0), "ticker": t}
        ).dropna(subset=["close"])
        piece["date"] = piece.index
        rows.append(piece.reset_index(drop=True))
    if not rows:
        return pd.DataFrame(columns=["ticker", "date", "close", "volume"])
    return pd.concat(rows, ignore_index=True)


def load_panel(tickers: list[str], as_of: date | None = None) -> pd.DataFrame:
    """~30 sessions of OHLCV for the universe. Cached per as_of calendar day."""
    import yfinance as yf

    day = (as_of or date.today()).isoformat()
    path = cache_dir() / f"panel_{day}.pkl"
    if path.exists():
        try:
            return pd.read_pickle(path)
        except Exception:  # noqa: BLE001
            logger.warning("reversal panel cache unreadable; refetching")
    ysyms = [yahoo_symbol(t) for t in tickers]
    try:
        raw = yf.download(
            ysyms,
            period="45d",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            threads=True,
            progress=False,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("yfinance panel download failed: %s", e)
        # Fall back to yesterday's cache if any.
        prev = sorted(cache_dir().glob("panel_*.pkl"))
        if prev:
            try:
                return pd.read_pickle(prev[-1])
            except Exception:  # noqa: BLE001
                return pd.DataFrame(columns=["ticker", "date", "close", "volume"])
        return pd.DataFrame(columns=["ticker", "date", "close", "volume"])
    panel = _flatten_yf(raw, tickers)
    if not panel.empty:
        panel.to_pickle(path)
    return panel


def load_earnings_reactions(
    db: Session | None,
    tickers: set[str],
    as_of: date,
    sessions_by_ticker: dict[str, list[date]],
    all_sessions: list[date],
) -> set[tuple[str, date]]:
    """Union of our journal + FMP's bulk calendar, mapped to reaction sessions."""
    lo = as_of - timedelta(days=21)
    hi = as_of + timedelta(days=21)
    events: list[tuple[str, date, str]] = []
    if db is not None:
        rows = db.scalars(
            select(EarningsEvent).where(
                EarningsEvent.date >= lo,
                EarningsEvent.date <= hi,
                EarningsEvent.ticker.in_(tickers),
            )
        ).all()
        events.extend((r.ticker, r.date, r.timing or "unknown") for r in rows)
    have = {(t, d) for t, d, _ in events}
    try:
        from app.clients.fmp import FMPClient

        cal = FMPClient().earnings_calendar(lo.isoformat(), hi.isoformat()) or []
        for row in cal:
            sym = (row.get("symbol") or row.get("ticker") or "").upper()
            if sym not in tickers:
                continue
            raw_d = row.get("date")
            if not raw_d:
                continue
            d = date.fromisoformat(str(raw_d)[:10])
            if (sym, d) in have:
                continue
            timing = (row.get("time") or row.get("timing") or "unknown") or "unknown"
            events.append((sym, d, str(timing)))
            have.add((sym, d))
    except Exception as e:  # noqa: BLE001
        logger.warning("FMP earnings calendar failed for reversal: %s", e)
    return reaction_dates(events, sessions_by_ticker, all_sessions)


def tickers_in_earn_buffer(
    db: Session | None,
    tickers: Iterable[str],
    as_of: date,
    buffer: int = 5,
) -> set[str]:
    """Names whose print is within ``buffer`` trading days of ``as_of``.

    Used to flatten a live reversal row if the calendar was incomplete at
    entry and we later learn the name was inside the skip window. Missing
    calendar data fails open (hold), not flatten.
    """
    names = {str(t).upper() for t in tickers if t}
    if not names or buffer < 0:
        return set()
    lo = as_of - timedelta(days=21)
    hi = as_of + timedelta(days=21)
    events: list[tuple[str, date]] = []
    if db is not None:
        rows = db.scalars(
            select(EarningsEvent).where(
                EarningsEvent.date >= lo,
                EarningsEvent.date <= hi,
                EarningsEvent.ticker.in_(names),
            )
        ).all()
        events.extend((r.ticker, r.date) for r in rows)
    have = set(events)
    try:
        from app.clients.fmp import FMPClient

        cal = FMPClient().earnings_calendar(lo.isoformat(), hi.isoformat()) or []
        for row in cal:
            sym = (row.get("symbol") or row.get("ticker") or "").upper()
            if sym not in names:
                continue
            raw_d = row.get("date")
            if not raw_d:
                continue
            d = date.fromisoformat(str(raw_d)[:10])
            if (sym, d) in have:
                continue
            events.append((sym, d))
            have.add((sym, d))
    except Exception as e:  # noqa: BLE001
        logger.warning("FMP earnings calendar failed for reversal flatten: %s", e)
    out: set[str] = set()
    for ticker, d in events:
        if d >= as_of:
            dist = int(np.busday_count(np.datetime64(as_of), np.datetime64(d)))
        else:
            dist = int(np.busday_count(np.datetime64(d), np.datetime64(as_of)))
        if dist <= buffer:
            out.add(ticker)
    return out


def rank_live(db: Session | None, settings, as_of: date | None = None) -> tuple[list[ReversalCandidate], list[ReversalCandidate], date | None]:
    """Load universe + panel + earnings and rank. Returns (picks, skipped, as_of)."""
    tickers = load_sp500_tickers()
    if not tickers:
        return [], [], None
    panel = load_panel(tickers, as_of=as_of)
    if panel.empty:
        return [], [], None
    panel["date"] = pd.to_datetime(panel["date"]).dt.tz_localize(None).dt.normalize()
    last = panel["date"].max().date()
    signal_day = as_of or last
    sessions_by_ticker = {
        t: [d.date() for d in pd.to_datetime(g["date"]).dt.tz_localize(None).dt.normalize().unique()]
        for t, g in panel.groupby("ticker")
    }
    all_sessions = sorted({d.date() for d in pd.to_datetime(panel["date"]).dt.normalize().unique()})
    earn = load_earnings_reactions(
        db, set(tickers), signal_day, sessions_by_ticker, all_sessions
    )
    picks, skipped = rank_from_panel(
        panel,
        earn_reaction=earn,
        as_of=signal_day,
        lookback=int(getattr(settings, "paper_reversal_lookback_days", 5)),
        top_n=int(getattr(settings, "paper_reversal_top_n", 5)),
        min_price=float(getattr(settings, "paper_reversal_min_price", 10.0)),
        min_dollar_vol=float(getattr(settings, "paper_reversal_min_dollar_vol", 50_000_000.0)),
        earn_buffer=int(getattr(settings, "paper_reversal_earn_buffer_days", 5)),
    )
    return picks, skipped, signal_day


def write_watch(
    picks: list[ReversalCandidate],
    skipped: list[ReversalCandidate],
    *,
    as_of: date | None,
    holding: bool,
    opened: list[str] | None = None,
    note: str | None = None,
) -> None:
    cache_dir()
    payload = {
        "as_of": as_of.isoformat() if as_of else None,
        "ranked_at": datetime.utcnow().isoformat() + "Z",
        "holding": holding,
        "opened": opened or [],
        "note": note,
        "candidates": [c.as_watch_dict() for c in picks],
        "skipped_earn": [c.as_watch_dict() for c in skipped[:15]],
    }
    WATCH_PATH.write_text(json.dumps(payload))


def read_watch() -> dict | None:
    if not WATCH_PATH.exists():
        return None
    try:
        data = json.loads(WATCH_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    # Stale after a week — a dead cache shouldn't sit on the paper page.
    ranked = data.get("ranked_at") or ""
    try:
        ts = datetime.fromisoformat(ranked.replace("Z", ""))
    except ValueError:
        return data
    if datetime.utcnow() - ts > timedelta(days=7):
        return None
    return data
