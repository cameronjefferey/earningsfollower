from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import AnalystSnapshot


def analyst_payload(db: Session, ticker: str, spot: float | None) -> dict | None:
    row = db.get(AnalystSnapshot, ticker.upper())
    if row is None:
        return None

    ratings = {
        "strong_buy": row.strong_buy or 0,
        "buy": row.buy or 0,
        "hold": row.hold or 0,
        "sell": row.sell or 0,
        "strong_sell": row.strong_sell or 0,
    }
    total = sum(ratings.values())
    bullish = ratings["strong_buy"] + ratings["buy"]

    upside = None
    if spot and row.price_target:
        upside = round(row.price_target / spot - 1.0, 4)

    # Simple revision trend: more bullish analysts than ~3 months ago?
    trend = None
    if row.prev_bullish is not None:
        if bullish > row.prev_bullish:
            trend = "improving"
        elif bullish < row.prev_bullish:
            trend = "deteriorating"
        else:
            trend = "stable"

    if total == 0 and row.price_target is None:
        return None

    return {
        "price_target": row.price_target,
        "price_target_high": row.price_target_high,
        "price_target_low": row.price_target_low,
        "upside_pct": upside,
        "ratings": ratings,
        "ratings_total": total,
        "bullish_pct": round(bullish / total, 3) if total else None,
        "trend": trend,
        "eps_estimate_next": row.eps_estimate_next,
        "revenue_estimate_next": row.revenue_estimate_next,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
