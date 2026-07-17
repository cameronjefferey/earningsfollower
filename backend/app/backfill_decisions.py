"""One-off (idempotent) backfill: seed ``trade_decisions`` from existing trades.

The feature/label store (``app.services.paper.decisions``) is populated going
forward by the executor as it scans. This script reconstructs a decision row for
every PaperTrade already on the book so the learning journal isn't blind to
history: each filled/live trade becomes an ``opened`` decision, each canceled one
a ``skipped`` decision (with its recorded reason), features rebuilt from the
stored thesis JSON + typed columns. It then runs the label sync so closed trades
get their realized P&L and multi-horizon underlying moves attached.

Idempotent: a trade that already has a decision row (matched by signal_id) is
skipped, so it's safe to re-run.

    python -m app.backfill_decisions            # apply
    python -m app.backfill_decisions --dry-run  # preview, change nothing
"""

from __future__ import annotations

import argparse
import logging

from app.db.session import SessionLocal, init_db
from app.services.paper.decisions import backfill_from_paper_trades, sync_labels

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("app.backfill_decisions")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill trade_decisions from paper_trades.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without writing to the database.",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        created = backfill_from_paper_trades(db)
        if args.dry_run:
            db.rollback()
            logger.info("[dry-run] would create %d decision(s); nothing written.", created)
        else:
            db.commit()
            labeled = sync_labels(db)
            db.commit()
            logger.info("Created %d decision(s); labeled %d.", created, labeled)
    finally:
        db.close()


if __name__ == "__main__":
    main()
