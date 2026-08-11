"""Admin-only reporting for signups, subscriptions, and ops events."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Admin, subscription_is_active
from app.config import Settings, get_settings
from app.db.models import AppEvent, User
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

_TRAFFIC_KINDS = (
    "pageview",
    "ad_landing",
    "ad_engage",
    "cta_click",
    "calendar_view",
    "company_view",
    "guest_gate",
    "signup",
)


@router.get("/traffic")
def admin_traffic(
    _admin: Admin,
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=30),
) -> dict:
    """What visitors do on the site: pages, tickers, funnel steps, CTA placements."""
    since = datetime.utcnow() - timedelta(days=days)
    events = db.scalars(
        select(AppEvent)
        .where(AppEvent.kind.in_(_TRAFFIC_KINDS), AppEvent.created_at >= since)
        .order_by(AppEvent.created_at.desc())
    ).all()

    by_kind: Counter[str] = Counter()
    daily: dict[str, Counter[str]] = defaultdict(Counter)
    paths: Counter[str] = Counter()
    path_sids: dict[str, set[str]] = defaultdict(set)
    tickers: Counter[str] = Counter()
    ctas: Counter[str] = Counter()
    viewers: Counter[str] = Counter()
    referrers: Counter[str] = Counter()
    sids: set[str] = set()
    sessions: dict[str, list[AppEvent]] = defaultdict(list)

    for e in events:
        by_kind[e.kind] += 1
        day = e.created_at.date().isoformat() if e.created_at else "?"
        daily[day][e.kind] += 1
        try:
            meta = json.loads(e.meta_json) if e.meta_json else {}
        except ValueError:
            meta = {}
        sid = meta.get("sid")
        path = meta.get("path")
        if sid:
            sids.add(sid)
            sessions[sid].append(e)
        if e.kind == "pageview":
            if path:
                paths[path] += 1
                if sid:
                    path_sids[path].add(sid)
                if path.startswith("/company/"):
                    tickers[path.removeprefix("/company/").upper()] += 1
            if meta.get("viewer"):
                viewers[meta["viewer"]] += 1
            if meta.get("referrer"):
                referrers[meta["referrer"][:120]] += 1
        elif e.kind == "company_view" and meta.get("target"):
            tickers[str(meta["target"]).upper()] += 1
        elif e.kind == "cta_click" and meta.get("target"):
            ctas[str(meta["target"])] += 1

    # Session depth: how many pages a visiting session actually opens.
    depths = [
        sum(1 for e in evs if e.kind == "pageview") for evs in sessions.values()
    ]
    depths = [d for d in depths if d > 0]
    multi_page = sum(1 for d in depths if d >= 2)

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "days": days,
        "by_kind": dict(by_kind),
        "daily": {d: dict(c) for d, c in sorted(daily.items())},
        "unique_sessions": len(sids),
        "sessions_with_pageviews": len(depths),
        "multi_page_sessions": multi_page,
        "avg_pages_per_session": (
            round(sum(depths) / len(depths), 2) if depths else 0
        ),
        "top_paths": [
            {"path": p, "views": n, "sessions": len(path_sids[p])}
            for p, n in paths.most_common(25)
        ],
        "top_tickers": [
            {"ticker": t, "views": n} for t, n in tickers.most_common(20)
        ],
        "cta_clicks": [{"target": t, "clicks": n} for t, n in ctas.most_common()],
        "viewers": dict(viewers),
        "referrers": [
            {"referrer": r, "count": n} for r, n in referrers.most_common(10)
        ],
    }


@router.get("/overview")
def admin_overview(
    _admin: Admin,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    events_limit: int = Query(50, ge=1, le=200),
    users_limit: int = Query(40, ge=1, le=200),
) -> dict:
    now = datetime.utcnow()
    d7 = now - timedelta(days=7)
    d30 = now - timedelta(days=30)

    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    created_7d = (
        db.scalar(
            select(func.count()).select_from(User).where(User.created_at >= d7)
        )
        or 0
    )
    created_30d = (
        db.scalar(
            select(func.count()).select_from(User).where(User.created_at >= d30)
        )
        or 0
    )

    status_rows = db.execute(
        select(User.subscription_status, func.count())
        .group_by(User.subscription_status)
        .order_by(func.count().desc())
    ).all()
    by_status = {str(status or "none"): int(n) for status, n in status_rows}

    all_users = db.scalars(select(User)).all()
    bypass_emails = settings.auth_bypass_email_set
    admin_emails = settings.admin_email_set
    subscribed_total = sum(
        1
        for u in all_users
        if subscription_is_active(
            email=u.email,
            status=u.subscription_status or "none",
            period_end=u.current_period_end,
            settings=settings,
        )
    )
    vip_total = sum(1 for u in all_users if u.email.lower() in bypass_emails)
    admin_total = sum(1 for u in all_users if u.email.lower() in admin_emails)

    recent = sorted(
        all_users,
        key=lambda u: u.created_at or datetime.min,
        reverse=True,
    )[:users_limit]
    recent_users = [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "subscription_status": u.subscription_status or "none",
            "subscribed": subscription_is_active(
                email=u.email,
                status=u.subscription_status or "none",
                period_end=u.current_period_end,
                settings=settings,
            ),
            "is_vip": u.email.lower() in bypass_emails,
            "is_admin": u.email.lower() in admin_emails,
            "has_password": bool(u.password_hash),
            "has_google": bool(u.google_sub),
            "email_verified": u.email_verified_at is not None,
            "stripe_customer_id": u.stripe_customer_id,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "current_period_end": (
                u.current_period_end.isoformat() if u.current_period_end else None
            ),
        }
        for u in recent
    ]

    # Pageviews are high-volume noise here; they have their own /admin/traffic.
    events = db.scalars(
        select(AppEvent)
        .where(AppEvent.kind != "pageview")
        .order_by(AppEvent.created_at.desc())
        .limit(events_limit)
    ).all()

    return {
        "generated_at": now.isoformat() + "Z",
        "users": {
            "total": int(total_users),
            "subscribed": int(subscribed_total),
            "vip": int(vip_total),
            "admin": int(admin_total),
            "created_7d": int(created_7d),
            "created_30d": int(created_30d),
            "by_status": by_status,
        },
        "recent_users": recent_users,
        "recent_events": [
            {
                "id": e.id,
                "kind": e.kind,
                "email": e.email,
                "message": e.message,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
