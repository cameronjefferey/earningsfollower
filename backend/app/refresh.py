"""CLI to populate / refresh the local database.

Examples:
    python -m app.refresh                 # full universe refresh
    python -m app.refresh --no-peers      # skip FMP peer expansion
    python -m app.refresh --tickers NVDA,SNOW,ORCL,AMD,CRM   # quick subset
"""

from __future__ import annotations

import argparse
import logging

from app.clients.fmp import FMPClient
from app.config import get_settings
from app.db.session import init_db, session_scope
from app.services.ingest import _build_universe, ingest_company, refresh_all

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
        result = refresh_all(db, expand_peers=None if not args.no_peers else False)
    logger.info("Refresh result: %s", result)


if __name__ == "__main__":
    main()
