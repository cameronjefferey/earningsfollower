from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.db.session import init_db
from app.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger("earningsfollower")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialized.")
    if settings.enable_scheduler:
        start_scheduler()
        logger.info("Daily refresh scheduler started.")
    yield
    shutdown_scheduler()


app = FastAPI(
    title="earningsfollower API",
    version="0.1.0",
    description="Earnings intelligence: calendar, reaction stats, implied move, peer waves.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Allow any Render-hosted frontend (*.onrender.com) plus configured origins,
    # so the deployed UI works without hardcoding its exact subdomain.
    allow_origin_regex=r"https://([a-z0-9-]+\.)*onrender\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
