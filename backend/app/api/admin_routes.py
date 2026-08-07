"""Admin-only reporting for signups, subscriptions, and ops events."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Admin, subscription_is_active
from app.config import Settings, get_settings
from app.db.models import AppEvent, User
from app.db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])


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

    events = db.scalars(
        select(AppEvent).order_by(AppEvent.created_at.desc()).limit(events_limit)
    ).all()

    return {
        "generated_at": now.isoformat() + "Z",
        "users": {
            "total": int(total_users),
            "subscribed": int(subscribed_total),
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
