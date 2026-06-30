"""One-off backfill: re-derive `max_risk` for existing paper trades.

Older rows stored a `max_risk` modeled off the mid credit at record time, which
the real fill then diverged from (the displayed max loss no longer matched the
credit the card showed). This recomputes every trade's max loss from its booked
`entry_credit` using the same logic the executor now applies on fill, so the
scorecard's max-loss (and the reward/risk it implies) is accurate everywhere.

    python -m app.backfill_max_risk            # apply the fix
    python -m app.backfill_max_risk --dry-run  # preview, change nothing
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import select

from app.db.models import PaperTrade
from app.db.session import SessionLocal, init_db
from app.services.paper.risk import defined_risk_max_loss

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("app.backfill_max_risk")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute max_risk for paper trades.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to the database.",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    changed = 0
    try:
        trades = db.scalars(select(PaperTrade)).all()
        for t in trades:
            before = t.max_risk
            after = defined_risk_max_loss(t.strategy, t.width, t.entry_credit, t.contracts)
            if after is None or after == before:
                continue
            t.max_risk = after
            changed += 1
            logger.info(
                "%s %s: max_risk %s -> %s (credit %s, width %s, x%s)",
                t.signal_id, t.ticker, before, after,
                t.entry_credit, t.width, t.contracts,
            )
        if args.dry_run:
            db.rollback()
            logger.info("[dry-run] %d/%d trades would change; nothing written.", changed, len(trades))
        else:
            db.commit()
            logger.info("Updated %d/%d trades.", changed, len(trades))
    finally:
        db.close()


if __name__ == "__main__":
    main()
