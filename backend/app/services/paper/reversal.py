"""5-day-loser weekly paper book.

Long the N worst S&P 500 names over the last 5 sessions, hold 5 sessions,
skip names with earnings ±5 sessions, equal-weight, non-overlapping
rebalance. Backtest (2019–2026, current S&P, 10 bps): 5-name mean
+1.09%/hold, t=3.36. A hard daily-close 10% TP cut that to +0.55%/hold.
Live follows the tested hold; the 10% clip is a shadow mark only.

No earnings-equity stop, no entry model until this book has its own sample.
Current S&P membership until the PIT rebuild (due 2026-09-29). Size by
how deep the washout is: 3% at −12% or worse, 2% from there to −8%,
1% for milder names that still make the top 5. Not the 1.22 Sharpe.
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
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


def reversal_conviction(
    ret_5: float,
    settings=None,
    *,
    high_ret: float = -0.12,
    medium_ret: float = -0.08,
) -> str:
    """Deeper 5-session washout = more confident bounce.

    ``high`` at or below ``high_ret`` (default −12%), ``medium`` at or below
    ``medium_ret`` (default −8%), otherwise ``low``. Thresholds come off
    settings when passed.
    """
    if settings is not None:
        high_ret = float(getattr(settings, "paper_reversal_conviction_high_ret", high_ret))
        medium_ret = float(
            getattr(settings, "paper_reversal_conviction_medium_ret", medium_ret)
        )
    if ret_5 <= high_ret:
        return "high"
    if ret_5 <= medium_ret:
        return "medium"
    return "low"


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


def shadow_hold_due(opened_on: date | None, today: date, hold_days: int) -> bool:
    """True once the research hold has elapsed, so we can mark a 10% TP vs hold."""
    if opened_on is None or hold_days <= 0:
        return False
    return hold_elapsed(opened_on, today) >= hold_days


def shadow_vs_live(
    *,
    entry_px: float,
    live_exit_px: float,
    hold_px: float,
    shares: int,
) -> dict:
    """P&L if we had ridden the 5-session hold instead of clipping at +10%."""
    live_pnl = (live_exit_px - entry_px) * shares
    hold_pnl = (hold_px - entry_px) * shares
    return {
        "live_exit_px": round(live_exit_px, 2),
        "hold_px": round(hold_px, 2),
        "live_pnl": round(live_pnl, 2),
        "hold_pnl": round(hold_pnl, 2),
        "hold_minus_live": round(hold_pnl - live_pnl, 2),
        "live_ret": round(live_exit_px / entry_px - 1, 4) if entry_px else None,
        "hold_ret": round(hold_px / entry_px - 1, 4) if entry_px else None,
        "shares": int(shares),
    }


def reversal_exit_reason(
    t, today: date, settings, spot_now: float | None = None,
    *,
    in_earn_window: bool = False,
) -> str | None:
    """5-session hold, plus operational escapes.

    Live does not clip at +10% — the backtest hold beat that override
    (+1.09%/hold vs +0.55%). The 10% path is a shadow mark only.
    Does not use the global 3% learned take-profit. Flatten if the name
    is discovered inside the earnings ±buffer after entry.
    """
    if t.signal_id in getattr(settings, "paper_force_close_id_set", set()):
        return "manual close"
    if (t.note or "").startswith(BAD_FILL_PREFIX):
        return "flatten: bad entry fill"
    if in_earn_window:
        return "flatten: earnings window"
    tp = float(getattr(settings, "paper_reversal_take_profit_pct", 0) or 0)
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
) -> tuple[list[ReversalCandidate], list[ReversalCandidate], list[ReversalCandidate]]:
    """Rank liquid names by trailing `lookback`-session return.

    ``bars`` needs columns ticker, date, close, volume. Dates may be timestamps.
    Returns (picks, skipped_for_earnings, pool) — ``pool`` is the worst-15
    liquid names *before* the earnings skip, so a later calendar fill can
    audit whether the cohort was correctly filtered, not just the names that
    opened. Skipped names would have made the worst-N list but sit inside the
    earnings window.
    """
    if bars is None or bars.empty:
        return [], [], []
    df = bars.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df["ticker"] = df["ticker"].astype(str)
    df = df.sort_values(["ticker", "date"])
    if as_of is not None:
        cutoff = pd.Timestamp(as_of)
        df = df[df["date"] <= cutoff]
    if df.empty:
        return [], [], []
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
        return [], [], []

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

    # Incomplete current-session bars (or missing historical days) make
    # pct_change(5) compare the wrong closes. Live MRNA -11.4% at 13:33 UTC
    # was a 9:33am quote vs Aug 25, not five complete sessions.
    sessions = sorted(df["date"].unique())
    if len(sessions) < lookback + 1:
        return [], [], []
    required = sessions[-lookback - 1 :]
    have = (
        df[df["date"].isin(required)]
        .groupby("ticker")["date"]
        .nunique()
    )
    complete = set(have[have >= lookback + 1].index)
    last = last[last["ticker"].isin(complete)]
    if last.empty:
        return [], [], []

    last = last.sort_values("ret_n", ascending=True)

    def _cand(r) -> ReversalCandidate:
        return ReversalCandidate(
            ticker=str(r.ticker),
            ret_5=float(r.ret_n),
            close=float(r.close),
            dollar_vol=float(r.dollar_vol),
            as_of=as_of_d,
            skipped_earn=bool(r.earn_window),
        )

    # Liquid losers before the earnings skip — persist this, not just the top-N
    # that survived, so a thin calendar can't hide who was even considered.
    pool = [_cand(r) for r in last.head(15).itertuples(index=False)]
    # Pull a deep enough loser list that earnings drops still leave `top_n`.
    deep = last.head(max(top_n * 8, 40))
    skipped: list[ReversalCandidate] = []
    picks: list[ReversalCandidate] = []
    for r in deep.itertuples(index=False):
        cand = _cand(r)
        if cand.skipped_earn:
            skipped.append(cand)
            continue
        picks.append(cand)
        if len(picks) >= top_n:
            break
    return picks, skipped, pool


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


def load_panel(
    tickers: list[str], as_of: date | None = None, *, refresh: bool = False
) -> pd.DataFrame:
    """~30 sessions of OHLCV for the universe. Cached per as_of calendar day.

    ``refresh`` skips the cache. The Friday preview needs the 12:55 print,
    not the panel the 12:30 run already stored.
    """
    import yfinance as yf

    day = (as_of or date.today()).isoformat()
    path = cache_dir() / f"panel_{day}.pkl"
    if path.exists() and not refresh:
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


def rank_live(
    db: Session | None,
    settings,
    as_of: date | None = None,
    *,
    include_today: bool = False,
) -> tuple[list[ReversalCandidate], list[ReversalCandidate], list[ReversalCandidate], date | None]:
    """Load universe + panel + earnings and rank. Returns (picks, skipped, pool, as_of).

    ``include_today`` keeps the in-progress session. Live entries leave it
    off; the Friday 12:55 preview turns it on so the list matches the tape.
    """
    tickers = load_sp500_tickers()
    if not tickers:
        return [], [], [], None
    panel = load_panel(tickers, as_of=as_of, refresh=include_today)
    if panel.empty:
        return [], [], [], None
    panel["date"] = pd.to_datetime(panel["date"]).dt.tz_localize(None).dt.normalize()
    last = panel["date"].max().date()
    today = date.today()
    if include_today and as_of is None:
        as_of = today
    if as_of is None:
        # Live rank must not use today's in-progress daily bar. The 13:33 UTC
        # cron is ~3 minutes after the open; Yahoo already has a partial session
        # whose volume and return are not a 5-day close-to-close.
        prior = [
            d.date()
            for d in panel["date"].unique()
            if d.date() < today
        ]
        signal_day = max(prior) if prior else last
    else:
        signal_day = as_of
    sessions_by_ticker = {
        t: [d.date() for d in pd.to_datetime(g["date"]).dt.tz_localize(None).dt.normalize().unique()]
        for t, g in panel.groupby("ticker")
    }
    all_sessions = sorted({d.date() for d in pd.to_datetime(panel["date"]).dt.normalize().unique()})
    earn = load_earnings_reactions(
        db, set(tickers), signal_day, sessions_by_ticker, all_sessions
    )
    picks, skipped, pool = rank_from_panel(
        panel,
        earn_reaction=earn,
        as_of=signal_day,
        lookback=int(getattr(settings, "paper_reversal_lookback_days", 5)),
        top_n=int(getattr(settings, "paper_reversal_top_n", 5)),
        min_price=float(getattr(settings, "paper_reversal_min_price", 10.0)),
        min_dollar_vol=float(getattr(settings, "paper_reversal_min_dollar_vol", 50_000_000.0)),
        earn_buffer=int(getattr(settings, "paper_reversal_earn_buffer_days", 5)),
    )
    # Watch/as_of is the last bar actually ranked, not today's calendar date
    # (a 13:30 UTC run is pre-open and only has yesterday's close).
    panel_as_of = (
        picks[0].as_of if picks else skipped[0].as_of if skipped else last
    )
    return picks, skipped, pool, panel_as_of


def write_watch(
    picks: list[ReversalCandidate],
    skipped: list[ReversalCandidate],
    *,
    as_of: date | None,
    holding: bool,
    opened: list[str] | None = None,
    note: str | None = None,
    pool: list[ReversalCandidate] | None = None,
    settings=None,
) -> dict:
    cache_dir()

    def _row(cand: ReversalCandidate) -> dict:
        row = cand.as_watch_dict()
        conv = reversal_conviction(cand.ret_5, settings)
        row["conviction"] = conv
        if settings is not None and hasattr(settings, "paper_reversal_risk_fraction"):
            row["risk_frac"] = round(float(settings.paper_reversal_risk_fraction(conv)), 4)
        return row

    payload = {
        "as_of": as_of.isoformat() if as_of else None,
        "ranked_at": datetime.utcnow().isoformat() + "Z",
        "holding": holding,
        "opened": opened or [],
        "note": note,
        "candidates": [_row(c) for c in picks],
        "skipped_earn": [_row(c) for c in skipped[:15]],
        "pool": [_row(c) for c in (pool or [])[:15]],
    }
    WATCH_PATH.write_text(json.dumps(payload))
    return payload


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


PACIFIC = ZoneInfo("America/Los_Angeles")
_PREVIEW_LEAD = timedelta(minutes=30)


def preview_wait_target(now: datetime | None = None) -> datetime | None:
    """Friday 12:55 PM Pacific, if ``now`` is inside the preceding 30 minutes.

    The paper cron already fires at 12:30 PM local (19:30 UTC during PDT,
    20:30 UTC during PST). That run waits and sends. It does not place orders.
    """
    now = now or datetime.now(PACIFIC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PACIFIC)
    else:
        now = now.astimezone(PACIFIC)
    if now.weekday() != 4:
        return None
    target = now.replace(hour=12, minute=55, second=0, microsecond=0)
    delta = target - now
    if timedelta(0) < delta <= _PREVIEW_LEAD:
        return target
    return None


def format_reversal_preview(
    picks: list[ReversalCandidate],
    skipped: list[ReversalCandidate],
    held: dict[str, str],
    *,
    reversal_open: bool,
    as_of: date | None,
    today: date,
    settings,
) -> str:
    """Telegram body for the Friday candidate list. Never an order."""
    lines = [
        "5-day losers — next week",
        "Friday 12:55 PM PT preview. No orders.",
    ]
    if as_of is None:
        lines.append("No ranking (panel empty).")
    elif as_of < today:
        lines.append(
            f"Last bar in the download is {as_of.isoformat()}, so Friday's "
            "session is not in this list yet."
        )
    else:
        lines.append(f"Through the {as_of.isoformat()} print, about 5 min before the close.")
    if reversal_open:
        lines.append("Current cohort is still open. This is the next rebalance, not a fill today.")
    lines.append("The live book uses the closing print, so a name can still drop off.")
    if not picks:
        lines.append("No names cleared price, dollar-volume, and earnings filters.")
    for i, cand in enumerate(picks, start=1):
        conv = reversal_conviction(cand.ret_5, settings)
        frac = (
            settings.paper_reversal_risk_fraction(conv)
            if hasattr(settings, "paper_reversal_risk_fraction")
            else None
        )
        size = f" · {frac:.0%}" if frac is not None else ""
        note = ""
        owner = held.get(cand.ticker)
        if owner and owner != STRATEGY:
            note = f" · skip, already in {owner}"
        elif owner == STRATEGY:
            note = " · already in this cohort"
        lines.append(
            f"{i}. {cand.ticker} {cand.ret_5:+.1%}{size} ({conv}){note}"
        )
    earn = [c for c in skipped if c.skipped_earn][:8]
    if earn:
        lines.append(
            "Earnings window: "
            + ", ".join(f"{c.ticker} {c.ret_5:+.1%}" for c in earn)
        )
    return "\n".join(lines)


def notify_reversal_preview(db: Session, settings) -> bool:
    """Rank with today's session and text the list. Does not submit orders."""
    from app.db.models import PaperTrade
    from app.services.notify import send_telegram, telegram_configured

    if not telegram_configured():
        logger.warning("reversal preview skipped: Telegram is not configured")
        return False
    picks, skipped, _pool, as_of = rank_live(db, settings, include_today=True)
    open_rows = db.scalars(
        select(PaperTrade).where(PaperTrade.status.in_(("pending", "open", "closing")))
    ).all()
    held = {t.ticker: (t.strategy or "") for t in open_rows}
    text = format_reversal_preview(
        picks,
        skipped,
        held,
        reversal_open=any((t.strategy or "") == STRATEGY for t in open_rows),
        as_of=as_of,
        today=date.today(),
        settings=settings,
    )
    logger.info("reversal preview:\n%s", text)
    return send_telegram(text)


def deliver_reversal_preview(target: datetime) -> None:
    """Sleep until ``target`` if needed, then send once for that calendar day."""
    import time

    from app.config import get_settings
    from app.db.session import session_scope

    now = datetime.now(PACIFIC)
    delay = (target.astimezone(PACIFIC) - now).total_seconds()
    if delay > 0:
        logger.info(
            "reversal preview waiting %.0fs until %s", delay, target.isoformat()
        )
        time.sleep(delay)
    day = target.astimezone(PACIFIC).date().isoformat()
    marker = cache_dir() / f"preview_{day}"
    if marker.exists():
        logger.info("reversal preview already sent for %s", day)
        return
    settings = get_settings()
    if not getattr(settings, "paper_reversal_preview_enabled", True):
        return
    with session_scope() as db:
        ok = notify_reversal_preview(db, settings)
    if ok:
        marker.write_text(target.isoformat())

