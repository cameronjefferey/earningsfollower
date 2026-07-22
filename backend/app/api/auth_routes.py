from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ACTIVE_STATUSES, OptionalAuth
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class UpsertBody(BaseModel):
    email: str
    name: str | None = None
    image: str | None = None
    google_sub: str | None = Field(None, description="Google subject (sub) claim")

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        email = (v or "").strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("invalid email")
        return email


def _user_payload(user: User, settings: Settings) -> dict:
    email = user.email.lower()
    bypass = email in settings.auth_bypass_email_set
    is_admin = email in settings.admin_email_set
    status = user.subscription_status or "none"
    subscribed = bypass or status in ACTIVE_STATUSES
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "image": user.image,
        "subscription_status": "active" if bypass and status == "none" else status,
        "subscribed": subscribed,
        "current_period_end": (
            user.current_period_end.isoformat() if user.current_period_end else None
        ),
        "bypass": bypass,
        "is_admin": is_admin,
    }


@router.post("/upsert")
def upsert_user(
    body: UpsertBody,
    caller: OptionalAuth,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Create or update a user row after Google sign-in.

    Prefer calling with a Bearer token whose email matches the body. When the
    paywall is off we also accept unauthenticated upserts so the jwt callback
    can sync before the client has a token wired everywhere.
    """
    email = body.email.strip().lower()
    if caller is not None and caller.email != email:
        raise HTTPException(status_code=403, detail="Token email mismatch")
    if settings.paywall_enabled and caller is None:
        raise HTTPException(status_code=401, detail="Sign in required")

    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None and body.google_sub:
        user = db.scalars(select(User).where(User.google_sub == body.google_sub)).first()

    if user is None:
        user = User(email=email)
        db.add(user)

    user.email = email
    if body.name is not None:
        user.name = body.name
    if body.image is not None:
        user.image = body.image
    if body.google_sub:
        user.google_sub = body.google_sub

    db.commit()
    db.refresh(user)
    return _user_payload(user, settings)


@router.get("/me")
def me(
    caller: OptionalAuth,
    settings: Settings = Depends(get_settings),
) -> dict:
    if caller is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    if caller.db_user is None:
        # Token valid but row not synced yet.
        email = caller.email.lower()
        bypass = email in settings.auth_bypass_email_set
        is_admin = email in settings.admin_email_set
        return {
            "id": None,
            "email": caller.email,
            "name": caller.name,
            "image": None,
            "subscription_status": "active" if bypass else "none",
            "subscribed": bypass,
            "current_period_end": None,
            "bypass": bypass,
            "is_admin": is_admin,
        }
    return _user_payload(caller.db_user, settings)
