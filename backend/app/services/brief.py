"""Morning brief - the paid daily habit.

One focus setup, a short board underneath, what changed, and who prints today.
Not a directory of other pages.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services import dashboard, digest as digest_svc, ranked_setups


def _board_quality(setups: list[dict]) -> dict[str, Any]:
    """An honest read on how strong today's board is - not fake P&L.

    Breadth (distinct drivers), sample strength (tier mix + median Wilson floor),
    and the best available edge. Lets the brief say 'quiet, thin day' vs 'broad,
    solid day' without pretending to a track record we don't have here.
    """
    if not setups:
        return {
            "count": 0,
            "solid": 0,
            "ok": 0,
            "thin": 0,
            "distinct_drivers": 0,
            "median_win_floor": None,
            "best_edge_pct": None,
            "top_conviction": None,
        }

    tiers = {"solid": 0, "ok": 0, "thin": 0}
    drivers: set[str] = set()
    floors: list[float] = []
    edges: list[float] = []
    convictions: list[int] = []
    for s in setups:
        t = s.get("sample_tier")
        if t in tiers:
            tiers[t] += 1
        drivers.add(str(s.get("trigger") or s.get("ticker")))
        fl = s.get("win_rate_ci_low")
        if isinstance(fl, (int, float)):
            floors.append(fl)
        ed = s.get("edge_pct")
        if isinstance(ed, (int, float)):
            edges.append(abs(ed))
        cv = s.get("conviction")
        if isinstance(cv, int):
            convictions.append(cv)

    return {
        "count": len(setups),
        "solid": tiers["solid"],
        "ok": tiers["ok"],
        "thin": tiers["thin"],
        "distinct_drivers": len(drivers),
        "median_win_floor": round(statistics.median(floors), 4) if floors else None,
        "best_edge_pct": round(max(edges), 4) if edges else None,
        "top_conviction": max(convictions) if convictions else None,
    }


def morning_brief(db: Session, *, preview: bool = False) -> dict[str, Any]:
    dig = digest_svc.get_today(db, preview=preview)
    ranked = ranked_setups.ranked_setups(
        db, limit=5 if not preview else 3, preview=preview
    )
    setups = list(ranked.get("setups") or [])
    focus = ranked.get("focus") or (setups[0] if setups else None)

    watch = dashboard.earnings_watchlist(db, "today", limit=8)
    if preview:
        for c in watch:
            c["implied_move_pct"] = None

    bullets = list((dig.get("bullets") or []))
    # Keep the change log short on the brief - this isn't the digest archive.
    if preview:
        bullets = bullets[:2]
    else:
        bullets = bullets[:5]

    note = None
    if preview:
        note = (
            "Calendar stays free. The ranked lean, conviction, and plan are Pro - "
            "preview numbers are sample data, not today's live book."
        )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "as_of": date.today().isoformat(),
        "preview": preview,
        "preview_note": note,
        "focus": focus,
        "board_quality": _board_quality(setups),
        "digest": {
            "date": dig.get("date"),
            "bullets": bullets,
            "updated_at": dig.get("updated_at"),
        },
        "ranked": setups,
        "today_earnings": watch,
        "updated_at": ranked.get("updated_at") or dig.get("updated_at"),
    }
