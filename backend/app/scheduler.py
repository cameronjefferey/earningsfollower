from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.session import session_scope
from app.services.ingest import refresh_all

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _daily_job() -> None:
    logger.info("Scheduled daily refresh starting.")
    try:
        with session_scope() as db:
            result = refresh_all(db)
        logger.info("Scheduled refresh complete: %s", result)
    except Exception:
        logger.exception("Scheduled refresh failed.")


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="America/New_York")
    # Refresh after the US market close on weekdays so the day's prints land.
    _scheduler.add_job(
        _daily_job,
        CronTrigger(day_of_week="mon-fri", hour=18, minute=0),
        id="daily_refresh",
        replace_existing=True,
    )
    _scheduler.start()


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
