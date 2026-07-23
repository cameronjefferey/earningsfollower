from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Company, EarningsEvent, ImpliedMove, ThemeMembership
from app.services.analyst import analyst_payload
from app.services.implied import implied_payload
from app.services.peers import shared_themes
from app.services.playbook import build_playbook
from app.services.prices import load_price_series
from app.services.reactions import reaction_payload, summarize, compute_reactions
from app.services.waves import peers_lead_lag
from app.universe import load_universe


def recent_prices(db: Session, ticker: str, days: int = 130) -> list[dict]:
    """Most recent ~`days` trading days of closing prices for a quick chart."""
    series = load_price_series(db, ticker)
    out: list[dict] = []
    for d, c in zip(series.dates, series.close):
        if c is not None:
            out.append({"date": d.isoformat(), "close": c})
    return out[-days:]


def date_range_for_window(window: str) -> tuple[date, date]:
    today = date.today()
    if window == "today":
        return today, today
    if window == "week":
        start = today - timedelta(days=today.weekday())  # Monday
        return start, start + timedelta(days=6)
    if window == "last_week":
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6)
    if window == "all":
        # The full span covering every tab (last week through the upcoming
        # weeks), so the frontend can load once and switch tabs client-side.
        start = today - timedelta(days=today.weekday() + 7)  # last Monday
        next_monday = today + timedelta(days=7 - today.weekday())
        return start, next_monday + timedelta(days=13)
    if window == "upcoming":
        # Future-only: next week plus the week after (two full Mon–Sun weeks).
        # This week's prints live in the "This week" tab, so "Upcoming" never
        # shows reports that are already here.
        next_monday = today + timedelta(days=7 - today.weekday())
        return next_monday, next_monday + timedelta(days=13)
    # default: a rolling 2-week window around today
    return today - timedelta(days=3), today + timedelta(days=11)


def list_themes(db: Session) -> list[dict]:
    universe = load_universe()
    counts = dict(
        db.execute(
            select(ThemeMembership.theme_key, func.count(ThemeMembership.ticker))
            .group_by(ThemeMembership.theme_key)
        ).all()
    )
    labels = dict(
        db.execute(
            select(ThemeMembership.theme_key, ThemeMembership.theme_label)
        ).all()
    )

    out: list[dict] = []
    seen: set[str] = set()
    # Curated themes first, in their configured order.
    for theme in universe.themes:
        out.append(
            {
                "key": theme.key,
                "label": theme.label,
                "ticker_count": counts.get(theme.key, 0),
            }
        )
        seen.add(theme.key)
    # Then sector themes discovered from the whole-market calendar sweep.
    for key in sorted(k for k in counts if k not in seen and k.startswith("sector_")):
        out.append(
            {
                "key": key,
                "label": labels.get(key, key),
                "ticker_count": counts[key],
            }
        )
    return out


def _verdict_for(avg_abs: float | None, expected: float | None) -> str | None:
    if not avg_abs or expected is None:
        return None
    richness = expected / avg_abs
    if richness < 0.85:
        return "cheap"
    if richness > 1.15:
        return "rich"
    return "inline"


def earnings_cards(
    db: Session,
    window: str,
    theme: str | None = None,
    *,
    limit: int | None = None,
) -> tuple[list[dict], bool]:
    """Build calendar cards for a window.

    Returns (cards, has_more). Batches company / implied / theme reads and
    computes reaction summaries once per ticker (not once per event).
    """
    start, end = date_range_for_window(window)

    stmt = (
        select(EarningsEvent)
        .where(EarningsEvent.date >= start, EarningsEvent.date <= end)
        .order_by(EarningsEvent.date.asc())
    )
    if theme:
        stmt = stmt.join(
            ThemeMembership, ThemeMembership.ticker == EarningsEvent.ticker
        ).where(ThemeMembership.theme_key == theme)

    events = db.scalars(stmt).unique().all()

    # De-dup events first (theme join can multiply rows).
    seen_ev: set[tuple[str, date]] = set()
    uniq_events: list[EarningsEvent] = []
    for ev in events:
        key = (ev.ticker.upper(), ev.date)
        if key in seen_ev:
            continue
        seen_ev.add(key)
        uniq_events.append(ev)

    has_more = False
    if limit is not None and len(uniq_events) > limit:
        has_more = True
        uniq_events = uniq_events[:limit]

    tickers = sorted({ev.ticker.upper() for ev in uniq_events})
    if not tickers:
        return [], False

    companies = {
        c.ticker.upper(): c
        for c in db.scalars(select(Company).where(Company.ticker.in_(tickers))).all()
    }
    implied_rows = {
        r.ticker.upper(): r
        for r in db.scalars(
            select(ImpliedMove).where(ImpliedMove.ticker.in_(tickers))
        ).all()
    }
    themes_by: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in db.scalars(
        select(ThemeMembership).where(ThemeMembership.ticker.in_(tickers))
    ).all():
        themes_by[row.ticker.upper()].append(
            {"key": row.theme_key, "label": row.theme_label}
        )

    # Reaction summaries are the expensive bit — once per ticker.
    summary_by: dict[str, object] = {}
    for ticker in tickers:
        series = load_price_series(db, ticker)
        summary_by[ticker] = summarize(compute_reactions(db, ticker, series=series))

    cards: list[dict] = []
    for ev in uniq_events:
        ticker = ev.ticker.upper()
        company = companies.get(ticker)
        summary = summary_by[ticker]
        implied_row = implied_rows.get(ticker)
        expected = implied_row.expected_move_pct if implied_row else None
        avg_abs = summary.avg_abs_move_pct
        cards.append(
            {
                "ticker": ticker,
                "name": company.name if company else None,
                "sector": company.sector if company else None,
                "market_cap": company.market_cap if company else None,
                "date": ev.date.isoformat(),
                "timing": ev.timing,
                "eps_estimate": ev.eps_estimate,
                "eps_actual": ev.eps_actual,
                "reported": ev.date <= date.today() and ev.eps_actual is not None,
                "themes": themes_by.get(ticker, []),
                "implied_move_pct": expected,
                "implied_verdict": _verdict_for(avg_abs, expected),
                "avg_abs_move_pct": avg_abs,
                "up_rate": summary.up_rate,
                "beat_streak": summary.beat_streak,
                "last_move_pct": summary.last_move_pct,
            }
        )
    return cards, has_more


def earnings_watchlist(db: Session, window: str = "today", *, limit: int = 12) -> list[dict]:
    """Light today/upcoming names for the brief — no reaction recompute."""
    start, end = date_range_for_window(window)
    events = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.date >= start, EarningsEvent.date <= end)
        .order_by(EarningsEvent.date.asc())
    ).all()

    seen: set[str] = set()
    tickers: list[str] = []
    event_by: dict[str, EarningsEvent] = {}
    for ev in events:
        t = ev.ticker.upper()
        if t in seen:
            continue
        seen.add(t)
        tickers.append(t)
        event_by[t] = ev
        if len(tickers) >= limit:
            break
    if not tickers:
        return []

    companies = {
        c.ticker.upper(): c
        for c in db.scalars(select(Company).where(Company.ticker.in_(tickers))).all()
    }
    implied_rows = {
        r.ticker.upper(): r
        for r in db.scalars(
            select(ImpliedMove).where(ImpliedMove.ticker.in_(tickers))
        ).all()
    }
    themes_by: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in db.scalars(
        select(ThemeMembership).where(ThemeMembership.ticker.in_(tickers))
    ).all():
        themes_by[row.ticker.upper()].append(
            {"key": row.theme_key, "label": row.theme_label}
        )

    out: list[dict] = []
    for t in tickers:
        ev = event_by[t]
        company = companies.get(t)
        implied = implied_rows.get(t)
        out.append(
            {
                "ticker": t,
                "name": company.name if company else None,
                "timing": ev.timing,
                "implied_move_pct": implied.expected_move_pct if implied else None,
                "themes": themes_by.get(t, []),
            }
        )
    return out


def company_detail(db: Session, ticker: str) -> dict | None:
    ticker = ticker.upper()
    company = db.get(Company, ticker)
    reactions = reaction_payload(db, ticker)
    summary = reactions["summary"]
    if company is None and summary["sample_size"] == 0:
        return None

    realized_abs_moves = [
        abs(e["move_pct"]) for e in reactions["events"] if e["move_pct"] is not None
    ]
    sell_strike_frac = get_settings().paper_sell_strike_em_frac
    implied = implied_payload(
        db, ticker, summary["avg_abs_move_pct"], realized_abs_moves, sell_strike_frac
    )

    spot = implied["underlying_price"] if implied else None
    analyst = analyst_payload(db, ticker, spot)

    next_event = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.ticker == ticker, EarningsEvent.date >= date.today())
        .order_by(EarningsEvent.date.asc())
    ).first()

    price_history = recent_prices(db, ticker)
    playbook = build_playbook(
        summary=summary,
        implied=implied,
        analyst=analyst,
        prices=price_history,
        next_earnings_date=next_event.date.isoformat() if next_event else None,
        next_earnings_timing=next_event.timing if next_event else None,
    )

    return {
        "ticker": ticker,
        "name": company.name if company else None,
        "sector": company.sector if company else None,
        "industry": company.industry if company else None,
        "exchange": company.exchange if company else None,
        "market_cap": company.market_cap if company else None,
        "image": company.image if company else None,
        "themes": shared_themes(db, ticker),
        "next_earnings_date": next_event.date.isoformat() if next_event else None,
        "next_earnings_timing": next_event.timing if next_event else None,
        "implied_move": implied,
        "analyst": analyst,
        "playbook": playbook,
        "price_history": price_history,
        "reactions": reactions,
        "peers": peers_lead_lag(db, ticker),
    }
