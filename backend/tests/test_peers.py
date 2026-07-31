"""Closest-peer ranking: FMP links first, then curated theme overlap, capped."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, Company, PeerLink, ThemeMembership  # noqa: E402
from app.services.peers import get_peers  # noqa: E402


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _company(db, ticker: str) -> None:
    db.add(Company(ticker=ticker, name=ticker))


def _theme(db, ticker: str, key: str, label: str) -> None:
    db.add(
        ThemeMembership(
            ticker=ticker, theme_key=key, theme_label=label, is_seed=True
        )
    )


def test_get_peers_ranks_explicit_then_curated_and_respects_limit():
    db = _session()
    for t in ("ABBV", "LLY", "JNJ", "VRTX", "MRK", "PFE", "BMY", "AMGN", "GILD"):
        _company(db, t)

    # Direct comps
    db.add(PeerLink(ticker="ABBV", peer="LLY"))
    db.add(PeerLink(ticker="ABBV", peer="JNJ"))

    # Huge sector bucket (the fan-out source)
    for t in ("ABBV", "LLY", "JNJ", "VRTX", "MRK", "PFE", "BMY", "AMGN", "GILD"):
        _theme(db, t, "sector_healthcare", "Healthcare")

    # Tighter curated theme shared with only a couple names
    for t in ("ABBV", "MRK", "PFE"):
        _theme(db, t, "big_pharma", "Big Pharma")

    db.commit()

    ranked = get_peers(db, "ABBV", limit=5)
    assert ranked[:2] == ["JNJ", "LLY"]  # explicit, alpha within links
    # Curated overlap (MRK/PFE) before sector-only names
    assert "MRK" in ranked
    assert "PFE" in ranked
    assert len(ranked) == 5
    # Cap keeps the rest of the sector bucket out
    assert "GILD" not in ranked
