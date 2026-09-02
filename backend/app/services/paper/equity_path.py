"""Account-value path for the Learning page: actual equity vs. today's book.

Actual close comes from Alpaca when the API can reach the paper account;
otherwise we reconstruct from journaled realized P&L so the page still
renders in local/dev. The counterfactual is always journal-only: start at
the same $100k and add only closed trades from books that are still allowed
to open (earnings sell-vol + earnings stock + 5-day losers). Retired books
(reddit, drift, waves) are excluded so you can see the bleed we stopped funding.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.alpaca import AlpacaClient, AlpacaError
from app.db.models import PaperTrade

logger = logging.getLogger(__name__)

STARTING_EQUITY = 100_000.0
_EQUITY_STRUCTURES = ("Long shares", "Short shares")

# Live policy changes that moved the P&L shape. Dates are when the change
# landed on main (UTC calendar day). Snapped to the nearest session on the
# curve at read time.
POLICY_EVENTS: tuple[dict, ...] = (
    {
        "date": "2026-07-09",
        "kind": "fix",
        "title": "Stopped flattening drift the day it opened",
        "detail": "Earnings exit manager no longer auto-closes PEAD trades.",
    },
    {
        "date": "2026-07-14",
        "kind": "add",
        "title": "Earnings stock book",
        "detail": "Same directional lean as sell-vol, expressed as shares.",
    },
    {
        "date": "2026-07-28",
        "kind": "guard",
        "title": "Learned take-profit",
        "detail": "Directional books bank a favorable underlying move instead of giving it back.",
    },
    {
        "date": "2026-08-05",
        "kind": "retire",
        "title": "Reddit retired",
        "detail": "Social-attention debit spreads stopped opening after poor live results.",
    },
    {
        "date": "2026-08-06",
        "kind": "guard",
        "title": "Hard stops armed",
        "detail": "Sell-vol losers cut at 20% of max risk; winners were already being clipped.",
    },
    {
        "date": "2026-08-25",
        "kind": "retire",
        "title": "Drift and waves retired",
        "detail": "Post-print option debits went 0-for-12. Calibration gate turned on.",
    },
    {
        "date": "2026-08-31",
        "kind": "add",
        "title": "5-day loser weekly",
        "detail": "Long the week's worst S&P names for 5 sessions or +10%; earnings ±5d out.",
    },
    {
        "date": "2026-09-02",
        "kind": "guard",
        "title": "Entry model drops book identity",
        "detail": "Fit only live earnings books, no strategy dummy. Earnings stock uses its 10%/7% band, not the 3% clip.",
    },
)

BOOK_LABELS = {
    "earnings": "Earnings sell-vol",
    "earnings_equity": "Earnings stock",
    "drift": "Drift",
    "waves": "Waves",
    "reddit": "Reddit options",
    "reddit_equity": "Reddit stock",
    "reversal": "5-day losers",
}


def book_of(t: PaperTrade) -> str:
    strat = (t.strategy or "earnings").lower()
    is_eq = (t.structure or "") in _EQUITY_STRUCTURES
    if strat == "earnings":
        return "earnings_equity" if is_eq else "earnings"
    if strat == "reddit":
        return "reddit_equity" if is_eq else "reddit"
    return strat


def allowed_books(settings) -> frozenset[str]:
    """Books still allowed to *open* under live flags."""
    books = {"earnings"}
    if getattr(settings, "paper_earnings_equity_enabled", True):
        books.add("earnings_equity")
    if getattr(settings, "paper_drift_enabled", False):
        books.add("drift")
    if getattr(settings, "paper_waves_enabled", False):
        books.add("waves")
    if getattr(settings, "paper_reddit_enabled", False):
        books.add("reddit")
        books.add("reddit_equity")
    if getattr(settings, "paper_reversal_enabled", True):
        books.add("reversal")
    return frozenset(books)


def _day(dt: datetime | date | None) -> date | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.date()
    return dt


def _summarize(rows: list[PaperTrade]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0, "wins": 0, "win_rate": None, "total_pnl": 0.0}
    wins = sum(1 for t in rows if (t.realized_pnl or 0) > 0)
    total = round(sum(float(t.realized_pnl or 0) for t in rows), 2)
    return {
        "n": n,
        "wins": wins,
        "win_rate": round(wins / n, 3),
        "total_pnl": total,
    }


def _fetch_alpaca_series() -> tuple[list[dict], str]:
    """Daily equity from the paper account. Empty on failure."""
    client = AlpacaClient()
    try:
        if not client.enabled:
            return [], "journal"
        raw = client.portfolio_history(period="1A", timeframe="1D")
    except (AlpacaError, Exception) as e:  # noqa: BLE001 - page must still render
        logger.warning("portfolio history unavailable: %s", e)
        return [], "journal"
    finally:
        client.close()

    timestamps = raw.get("timestamp") or []
    equities = raw.get("equity") or []
    out: list[dict] = []
    for ts, eq in zip(timestamps, equities):
        try:
            d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
            val = float(eq)
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        if val <= 0:
            continue
        out.append({"date": d.isoformat(), "actual": round(val, 2)})
    return out, "alpaca"


def _journal_dates(closed: list[PaperTrade]) -> list[date]:
    days = [_day(t.closed_at) for t in closed]
    days = [d for d in days if d is not None]
    if not days:
        return []
    first, last = min(days), max(days)
    event_days = [date.fromisoformat(ev["date"]) for ev in POLICY_EVENTS]
    if event_days:
        first = min(first, min(event_days))
        last = max(last, max(event_days))
    last = max(last, date.today())
    return _weekday_range(first, last)


def _cumulative_on_dates(
    closed: list[PaperTrade],
    dates: list[date],
    start: float,
    include: frozenset[str] | None,
) -> list[float]:
    """Running start+pnl as of each date (inclusive). include=None means all books."""
    by_day: dict[date, float] = defaultdict(float)
    for t in closed:
        d = _day(t.closed_at)
        if d is None:
            continue
        if include is not None and book_of(t) not in include:
            continue
        by_day[d] += float(t.realized_pnl or 0)
    running = start
    i_day = 0
    ordered = sorted(by_day)
    out: list[float] = []
    for d in dates:
        while i_day < len(ordered) and ordered[i_day] <= d:
            running += by_day[ordered[i_day]]
            i_day += 1
        out.append(round(running, 2))
    return out


def _snap_events(dates: list[str]) -> list[dict]:
    if not dates:
        return []
    date_set = set(dates)
    parsed = [date.fromisoformat(d) for d in dates]
    out = []
    for ev in POLICY_EVENTS:
        target = date.fromisoformat(ev["date"])
        snapped = next((d for d in parsed if d >= target), parsed[-1])
        iso = snapped.isoformat()
        if iso not in date_set:
            continue
        out.append({**ev, "chart_date": iso})
    return out


def _weekday_range(start: date, end: date) -> list[date]:
    out: list[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def equity_path_report(
    db: Session,
    settings,
    *,
    alpaca_points: list[dict] | None = None,
) -> dict:
    closed = [
        t
        for t in db.scalars(
            select(PaperTrade).where(
                PaperTrade.status == "closed",
                PaperTrade.realized_pnl.is_not(None),
                PaperTrade.closed_at.is_not(None),
            )
        ).all()
    ]
    keep = allowed_books(settings)
    kept_rows = [t for t in closed if book_of(t) in keep]
    retired_rows = [t for t in closed if book_of(t) not in keep]

    start = STARTING_EQUITY
    if alpaca_points is None:
        fetched, source = _fetch_alpaca_series()
        alpaca_points = fetched
    else:
        source = "alpaca" if alpaca_points else "journal"

    if alpaca_points:
        source = "alpaca"
        points = [{"date": p["date"], "actual": float(p["actual"])} for p in alpaca_points]
    else:
        source = "journal"
        dates = _journal_dates(closed)
        if dates:
            actual_vals = _cumulative_on_dates(closed, dates, start, None)
            points = [
                {"date": d.isoformat(), "actual": v}
                for d, v in zip(dates, actual_vals)
            ]
        else:
            points = []

    dates = [date.fromisoformat(p["date"]) for p in points]
    if dates:
        allowed_vals = _cumulative_on_dates(closed, dates, start, keep)
        all_realized = _cumulative_on_dates(closed, dates, start, None)
        for p, a, r in zip(points, allowed_vals, all_realized):
            p["allowed"] = a
            p["all_realized"] = r

    by_book = []
    buckets: dict[str, list[PaperTrade]] = defaultdict(list)
    for t in closed:
        buckets[book_of(t)].append(t)
    for key in sorted(buckets, key=lambda k: BOOK_LABELS.get(k, k)):
        summary = _summarize(buckets[key])
        by_book.append({
            "book": key,
            "label": BOOK_LABELS.get(key, key),
            "allowed": key in keep,
            **summary,
        })

    last = points[-1] if points else None
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "starting_equity": STARTING_EQUITY,
        "actual_source": source,
        "allowed_books": sorted(keep),
        "allowed_labels": [BOOK_LABELS.get(b, b) for b in sorted(keep)],
        "points": points,
        "events": _snap_events([p["date"] for p in points]),
        "by_book": by_book,
        "all": _summarize(closed),
        "allowed": _summarize(kept_rows),
        "retired": _summarize(retired_rows),
        "latest_actual": last["actual"] if last else None,
        "latest_allowed": last.get("allowed") if last else None,
        "window_note": (
            "Actual is Alpaca daily close. "
            "'Today's book' starts at $100k and adds closed-trade P&L from "
            "earnings sell-vol and earnings stock only. Open marks are not in that line."
            if source == "alpaca"
            else "Alpaca history unavailable; actual is reconstructed from closed-trade P&L. "
            "'Today's book' starts at $100k and excludes reddit, drift, and waves."
        ),
    }
