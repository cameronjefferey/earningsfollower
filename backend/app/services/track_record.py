"""Sanitized paper-trading aggregates for the public / Pro track-record page.

No live book, strikes, tickers-in-trade, or account balances.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.services.paper import report as paper_report
from app.services.sample_stats import sample_tier, wilson_low


def _sanitize_bucket(raw: dict) -> list[dict]:
    rows: list[dict] = []
    for key, b in (raw or {}).items():
        n = int(b.get("n") or 0)
        wins = int(b.get("wins") or 0)
        wr = (wins / n) if n else None
        rows.append(
            {
                "key": str(key),
                "n": n,
                "win_rate": round(wr, 3) if wr is not None else None,
                "win_rate_ci_low": wilson_low(wr, n),
                "sample_tier": sample_tier(n),
                # Aggregate P&L only for Pro; guests get nulls via preview strip.
                "total_pnl": round(float(b.get("pnl") or 0.0), 2),
            }
        )
    rows.sort(key=lambda r: (r["n"], r["win_rate"] or 0), reverse=True)
    return rows


def track_record(db: Session, *, preview: bool) -> dict:
    # Skip Alpaca account / live spots - we only need closed-trade aggregates.
    full = paper_report.scorecard(db, include_account=False)
    stats = full.get("stats") or {}
    closed_n = int(stats.get("closed_count") or 0)
    wins = int(stats.get("wins") or 0)
    win_rate = stats.get("win_rate")

    overall = {
        "closed_count": closed_n,
        "wins": wins,
        "win_rate": win_rate,
        "win_rate_ci_low": wilson_low(win_rate, closed_n),
        "sample_tier": sample_tier(closed_n),
        "total_pnl": None if preview else stats.get("total_pnl"),
        "avg_pnl": None if preview else stats.get("avg_pnl"),
    }

    by_strategy = _sanitize_bucket(stats.get("by_strategy") or {})
    if preview:
        # Guests: overall + strategy names/n/win only (no P&L).
        for row in by_strategy:
            row["total_pnl"] = None
        by_strategy = by_strategy[:3]
        note = (
            "Preview - lagged paper-research aggregates. Pro unlocks full strategy "
            "breakdown and P&L totals. Not investment advice."
        )
    else:
        note = (
            "Paper-research scorecard (simulated fills). Historical sample stats, "
            "not a promise of future results. Not investment advice."
        )

    return {
        "generated_at": full.get("generated_at") or datetime.utcnow().isoformat(),
        "preview": preview,
        "preview_note": note if preview else None,
        "overall": overall,
        "by_strategy": by_strategy,
        "window_note": "All closed paper trades in the journal to date.",
    }
