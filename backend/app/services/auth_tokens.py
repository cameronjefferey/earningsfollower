"""One-time auth tokens (magic login, password reset, email verify)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuthToken

PURPOSE_MAGIC = "magic_login"
PURPOSE_RESET = "password_reset"
PURPOSE_VERIFY = "email_verify"

TTL = {
    PURPOSE_MAGIC: timedelta(minutes=15),
    PURPOSE_RESET: timedelta(hours=1),
    PURPOSE_VERIFY: timedelta(days=2),
}


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mint_token(db: Session, *, email: str, purpose: str) -> str:
    """Create a one-time token; returns the raw token to put in the email link."""
    if purpose not in TTL:
        raise ValueError(f"unknown purpose: {purpose}")
    email = email.strip().lower()
    raw = secrets.token_urlsafe(32)
    row = AuthToken(
        email=email,
        purpose=purpose,
        token_hash=_hash_token(raw),
        expires_at=datetime.utcnow() + TTL[purpose],
    )
    db.add(row)
    db.flush()
    return raw


def consume_token(
    db: Session, *, raw: str, purpose: str
) -> AuthToken | None:
    """Validate and mark a token used. Returns the row, or None if invalid."""
    if not raw or purpose not in TTL:
        return None
    token_hash = _hash_token(raw.strip())
    row = db.scalars(
        select(AuthToken).where(
            AuthToken.token_hash == token_hash,
            AuthToken.purpose == purpose,
        )
    ).first()
    if row is None:
        return None
    if row.used_at is not None:
        return None
    if row.expires_at < datetime.utcnow():
        return None
    row.used_at = datetime.utcnow()
    db.flush()
    return row
