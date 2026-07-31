"""CLI entry point for the paper earnings trader.

Examples:
    python -m app.paper_run            # reconcile, manage exits, open new trades
    python -m app.paper_run --dry-run  # preview entries/exits, submit nothing
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime

from app.db.session import SessionLocal, init_db
from app.services.job_runs import record_job_run
from app.services.paper.executor import run
from app.services.paper.health import (
    collect_anomalies,
    notify_anomalies,
    notify_paper_health,
    paper_heartbeat_anomalies,
    run_is_unhealthy,
)

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
    started = datetime.utcnow()
    try:
        # Catch missed prior crons before this run does any work.
        if not args.dry_run:
            try:
                hb = paper_heartbeat_anomalies(db)
                if hb:
                    notify_anomalies(
                        title="earningsfollower — paper heartbeat stale",
                        anomalies=hb,
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning("heartbeat check failed: %s", e)

        result = run(db, dry_run=args.dry_run)
        # Dry-run must never persist: discard any preview rows that were flushed.
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
            try:
                record_job_run(db, job="paper", started_at=started, result=result)
            except Exception as e:  # noqa: BLE001
                logger.warning("failed to persist paper job run: %s", e)
    finally:
        db.close()
    logger.info("Paper run result:\n%s", json.dumps(result, indent=2, default=str))

    # Fail the process (and page via Telegram / Render notifyOnFail) when the
    # run is unhealthy. Dry-runs stay exit-0 so local previews aren't alarms.
    if not args.dry_run:
        anomalies = collect_anomalies(result)
        if run_is_unhealthy(result, anomalies):
            try:
                notify_paper_health(result)
            except Exception as e:  # noqa: BLE001 - never mask the real failure
                logger.warning("paper health notify failed: %s", e)
            logger.error(
                "Paper run unhealthy — exiting non-zero: %s",
                "; ".join(anomalies),
            )
            raise SystemExit(1)


if __name__ == "__main__":
    main()
