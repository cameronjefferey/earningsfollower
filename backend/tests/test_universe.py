"""Public site universe: $10B+, known cap, skip application software."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, Company  # noqa: E402
from app.services.universe import universe_tickers  # noqa: E402


class _Settings:
    calendar_min_market_cap = 10_000_000_000.0
    paper_earnings_skip_industries = "Software - Application"


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_universe_keeps_large_caps_and_drops_the_leak():
    db = _session()
    db.add_all(
        [
            Company(ticker="NVDA", market_cap=3_000_000_000_000, industry="Semiconductors"),
            Company(ticker="SHOP", market_cap=80_000_000_000, industry="Software - Application"),
            Company(ticker="MID", market_cap=4_000_000_000, industry="Banks"),
            Company(ticker="UNK", market_cap=20_000_000_000, industry=None),
            Company(ticker="NOCAP", market_cap=None, industry="Banks"),
        ]
    )
    db.commit()

    kept = universe_tickers(
        db, ["NVDA", "SHOP", "MID", "UNK", "NOCAP", "GONE"], _Settings()
    )
    assert kept == {"NVDA", "UNK"}
