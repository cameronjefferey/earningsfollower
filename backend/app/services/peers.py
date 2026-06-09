from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PeerLink, ThemeMembership


def shared_themes(db: Session, ticker: str) -> list[dict[str, str]]:
    rows = db.scalars(
        select(ThemeMembership).where(ThemeMembership.ticker == ticker.upper())
    ).all()
    return [{"key": r.theme_key, "label": r.theme_label} for r in rows]


def get_peers(db: Session, ticker: str) -> set[str]:
    """Peers = explicit FMP peer links + tickers sharing any theme."""
    ticker = ticker.upper()
    peers: set[str] = set()

    for link in db.scalars(select(PeerLink).where(PeerLink.ticker == ticker)):
        peers.add(link.peer)
    for link in db.scalars(select(PeerLink).where(PeerLink.peer == ticker)):
        peers.add(link.ticker)

    theme_keys = [
        r.theme_key
        for r in db.scalars(
            select(ThemeMembership).where(ThemeMembership.ticker == ticker)
        )
    ]
    if theme_keys:
        co_members = db.scalars(
            select(ThemeMembership.ticker).where(
                ThemeMembership.theme_key.in_(theme_keys)
            )
        ).all()
        peers.update(co_members)

    peers.discard(ticker)
    return peers
