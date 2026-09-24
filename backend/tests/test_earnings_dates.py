"""A moved earnings date replaces the old unreported row."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, EarningsEvent  # noqa: E402
from app.services.ingest import _drop_abandoned_earnings, kept_open_dates  # noqa: E402


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_drop_abandoned_keeps_the_print_and_the_reported_history():
    db = _session()
    db.add_all(
        [
            EarningsEvent(ticker="MU", date=date(2026, 9, 23), timing="amc", eps_actual=None),
            EarningsEvent(ticker="MU", date=date(2026, 9, 29), timing="unknown", eps_actual=None),
            EarningsEvent(ticker="MU", date=date(2026, 9, 30), timing="amc", eps_actual=None),
            EarningsEvent(ticker="MU", date=date(2026, 6, 24), timing="amc", eps_actual=25.11),
            EarningsEvent(ticker="JBL", date=date(2026, 9, 24), timing="unknown", eps_actual=None),
        ]
    )
    db.commit()

    dropped = _drop_abandoned_earnings(db, "MU", {date(2026, 9, 30), date(2026, 6, 24)})
    db.commit()

    left = db.scalars(select(EarningsEvent).order_by(EarningsEvent.ticker, EarningsEvent.date)).all()
    assert dropped == 2
    assert [(e.ticker, e.date) for e in left] == [
        ("JBL", date(2026, 9, 24)),
        ("MU", date(2026, 6, 24)),
        ("MU", date(2026, 9, 30)),
    ]


def test_yahoo_picks_the_print_when_the_calendar_moved():
    stored = {
        date(2026, 9, 22),
        date(2026, 9, 23),
        date(2026, 9, 29),
        date(2026, 9, 30),
    }
    assert kept_open_dates(stored, {date(2026, 9, 30)}, {date(2026, 9, 30)}) == {
        date(2026, 9, 30)
    }


def test_single_matching_date_is_left_alone():
    assert kept_open_dates({date(2026, 9, 24)}, {date(2026, 9, 24)}, None) == {
        date(2026, 9, 24)
    }
