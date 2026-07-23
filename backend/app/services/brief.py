"""Morning brief — the paid daily habit.

One focus setup, a short board underneath, what changed, and who prints today.
Not a directory of other pages.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services import dashboard, digest as digest_svc, ranked_setups


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
    # Keep the change log short on the brief — this isn't the digest archive.
    if preview:
        bullets = bullets[:2]
    else:
        bullets = bullets[:5]

    note = None
    if preview:
        note = (
            "Free users see who prints. Pro tells you what to lean on — "
            "one focus setup with action, watch, and drop-if for the session."
        )

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "as_of": date.today().isoformat(),
        "preview": preview,
        "preview_note": note,
        "focus": focus,
        "digest": {
            "date": dig.get("date"),
            "bullets": bullets,
            "updated_at": dig.get("updated_at"),
        },
        "ranked": setups,
        "today_earnings": watch,
        "updated_at": ranked.get("updated_at") or dig.get("updated_at"),
    }
