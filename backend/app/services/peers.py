from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PeerLink, ThemeMembership

# Default cap when a caller wants "closest peers" rather than the whole theme.
# FMP stock-peers are typically a short list; theme co-members can be dozens.
DEFAULT_PEER_LIMIT = 8


def shared_themes(db: Session, ticker: str) -> list[dict[str, str]]:
    rows = db.scalars(
        select(ThemeMembership).where(ThemeMembership.ticker == ticker.upper())
    ).all()
    return [{"key": r.theme_key, "label": r.theme_label} for r in rows]


def get_peers(
    db: Session,
    ticker: str,
    *,
    limit: int | None = None,
) -> list[str]:
    """Peers ranked closest-first.

    Order:
      1. Explicit FMP peer links (direct comps)
      2. Theme co-members by shared curated themes, then sector themes

    Pass ``limit`` (e.g. ``DEFAULT_PEER_LIMIT``) so a single print can't fan
    out across an entire industry theme.
    """
    ticker = ticker.upper()

    explicit: list[str] = []
    seen: set[str] = set()
    for link in db.scalars(
        select(PeerLink).where(PeerLink.ticker == ticker).order_by(PeerLink.peer)
    ):
        if link.peer != ticker and link.peer not in seen:
            explicit.append(link.peer)
            seen.add(link.peer)
    for link in db.scalars(
        select(PeerLink).where(PeerLink.peer == ticker).order_by(PeerLink.ticker)
    ):
        if link.ticker != ticker and link.ticker not in seen:
            explicit.append(link.ticker)
            seen.add(link.ticker)

    my_themes = {
        r.theme_key
        for r in db.scalars(
            select(ThemeMembership).where(ThemeMembership.ticker == ticker)
        )
    }
    if not my_themes:
        return explicit[:limit] if limit is not None else explicit

    co_rows = db.scalars(
        select(ThemeMembership).where(ThemeMembership.theme_key.in_(my_themes))
    ).all()

    peer_shared: dict[str, set[str]] = {}
    for row in co_rows:
        if row.ticker == ticker or row.ticker in seen:
            continue
        peer_shared.setdefault(row.ticker, set()).add(row.theme_key)

    def _theme_score(peer: str) -> tuple:
        shared = peer_shared[peer]
        curated = sum(1 for t in shared if not t.startswith("sector_"))
        sector = sum(1 for t in shared if t.startswith("sector_"))
        # More curated overlap wins; sector-only buckets rank last.
        return (-curated, -sector, peer)

    themed = sorted(peer_shared.keys(), key=_theme_score)
    ranked = explicit + themed
    if limit is not None:
        return ranked[: max(limit, 0)]
    return ranked
