"""Internal ops endpoints (frontend → API alerts / traffic beacons)."""

from __future__ import annotations

import hmac
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import AuthToken, User
from app.db.session import get_db
from app.services import auth_rate_limit
from app.services.admin_events import log_event
from app.services.bot_signals import is_bot_suspect, score_bot
from app.services.signup_alerts import notify_signup

router = APIRouter(prefix="/ops", tags=["ops"])

TrafficKind = Literal["ad_landing", "ad_engage", "auth_fail"]


class OpsAlertBody(BaseModel):
    kind: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=2000)
    debounce_key: str | None = Field(default=None, max_length=128)


class TrafficBody(BaseModel):
    kind: TrafficKind
    path: str | None = Field(default=None, max_length=256)
    rdt_cid: str | None = Field(default=None, max_length=128)
    utm_source: str | None = Field(default=None, max_length=64)
    utm_medium: str | None = Field(default=None, max_length=64)
    utm_campaign: str | None = Field(default=None, max_length=128)
    engaged_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    ua: str | None = Field(default=None, max_length=512)
    auth_error: str | None = Field(default=None, max_length=128)
    auth_cause: str | None = Field(default=None, max_length=500)
    message: str | None = Field(default=None, max_length=2000)


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


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


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


class PurgeUsersBody(BaseModel):
    emails: list[str] = Field(..., min_length=1, max_length=50)

    @field_validator("emails")
    @classmethod
    def _emails(cls, values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in values:
            email = (raw or "").strip().lower()
            if not email or "@" not in email or email in seen:
                continue
            if len(email) > 320:
                continue
            seen.add(email)
            out.append(email)
        if not out:
            raise ValueError("no valid emails")
        return out


@router.post("/purge-users")
def post_ops_purge_users(
    body: PurgeUsersBody,
    _: None = Depends(_require_ops_secret),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Delete test/junk accounts by email. Refuses to delete configured admins."""
    admin_set = {e.lower() for e in settings.admin_email_set}
    blocked = [e for e in body.emails if e in admin_set]
    targets = [e for e in body.emails if e not in admin_set]

    found = db.scalars(select(User).where(User.email.in_(targets))).all()
    deleted = [u.email for u in found]
    missing = [e for e in targets if e not in set(deleted)]

    if found:
        emails = deleted
        db.execute(delete(AuthToken).where(AuthToken.email.in_(emails)))
        for u in found:
            db.delete(u)
        log_event(
            db,
            kind="users_purged",
            message=f"Purged {len(deleted)} user(s): {', '.join(deleted)}",
            meta={"emails": deleted, "blocked_admins": blocked, "missing": missing},
            telegram=True,
            debounce_s=0,
            debounce_key=f"users_purged:{','.join(sorted(deleted))}",
        )
        db.commit()

    return {
        "ok": True,
        "deleted": deleted,
        "missing": missing,
        "blocked_admins": blocked,
    }


@router.post("/traffic")
def post_ops_traffic(
    body: TrafficBody,
    request: Request,
    _: None = Depends(_require_ops_secret),
    db: Session = Depends(get_db),
) -> dict:
    """Persist ad/auth traffic beacons; Telegram only for bot-ish or auth fails."""
    ip = _client_ip(request)
    if not auth_rate_limit.allow(f"ops_traffic:{ip}", limit=120, window_sec=3600):
        return {"ok": True, "sent": False, "rate_limited": True}

    ua = (body.ua or request.headers.get("user-agent") or "").strip()[:512]
    score, reasons = score_bot(ua, ip=ip)
    bot = is_bot_suspect(score)

    meta: dict[str, Any] = {
        "path": body.path,
        "rdt_cid": body.rdt_cid,
        "utm_source": body.utm_source,
        "utm_medium": body.utm_medium,
        "utm_campaign": body.utm_campaign,
        "engaged_ms": body.engaged_ms,
        "ua": ua[:240] if ua else None,
        "ip": ip,
        "bot_score": score,
        "bot_reasons": reasons,
        "auth_error": body.auth_error,
        "auth_cause": body.auth_cause,
    }
    meta = {k: v for k, v in meta.items() if v is not None and v != []}

    message = body.message or _traffic_message(body, bot=bot, score=score, ip=ip, ua=ua)
    telegram = body.kind == "auth_fail" or (body.kind == "ad_landing" and bot)
    debounce_key = (
        f"auth_fail:{body.auth_error or 'unknown'}:{'bot' if bot else 'human'}"
        if body.kind == "auth_fail"
        else f"ad_bot:{ip}"
        if body.kind == "ad_landing" and bot
        else f"{body.kind}:{ip}"
    )
    debounce_s = 600 if telegram else 0

    log_event(
        db,
        kind=body.kind,
        message=message,
        meta=meta,
        telegram=telegram,
        debounce_s=debounce_s,
        debounce_key=debounce_key,
    )
    db.commit()
    return {"ok": True, "bot": bot, "bot_score": score, "telegram": telegram}


def _traffic_message(
    body: TrafficBody, *, bot: bool, score: int, ip: str, ua: str
) -> str:
    tag = "[BOT] " if bot else ""
    ua_short = (ua[:80] + "…") if len(ua) > 80 else ua
    if body.kind == "auth_fail":
        err = body.auth_error or "Error"
        cause = f" · {body.auth_cause}" if body.auth_cause else ""
        return (
            f"{tag}Auth fail: {err}{cause} · score={score} · ip={ip} · ua={ua_short or '—'}"
        )
    if body.kind == "ad_engage":
        ms = body.engaged_ms if body.engaged_ms is not None else "?"
        cid = body.rdt_cid or "—"
        return f"Ad engage {ms}ms · rdt_cid={cid} · {body.utm_campaign or body.utm_source or '—'}"
    # ad_landing
    cid = body.rdt_cid or "—"
    camp = body.utm_campaign or "—"
    src = body.utm_source or "—"
    return (
        f"{tag}Ad landing · source={src} · campaign={camp} · rdt_cid={cid} "
        f"· score={score} · ip={ip} · ua={ua_short or '—'}"
    )
