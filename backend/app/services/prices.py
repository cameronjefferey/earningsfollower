from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PriceBar


@dataclass
class PriceSeries:
    """Sorted daily price series with fast date -> index lookup."""

    dates: list[date]
    open: list[float | None]
    close: list[float | None]

    def __len__(self) -> int:
        return len(self.dates)

    def index_on_or_after(self, d: date) -> int | None:
        i = bisect.bisect_left(self.dates, d)
        return i if i < len(self.dates) else None

    def index_on_or_before(self, d: date) -> int | None:
        i = bisect.bisect_right(self.dates, d) - 1
        return i if i >= 0 else None

    def index_strictly_before(self, d: date) -> int | None:
        i = bisect.bisect_left(self.dates, d) - 1
        return i if i >= 0 else None


def load_price_series(db: Session, ticker: str) -> PriceSeries:
    rows = db.scalars(
        select(PriceBar)
        .where(PriceBar.ticker == ticker.upper())
        .order_by(PriceBar.date.asc())
    ).all()
    return PriceSeries(
        dates=[r.date for r in rows],
        open=[r.open for r in rows],
        close=[r.close for r in rows],
    )
