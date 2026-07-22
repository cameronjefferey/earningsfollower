from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db

ACTIVE_STATUSES = frozenset({"active", "trialing"})


@dataclass
class AuthUser:
    email: str
    sub: str | None
    name: str | None
    db_user: User | None

    @property
    def subscription_status(self) -> str:
        if self.db_user is None:
            return "none"
        return self.db_user.subscription_status or "none"

    def is_subscribed(self, settings: Settings) -> bool:
        if self.email.lower() in settings.auth_bypass_email_set:
            return True
        if self.db_user is None:
            return False
        return self.db_user.subscription_status in ACTIVE_STATUSES

    def is_admin(self, settings: Settings) -> bool:
        return self.email.lower() in settings.admin_email_set


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def decode_access_token(token: str, secret: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthUser | None:
    """Return the caller when a valid Bearer token is present; else None."""
    if not settings.auth_secret:
        return None
    token = _extract_bearer(request)
    if not token:
        return None
    payload = decode_access_token(token, settings.auth_secret)
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Token missing email")
    user = db.scalars(select(User).where(User.email == email)).first()
    return AuthUser(
        email=email,
        sub=payload.get("sub"),
        name=payload.get("name"),
        db_user=user,
    )


def require_user(
    user: Annotated[AuthUser | None, Depends(get_optional_user)] = None,
    settings: Settings = Depends(get_settings),
) -> AuthUser:
    if user is None:
        # When the paywall is off we still allow identity-optional routes; callers
        # that truly need a user should only be wired when paywall is on.
        if not settings.paywall_enabled:
            raise HTTPException(
                status_code=401,
                detail="Sign in required (send Authorization: Bearer <token>)",
            )
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def require_subscriber(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthUser | None:
    """Gate paid API routes. No-op (returns None) when the paywall is disabled."""
    if not settings.paywall_enabled:
        return None
    if not settings.auth_secret:
        raise HTTPException(
            status_code=503,
            detail="Paywall enabled but AUTH_SECRET is not configured",
        )
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in required")
    payload = decode_access_token(token, settings.auth_secret)
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Token missing email")
    user = db.scalars(select(User).where(User.email == email)).first()
    auth = AuthUser(
        email=email,
        sub=payload.get("sub"),
        name=payload.get("name"),
        db_user=user,
    )
    if not auth.is_subscribed(settings):
        raise HTTPException(
            status_code=402,
            detail="Active subscription required",
        )
    return auth


def require_admin(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthUser:
    """Gate admin-only surfaces. Empty ADMIN_EMAILS → nobody is admin (403)."""
    if not settings.admin_email_set:
        raise HTTPException(
            status_code=403,
            detail="Admin access is not configured",
        )
    if not settings.auth_secret:
        raise HTTPException(
            status_code=503,
            detail="AUTH_SECRET is not configured",
        )
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in required")
    payload = decode_access_token(token, settings.auth_secret)
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Token missing email")
    user = db.scalars(select(User).where(User.email == email)).first()
    auth = AuthUser(
        email=email,
        sub=payload.get("sub"),
        name=payload.get("name"),
        db_user=user,
    )
    if not auth.is_admin(settings):
        raise HTTPException(status_code=403, detail="Admin access required")
    return auth


# Shorthand for route annotations
Subscriber = Annotated[AuthUser | None, Depends(require_subscriber)]
OptionalAuth = Annotated[AuthUser | None, Depends(get_optional_user)]
Admin = Annotated[AuthUser, Depends(require_admin)]
