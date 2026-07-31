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
from app.services.paper.health import notify_paper_health, run_is_unhealthy

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("app.paper_run")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the paper earnings trader.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview trades without submitting any orders.",
    )
    parser.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send a test Telegram message to verify the bot config, then exit.",
    )
    args = parser.parse_args()

    if args.test_telegram:
        from datetime import datetime

        from app.services.notify import send_telegram, telegram_configured

        if not telegram_configured():
            logger.error(
                "Telegram not configured — set TELEGRAM_BOT_TOKEN and "
                "TELEGRAM_CHAT_ID in .env (or the Render environment)."
            )
            raise SystemExit(1)
        ok = send_telegram(
            f"EarningsFollower test alert — bot is wired up "
            f"({datetime.now():%Y-%m-%d %H:%M})."
        )
        logger.info("Test message %s.", "sent" if ok else "failed to send")
        raise SystemExit(0 if ok else 1)

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

    # Fail the process (and page via Telegram / Render notifyOnFail) when the
    # run is unhealthy. Dry-runs stay exit-0 so local previews aren't alarms.
    if not args.dry_run and run_is_unhealthy(result):
        try:
            notify_paper_health(result)
        except Exception as e:  # noqa: BLE001 - never mask the real failure
            logger.warning("paper health notify failed: %s", e)
        logger.error("Paper run unhealthy — exiting non-zero for cron alerting")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
