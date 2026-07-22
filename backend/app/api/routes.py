from __future__ import annotations

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Admin, OptionalAuth, PaidAccess, Subscriber
from app import cache as response_cache
from app.config import Settings, get_settings
from app.db.models import RefreshLog
from app.db.session import get_db, session_scope
from app.research.attribution import attribution_report
from app.research.progress import progress_series
from app.services import dashboard, drift, reddit_sentiment, waves
from app.services.ingest import refresh_all
from app.services.paper import report as paper_report
from app.services.paper.calibration import calibration_state
from app.services.paper.narrator import build_narrative

router = APIRouter()

WINDOWS = {"all", "today", "week", "last_week", "upcoming", "around"}

# How much unpaid visitors see — enough to sell the product, not the full book.
_PREVIEW_REACTION_EVENTS = 8
_PREVIEW_PRICE_POINTS = 90
_PREVIEW_PEERS = 3
_PREVIEW_WAVES = 4
_PREVIEW_DRIFT = 3
_PREVIEW_REDDIT = 5


def _is_admin(caller: OptionalAuth, settings: Settings) -> bool:
    return bool(caller and caller.is_admin(settings))


def _preview_company(detail: dict) -> dict:
    reactions = detail.get("reactions") or {}
    events = list(reactions.get("events") or [])[:_PREVIEW_REACTION_EVENTS]
    prices = list(detail.get("price_history") or [])[-_PREVIEW_PRICE_POINTS:]
    peers = list(detail.get("peers") or [])[:_PREVIEW_PEERS]
    return {
        **detail,
        "playbook": None,
        "price_history": prices,
        "peers": peers,
        "reactions": {**reactions, "events": events},
        "preview": True,
        "preview_note": (
            "Preview — full reaction history, peer waves, and live implied-move "
            "context unlock with Pro."
        ),
    }

@router.get("/themes", tags=["reference"])
def get_themes(db: Session = Depends(get_db)) -> list[dict]:
    # Public (freemium): calendar filters need theme list.
    return dashboard.list_themes(db)


@router.get("/earnings", tags=["earnings"])
def get_earnings(
    window: str = Query("week", description="all|today|week|last_week|upcoming|around"),
    theme: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    if window not in WINDOWS:
        raise HTTPException(400, f"window must be one of {sorted(WINDOWS)}")
    start, end = dashboard.date_range_for_window(window)
    # Day is part of the key so Mon–Sun windows roll correctly at midnight.
    cache_key = f"earnings:{window}:{theme or ''}:{start.isoformat()}:{end.isoformat()}"
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached
    payload = {
        "window": window,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "theme": theme,
        "cards": dashboard.earnings_cards(db, window, theme),
    }
    response_cache.set(cache_key, payload)
    return payload


@router.get("/company/{ticker}", tags=["company"])
def get_company(
    ticker: str,
    access: PaidAccess,
    caller: OptionalAuth,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    detail = dashboard.company_detail(db, ticker)
    if detail is None:
        raise HTTPException(404, f"No data for {ticker.upper()}")
    if access == "preview":
        return _preview_company(detail)
    if not _is_admin(caller, settings):
        detail = {**detail, "playbook": None}
    return {**detail, "preview": False}


@router.get("/waves", tags=["waves"])
def get_waves(
    access: PaidAccess,
    recent_days: int = Query(14, ge=1, le=60),
    upcoming_days: int = Query(21, ge=1, le=60),
    db: Session = Depends(get_db),
) -> dict:
    signals = waves.current_waves(
        db, recent_days=recent_days, upcoming_days=upcoming_days
    )
    preview = access == "preview"
    if preview:
        signals = signals[:_PREVIEW_WAVES]
    return {
        "recent_days": recent_days,
        "upcoming_days": upcoming_days,
        "count": len(signals),
        "signals": signals,
        "preview": preview,
        "preview_note": (
            "Preview — a few live peer-wave setups. Pro unlocks the full board."
            if preview
            else None
        ),
    }


@router.get("/drift", tags=["drift"])
def get_drift(
    access: PaidAccess,
    caller: OptionalAuth,
    lookback_days: int = Query(12, ge=3, le=45),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    setups = drift.drift_setups(db, lookback_days=lookback_days)
    preview = access == "preview"
    if not _is_admin(caller, settings) or preview:
        setups = [{**s, "plan": None} for s in setups]
    if preview:
        setups = setups[:_PREVIEW_DRIFT]
    return {
        "lookback_days": lookback_days,
        "count": len(setups),
        "setups": setups,
        "preview": preview,
        "preview_note": (
            "Preview — sample post-earnings drift setups. Pro unlocks the full list."
            if preview
            else None
        ),
    }


@router.get("/reddit", tags=["reddit"])
def get_reddit(
    access: PaidAccess,
    refresh: bool = Query(
        False, description="Run a live scan now (polls Reddit); else read the latest journaled signals"
    ),
    db: Session = Depends(get_db),
) -> dict:
    preview = access == "preview"
    # Live scans are subscriber-only (hits external APIs).
    if refresh and preview:
        raise HTTPException(402, "Active subscription required for live Reddit scans")
    if refresh:
        signals = reddit_sentiment.current_reddit_signals(db)
        source = "live"
    else:
        signals = reddit_sentiment.recent_reddit_signals(db)
        source = "journal"
    if preview:
        signals = signals[:_PREVIEW_REDDIT]
    return {
        "source": source,
        "count": len(signals),
        "signals": signals,
        "preview": preview,
        "preview_note": (
            "Preview — recent Reddit attention signals. Pro unlocks the full feed + live scan."
            if preview
            else None
        ),
    }


@router.get("/paper", tags=["paper"])
def get_paper(_: Admin, db: Session = Depends(get_db)) -> dict:
    return paper_report.scorecard(db)


@router.get("/paper/attribution", tags=["paper"])
def get_paper_attribution(
    _: Admin,
    min_samples: int = Query(
        5, ge=1, le=100, description="Hide cohorts/features thinner than this"
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Signal attribution over the trade-decision feature store: which cohorts and
    entry features actually predict winners, with sample sizes + confidence
    intervals, calibration, and the opened-vs-skipped counterfactual."""
    return attribution_report(db, min_samples=min_samples)


@router.get("/paper/progress", tags=["paper"])
def get_paper_progress(
    _: Admin,
    weeks: int = Query(8, ge=2, le=52, description="How many weeks back to reconstruct"),
    db: Session = Depends(get_db),
) -> dict:
    """Week-to-week learning tracker: the attribution state reconstructed at each
    past week-end, with deltas, a 'what changed' summary per week, and an honest
    verdict on whether the model is actually getting better."""
    return progress_series(db, weeks=weeks)


@router.get("/paper/narrative", tags=["paper"])
def get_paper_narrative(_: Admin, db: Session = Depends(get_db)) -> dict:
    """A plain-English post-mortem of the attribution numbers (LLM when a key is
    configured, deterministic heuristic otherwise), plus the current calibration
    state feeding back into the entry gate."""
    settings = get_settings()
    report = attribution_report(db)
    calib = calibration_state(db, settings)
    narrative = build_narrative(report, calib)
    return {**narrative, "calibration": calib}


def _run_refresh() -> None:
    with session_scope() as db:
        refresh_all(db)


@router.post("/refresh", tags=["meta"])
def post_refresh(
    _: Admin,
    background: bool = Query(True, description="Run the refresh in the background"),
    tasks: BackgroundTasks = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
) -> dict:
    if background:
        tasks.add_task(_run_refresh)
        return {"status": "scheduled"}
    result = refresh_all(db)
    return {"status": "done", **result}


@router.get("/refresh/status", tags=["meta"])
def refresh_status(db: Session = Depends(get_db)) -> dict:
    log = db.scalars(
        select(RefreshLog).order_by(RefreshLog.id.desc())
    ).first()
    if log is None:
        return {"status": "never_run"}
    return {
        "status": log.status,
        "started_at": log.started_at.isoformat() if log.started_at else None,
        "finished_at": log.finished_at.isoformat() if log.finished_at else None,
        "detail": log.detail,
    }
