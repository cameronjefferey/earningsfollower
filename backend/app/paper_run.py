"""CLI entry point for the paper earnings trader.

Examples:
    python -m app.paper_run            # reconcile, manage exits, open new trades
    python -m app.paper_run --dry-run  # preview entries/exits, submit nothing
"""

from __future__ import annotations

import argparse
import json
import logging

from app.db.session import SessionLocal, init_db
from app.services.paper.executor import run

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("app.paper_run")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the paper earnings trader.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview trades without submitting any orders.",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        result = run(db, dry_run=args.dry_run)
        # Dry-run must never persist: discard any preview rows that were flushed.
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    finally:
        db.close()
    logger.info("Paper run result:\n%s", json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
