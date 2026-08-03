"""Internal ops endpoints (frontend → API alerts)."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.signup_alerts import notify_signup

router = APIRouter(prefix="/ops", tags=["ops"])


class OpsAlertBody(BaseModel):
    kind: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=2000)
    debounce_key: str | None = Field(default=None, max_length=128)


def _require_ops_secret(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    secret = (settings.auth_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="AUTH_SECRET is not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/alert")
def post_ops_alert(
    body: OpsAlertBody,
    _: None = Depends(_require_ops_secret),
    settings: Settings = Depends(get_settings),
) -> dict:
    sent = notify_signup(
        body.kind,
        body.message,
        debounce_key=body.debounce_key or body.kind,
        settings=settings,
    )
    return {"ok": True, "sent": sent}
