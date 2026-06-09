from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ImpliedMove

MIN_EDGE_SAMPLE = 4


def compute_vol_edge(
    expected_move_pct: float | None, realized_abs_moves: list[float]
) -> dict:
    """Has the stock historically moved MORE or LESS than the move now priced in?

    `exceed_rate` = share of past prints whose absolute move was at least as
    large as the current implied move. A low exceed rate means the market is
    pricing a bigger move than this name usually makes (premium-seller edge);
    a high rate favors premium buyers.
    """
    if expected_move_pct is None or len(realized_abs_moves) < MIN_EDGE_SAMPLE:
        return {"exceed_rate": None, "edge_verdict": None, "edge_sample": len(realized_abs_moves)}

    exceeded = sum(1 for m in realized_abs_moves if m >= expected_move_pct)
    rate = exceeded / len(realized_abs_moves)
    if rate < 0.40:
        verdict = "seller_edge"  # realized rarely reaches the implied move
    elif rate > 0.60:
        verdict = "buyer_edge"  # realized often exceeds the implied move
    else:
        verdict = "balanced"
    return {
        "exceed_rate": round(rate, 3),
        "edge_verdict": verdict,
        "edge_sample": len(realized_abs_moves),
    }


def implied_payload(
    db: Session,
    ticker: str,
    avg_abs_move_pct: float | None,
    realized_abs_moves: list[float] | None = None,
) -> dict | None:
    """Stored implied move plus context vs. the stock's historical moves.

    `richness` = implied expected move / historical average absolute move.
      < 0.85  -> options look cheap relative to history
      0.85-1.15 -> roughly in line
      > 1.15  -> options look rich (market expects a bigger-than-usual move)
    """
    row = db.get(ImpliedMove, ticker.upper())
    if row is None or row.expected_move_pct is None:
        return None

    richness = None
    verdict = None
    if avg_abs_move_pct:
        richness = round(row.expected_move_pct / avg_abs_move_pct, 3)
        if richness < 0.85:
            verdict = "cheap"
        elif richness > 1.15:
            verdict = "rich"
        else:
            verdict = "inline"

    edge = compute_vol_edge(row.expected_move_pct, realized_abs_moves or [])

    return {
        "expected_move_pct": row.expected_move_pct,
        "expiry": row.expiry.isoformat() if row.expiry else None,
        "underlying_price": row.underlying_price,
        "atm_strike": row.atm_strike,
        "straddle_price": row.straddle_price,
        "historical_avg_abs_move_pct": avg_abs_move_pct,
        "richness": richness,
        "verdict": verdict,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        **edge,
    }
