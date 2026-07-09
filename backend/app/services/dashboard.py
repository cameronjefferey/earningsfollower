from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, EarningsEvent, ImpliedMove, ThemeMembership
from app.services.analyst import analyst_payload
from app.services.implied import implied_payload
from app.services.peers import get_peers, shared_themes
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
    out = []
    for theme in universe.themes:
        n = len(
            db.scalars(
                select(ThemeMembership.ticker).where(
                    ThemeMembership.theme_key == theme.key
                )
            ).all()
        )
        out.append({"key": theme.key, "label": theme.label, "ticker_count": n})
    return out


def earnings_cards(
    db: Session, window: str, theme: str | None = None
) -> list[dict]:
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

    cards: list[dict] = []
    for ev in events:
        reactions = compute_reactions(db, ev.ticker)
        summary = summarize(reactions)
        implied = implied_payload(db, ev.ticker, summary.avg_abs_move_pct)
        company = db.get(Company, ev.ticker)
        cards.append(
            {
                "ticker": ev.ticker,
                "name": company.name if company else None,
                "sector": company.sector if company else None,
                "market_cap": company.market_cap if company else None,
                "date": ev.date.isoformat(),
                "timing": ev.timing,
                "eps_estimate": ev.eps_estimate,
                "eps_actual": ev.eps_actual,
                "reported": ev.date <= date.today() and ev.eps_actual is not None,
                "themes": shared_themes(db, ev.ticker),
                "implied_move_pct": implied["expected_move_pct"] if implied else None,
                "implied_verdict": implied["verdict"] if implied else None,
                "avg_abs_move_pct": summary.avg_abs_move_pct,
                "up_rate": summary.up_rate,
                "beat_streak": summary.beat_streak,
                "last_move_pct": summary.last_move_pct,
            }
        )
    # De-dup by ticker within window (a ticker can match multiple themes on join).
    seen: set[tuple[str, str]] = set()
    deduped = []
    for c in cards:
        key = (c["ticker"], c["date"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped


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
    implied = implied_payload(
        db, ticker, summary["avg_abs_move_pct"], realized_abs_moves
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
