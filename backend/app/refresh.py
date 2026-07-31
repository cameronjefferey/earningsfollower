"""CLI to populate / refresh the local database.

Examples:
    python -m app.refresh                 # full universe refresh
    python -m app.refresh --no-peers      # skip FMP peer expansion
    python -m app.refresh --tickers NVDA,SNOW,ORCL,AMD,CRM   # quick subset
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from app.clients.fmp import FMPClient
from app.config import get_settings
from app.db.session import init_db, session_scope
from app.services.ingest import _build_universe, ingest_company, refresh_all
from app.services.job_runs import record_job_run
from app.services.paper.health import (
    notify_refresh_health,
    refresh_is_unhealthy,
    refresh_stale_anomaly,
    notify_anomalies,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
logger = logging.getLogger("app.refresh")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh earningsfollower data.")
    parser.add_argument(
        "--tickers",
        help="Comma-separated subset to ingest (still builds theme memberships).",
    )
    parser.add_argument(
        "--no-peers",
        action="store_true",
        help="Skip FMP peer expansion (saves API calls).",
    )
    args = parser.parse_args()

    init_db()
    settings = get_settings()
    started = datetime.utcnow()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        with session_scope() as db, FMPClient() as fmp:
            _build_universe(db, fmp, expand_peers=not args.no_peers)
            for t in tickers:
                logger.info("Ingesting %s", t)
                ingest_company(db, fmp, t, history_years=settings.history_years)
                db.commit()
        logger.info("Done: ingested %d tickers", len(tickers))
        return

    with session_scope() as db:
        # Missed daily refresh?
        try:
            stale = refresh_stale_anomaly(db)
            if stale:
                notify_anomalies(
                    title="earningsfollower — refresh heartbeat stale",
                    anomalies=stale,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("refresh heartbeat check failed: %s", e)

        result = refresh_all(db, expand_peers=None if not args.no_peers else False)
        try:
            record_job_run(db, job="refresh", started_at=started, result=result)
        except Exception as e:  # noqa: BLE001
            logger.warning("failed to persist refresh job run: %s", e)

    logger.info("Refresh result: %s", result)

    if refresh_is_unhealthy(result):
        try:
            notify_refresh_health(result)
        except Exception as e:  # noqa: BLE001
            logger.warning("refresh health notify failed: %s", e)
        logger.error("Refresh unhealthy — exiting non-zero")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
