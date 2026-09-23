"""The public site shows the same names the live book will consider.

$10B+ market cap, and not an industry the earnings book already skips.
Missing market cap stays off the site: we only list names we know are big.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company


def _skip_industries(settings) -> set[str]:
    skip = getattr(settings, "paper_earnings_skip_industry_set", None)
    if isinstance(skip, set):
        return skip
    raw = getattr(settings, "paper_earnings_skip_industries", "") or ""
    return {s.strip() for s in str(raw).split(",") if s.strip()}


def universe_tickers(db: Session, tickers: list[str], settings) -> set[str]:
    """Tickers that clear the site's size and industry bar."""
    names = sorted({(t or "").upper() for t in tickers if t})
    if not names:
        return set()
    rows = db.scalars(select(Company).where(Company.ticker.in_(names))).all()
    by = {c.ticker.upper(): c for c in rows}
    min_cap = float(getattr(settings, "calendar_min_market_cap", 0) or 0)
    skip = _skip_industries(settings)
    ok: set[str] = set()
    for ticker in names:
        company = by.get(ticker)
        cap = getattr(company, "market_cap", None) if company else None
        if min_cap and (cap is None or cap < min_cap):
            continue
        industry = (getattr(company, "industry", None) or "") if company else ""
        if industry and industry in skip:
            continue
        ok.add(ticker)
    return ok
