"""Wave receipts: how recently resolved waves actually played out.

The Waves board is a forecast; receipts are the proof. For every name that
already reported and had >= 2 themed peers print in the fortnight before it,
we measure what the stock actually did from the first peer print to the close
before its own report - the exact window the founder's ORCL trade lived in.

Unselected on purpose: every qualifying wave in the window is scored, winners
and losers alike, so the aggregate is honest rather than a highlight reel.
"""

from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, EarningsEvent
from app.services.peers import get_peers
from app.services.prices import load_price_series
from app.services.reactions import compute_reactions
from app.services.waves import (
    MAX_PEERS_PER_TRIGGER,
    MAX_TRIGGERS_PER_TARGET,
    MIN_PEERS_PER_TARGET,
    RIP_MOVE_PCT,
)

logger = logging.getLogger(__name__)

DAYS_BACK = 30
RECENT_DAYS = 14  # match the board's default "peer reported within" window
MAX_RECEIPTS = 20


def _round(v: float | None) -> float | None:
    return round(v, 4) if v is not None else None


def summarize_receipts(receipts: list[dict]) -> dict:
    """Aggregate honesty line: how often riding the wave direction was right."""
    scored = [r for r in receipts if r.get("actual_runup_pct") is not None]
    followed = [r for r in scored if r.get("followed")]
    # Directional edge: the run-up you'd capture trading in the wave's direction.
    edges = [
        r["actual_runup_pct"] * (1 if r["direction"] == "bullish" else -1)
        for r in scored
    ]
    best = max(
        scored,
        key=lambda r: r["actual_runup_pct"] * (1 if r["direction"] == "bullish" else -1),
        default=None,
    )
    return {
        "count": len(scored),
        "followed": len(followed),
        "follow_rate": round(len(followed) / len(scored), 3) if scored else None,
        "avg_edge_pct": _round(statistics.fmean(edges)) if edges else None,
        "best": (
            {
                "target": best["target"],
                "direction": best["direction"],
                "actual_runup_pct": best["actual_runup_pct"],
                "target_report_date": best["target_report_date"],
            }
            if best
            else None
        ),
    }


def receipts_proof_line(payload: dict | None, *, min_count: int = 5) -> str | None:
    """One honest sentence for emails / banners; None when the sample is thin."""
    if not payload:
        return None
    s = payload.get("summary") or {}
    n = int(s.get("count") or 0)
    if n < min_count or s.get("follow_rate") is None:
        return None
    avg = s.get("avg_edge_pct")
    avg_part = ""
    if avg is not None:
        sign = "+" if avg >= 0 else ""
        avg_part = f", avg {sign}{avg * 100:.1f}% into the print"
    return (
        f"Receipts from the last {payload.get('days_back', DAYS_BACK)} days: "
        f"{n} waves resolved; riding the wave direction was right "
        f"{s.get('followed', 0)} of {n}{avg_part}. Winners and losers both counted."
    )


def compute_wave_receipts(
    db: Session,
    *,
    days_back: int = DAYS_BACK,
    recent_days: int = RECENT_DAYS,
    max_receipts: int = MAX_RECEIPTS,
) -> dict:
    """Score every wave that resolved in the last ``days_back`` days."""
    today = date.today()
    start = today - timedelta(days=days_back)

    resolved = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.date >= start, EarningsEvent.date < today)
        .order_by(EarningsEvent.date.desc())
    ).all()
    if not resolved:
        return _payload([], days_back, recent_days)

    # One receipt per ticker: its most recent resolved report in the window.
    target_events: dict[str, EarningsEvent] = {}
    for ev in resolved:
        target_events.setdefault(ev.ticker, ev)

    # All prints that could have seeded a wave into one of those reports.
    prior = db.scalars(
        select(EarningsEvent)
        .where(
            EarningsEvent.date >= start - timedelta(days=recent_days),
            EarningsEvent.date < today,
        )
        .order_by(EarningsEvent.date.asc())
    ).all()
    events_by_ticker: dict[str, list[EarningsEvent]] = {}
    for ev in prior:
        events_by_ticker.setdefault(ev.ticker, []).append(ev)

    reactions_cache: dict[str, dict[date, float | None]] = {}

    def _move(ticker: str, on: date) -> float | None:
        if ticker not in reactions_cache:
            # Reaction dates serialize as ISO strings; re-key by real dates.
            reactions_cache[ticker] = {
                date.fromisoformat(r.date): r.move_pct
                for r in compute_reactions(db, ticker)
            }
        return reactions_cache[ticker].get(on)

    receipts: list[dict] = []
    for target, target_event in target_events.items():
        if len(receipts) >= max_receipts:
            break
        window_start = target_event.date - timedelta(days=recent_days)

        peer_prints: list[tuple[str, EarningsEvent]] = []
        for peer in get_peers(db, target, limit=MAX_PEERS_PER_TRIGGER):
            for ev in events_by_ticker.get(peer, []):
                if window_start <= ev.date < target_event.date:
                    peer_prints.append((peer, ev))
                    break  # one print per peer is the wave seed
        if len(peer_prints) < MIN_PEERS_PER_TARGET:
            continue

        peer_prints.sort(key=lambda pe: pe[1].date)
        first_peer_date = peer_prints[0][1].date

        series = load_price_series(db, target)
        start_idx = series.index_on_or_after(first_peer_date)
        end_idx = series.index_strictly_before(target_event.date)
        if start_idx is None or end_idx is None or end_idx <= start_idx:
            continue
        start_close = series.close[start_idx]
        end_close = series.close[end_idx]
        if not start_close or not end_close:
            continue
        runup = end_close / start_close - 1.0

        peers = []
        moves: list[float] = []
        ripped = 0
        for peer, ev in peer_prints[:MAX_TRIGGERS_PER_TARGET]:
            move = _move(peer, ev.date)
            peers.append(
                {
                    "ticker": peer,
                    "report_date": ev.date.isoformat(),
                    "move_pct": _round(move),
                }
            )
            if move is not None:
                moves.append(move)
                if move >= RIP_MOVE_PCT:
                    ripped += 1
        # A wave has a direction; without any peer moves there's no story to score.
        if not moves:
            continue
        direction = "bullish" if statistics.fmean(moves) >= 0 else "bearish"
        followed = runup > 0 if direction == "bullish" else runup < 0

        receipts.append(
            {
                "target": target,
                "target_name": _name(db, target),
                "target_report_date": target_event.date.isoformat(),
                "wave_start_date": first_peer_date.isoformat(),
                "peers": peers,
                "peer_count": len(peer_prints),
                "ripped_count": ripped,
                "direction": direction,
                "actual_runup_pct": _round(runup),
                "followed": followed,
            }
        )

    return _payload(receipts, days_back, recent_days)


def _payload(receipts: list[dict], days_back: int, recent_days: int) -> dict:
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "days_back": days_back,
        "recent_days": recent_days,
        "count": len(receipts),
        "summary": summarize_receipts(receipts),
        "receipts": receipts,
    }


def _name(db: Session, ticker: str) -> str | None:
    company = db.get(Company, ticker.upper())
    return company.name if company else None
