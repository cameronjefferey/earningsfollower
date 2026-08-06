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
from app.research.execution import execution_report
from app.research.progress import progress_series
from app.services.paper.exit_learning import exit_policy_state
from app.services import (
    board_snapshots,
    brief as brief_svc,
    dashboard,
    digest as digest_svc,
    drift,
    ranked_setups,
    reddit_sentiment,
    waves,
)
from app.services.ingest import refresh_all
from app.services.paper import report as paper_report
from app.services.paper.calibration import calibration_state
from app.services.paper.narrator import build_narrative
from app.services.preview_demo import (
    demo_drift,
    demo_reddit,
    demo_waves,
    preview_company,
)
from app.services import track_record as track_record_svc

router = APIRouter()

WINDOWS = {"all", "today", "week", "last_week", "upcoming", "around"}


def _is_admin(caller: OptionalAuth, settings: Settings) -> bool:
    return bool(caller and caller.is_admin(settings))

@router.get("/themes", tags=["reference"])
def get_themes(db: Session = Depends(get_db)) -> list[dict]:
    # Public (freemium): calendar filters need theme list.
    return dashboard.list_themes(db)


@router.get("/earnings", tags=["earnings"])
def get_earnings(
    window: str = Query("week", description="all|today|week|last_week|upcoming|around"),
    theme: str | None = Query(None),
    limit: int = Query(
        80,
        ge=1,
        le=400,
        description="Return at most this many cards (date-ordered). Raise to load more.",
    ),
    db: Session = Depends(get_db),
) -> dict:
    if window not in WINDOWS:
        raise HTTPException(400, f"window must be one of {sorted(WINDOWS)}")
    start, end = dashboard.date_range_for_window(window)
    # Day + limit in the key so Mon–Sun windows roll correctly at midnight.
    cache_key = (
        f"earnings:{window}:{theme or ''}:{start.isoformat()}:{end.isoformat()}:{limit}"
    )
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached

    cards: list | None = None
    has_more = False
    updated_at = None
    # Prefer the persisted full-span snapshot (built on refresh / first full load).
    # Ignore snapshots that predate new card fields (e.g. conviction) so filters
    # don't silently empty the board until the next cron refresh.
    snap = board_snapshots.get_snapshot(
        db, "earnings", board_snapshots.earnings_snapshot_key()
    )
    snap_cards = snap.get("cards") if snap else None
    snap_usable = (
        isinstance(snap_cards, list)
        and (not snap_cards or "conviction" in snap_cards[0])
    )
    if snap_usable:
        cards = list(snap_cards)
        updated_at = snap.get("updated_at")
        if window != "all":
            s, e = start.isoformat(), end.isoformat()
            cards = [c for c in cards if s <= (c.get("date") or "") <= e]
        if theme:
            cards = [
                c
                for c in cards
                if any(t.get("key") == theme for t in (c.get("themes") or []))
            ]
        has_more = len(cards) > limit
        cards = cards[:limit]
    elif window == "all" and not theme:
        # First full-span request materializes the snapshot (slow once).
        all_cards, _ = dashboard.earnings_cards(db, "all")
        try:
            row = board_snapshots.persist_earnings_snapshot(db, all_cards)
            updated_at = row.computed_at.isoformat() if row.computed_at else None
        except Exception:
            updated_at = None
        has_more = len(all_cards) > limit
        cards = all_cards[:limit]
    else:
        cards, has_more = dashboard.earnings_cards(db, window, theme, limit=limit)

    payload = {
        "window": window,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "theme": theme,
        "limit": limit,
        "count": len(cards),
        "has_more": has_more,
        "cards": cards,
        "updated_at": updated_at,
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
        return preview_company(detail)
    if not _is_admin(caller, settings):
        detail = {**detail, "playbook": None}
    return {**detail, "preview": False}


@router.get("/waves", tags=["waves"])
def get_waves(
    access: PaidAccess,
    recent_days: int = Query(14, ge=1, le=60),
    upcoming_days: int = Query(21, ge=1, le=60),
    limit: int = Query(
        40,
        ge=1,
        le=80,
        description="Max signals to return. Smaller values early-stop for faster first paint.",
    ),
    db: Session = Depends(get_db),
) -> dict:
    # Guests get a static demo board instantly — no live compute, no live book.
    if access == "preview":
        payload = demo_waves(recent_days=recent_days, upcoming_days=upcoming_days)
        return {**payload, "limit": limit, "has_more": False}

    cache_key = f"waves:{recent_days}:{upcoming_days}:{limit}"
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached

    # Prefer persisted snapshot for the default window (instant after refresh).
    params_key = f"{recent_days}:{upcoming_days}"
    snap = board_snapshots.get_snapshot(db, "waves", params_key)
    if snap is not None:
        payload = board_snapshots.slice_list_payload(snap, list_key="signals", limit=limit)
        response_cache.set(cache_key, payload)
        return payload

    signals, has_more = waves.current_waves(
        db,
        recent_days=recent_days,
        upcoming_days=upcoming_days,
        limit=limit,
    )
    payload = {
        "recent_days": recent_days,
        "upcoming_days": upcoming_days,
        "limit": limit,
        "count": len(signals),
        "has_more": has_more,
        "signals": signals,
        "preview": False,
        "preview_note": None,
        "updated_at": board_snapshots.last_refresh_finished(db),
    }
    response_cache.set(cache_key, payload)
    return payload


@router.get("/drift", tags=["drift"])
def get_drift(
    access: PaidAccess,
    caller: OptionalAuth,
    lookback_days: int = Query(12, ge=3, le=45),
    limit: int = Query(
        30,
        ge=1,
        le=60,
        description="Max setups to return. Smaller values early-stop for faster first paint.",
    ),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    if access == "preview":
        payload = demo_drift(lookback_days=lookback_days)
        return {**payload, "limit": limit, "has_more": False}

    is_admin = _is_admin(caller, settings)
    cache_key = f"drift:{lookback_days}:{limit}:{'admin' if is_admin else 'user'}"
    cached = response_cache.get(cache_key)
    if cached is not None:
        return cached

    snap = board_snapshots.get_snapshot(db, "drift", str(lookback_days))
    if snap is not None:
        payload = board_snapshots.slice_list_payload(
            snap, list_key="setups", limit=limit, strip_plans=not is_admin
        )
        response_cache.set(cache_key, payload)
        return payload

    setups, has_more = drift.drift_setups(db, lookback_days=lookback_days, limit=limit)
    if not is_admin:
        setups = [{**s, "plan": None} for s in setups]
    payload = {
        "lookback_days": lookback_days,
        "limit": limit,
        "count": len(setups),
        "has_more": has_more,
        "setups": setups,
        "preview": False,
        "preview_note": None,
        "updated_at": board_snapshots.last_refresh_finished(db),
    }
    response_cache.set(cache_key, payload)
    return payload


@router.get("/reddit", tags=["reddit"])
def get_reddit(
    access: PaidAccess,
    refresh: bool = Query(
        False, description="Run a live scan now (polls Reddit); else read the latest journaled signals"
    ),
    db: Session = Depends(get_db),
) -> dict:
    if access == "preview":
        if refresh:
            raise HTTPException(402, "Active subscription required for live Reddit scans")
        return demo_reddit()

    if refresh:
        signals = reddit_sentiment.current_reddit_signals(db)
        source = "live"
    else:
        cache_key = "reddit:journal"
        cached = response_cache.get(cache_key)
        if cached is not None:
            return cached
        signals = reddit_sentiment.recent_reddit_signals(db)
        source = "journal"
        payload = {
            "source": source,
            "count": len(signals),
            "signals": signals,
            "preview": False,
            "preview_note": None,
        }
        response_cache.set(cache_key, payload, ttl_seconds=120)
        return payload

    return {
        "source": source,
        "count": len(signals),
        "signals": signals,
        "preview": False,
        "preview_note": None,
    }


@router.get("/track-record", tags=["research"])
def get_track_record(
    access: PaidAccess,
    db: Session = Depends(get_db),
) -> dict:
    """Sanitized paper aggregates — freemium teaser, full detail for Pro."""
    return track_record_svc.track_record(db, preview=(access == "preview"))


@router.get("/digest/today", tags=["research"])
def get_digest_today(
    access: PaidAccess,
    db: Session = Depends(get_db),
) -> dict:
    """Homepage / digest page: what changed since the last refresh cycle."""
    return digest_svc.get_today(db, preview=(access == "preview"))


@router.get("/setups/ranked", tags=["research"])
def get_ranked_setups(
    access: PaidAccess,
    limit: int = Query(12, ge=1, le=40),
    db: Session = Depends(get_db),
) -> dict:
    """Cross-board ranked research setups (waves + drift) with why/watch notes."""
    return ranked_setups.ranked_setups(
        db, limit=limit, preview=(access == "preview")
    )


@router.get("/brief/today", tags=["research"])
def get_morning_brief(
    access: PaidAccess,
    db: Session = Depends(get_db),
) -> dict:
    """Morning habit page: digest + ranked picks + today's earnings names."""
    return brief_svc.morning_brief(db, preview=(access == "preview"))


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


@router.get("/paper/execution", tags=["paper"])
def get_paper_execution(
    _: Admin,
    min_samples: int = Query(
        5, ge=1, le=100, description="Hide capture cohorts thinner than this"
    ),
    weeks: int = Query(8, ge=2, le=52, description="Weeks of signal-vintage history"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Execution-quality decomposition: signal lean (opened + skipped) vs. entry
    timing (lag / chasing) vs. exit timing (MFE/MAE capture ratio). Isolates
    whether a loss was a bad signal, a late entry, or a mistimed exit."""
    report = execution_report(db, min_samples=min_samples, weeks=weeks)
    # The take-profit the live trader is enforcing right now (default or learned),
    # so the page shows the leak *and* that the loop has acted on it.
    report["live_exit_policy"] = exit_policy_state(db, settings)
    return report


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
