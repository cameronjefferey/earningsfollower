from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import OptionalAuth, subscription_is_active
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_db
from app.services import auth_email, auth_rate_limit, auth_tokens
from app.services.admin_events import log_event
from app.services.passwords import MIN_PASSWORD_LEN, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC_CREDS = "Invalid email or password"
_GENERIC_TOKEN = "Invalid or expired link"
_OK_CHECK_INBOX = {
    "ok": True,
    "message": "If that email can receive mail, check your inbox.",
}


def _normalize_email(v: str) -> str:
    email = (v or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("invalid email")
    return email


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _rate_key(kind: str, email: str, request: Request) -> str:
    return f"{kind}:{email}:{_client_ip(request)}"


class UpsertBody(BaseModel):
    email: str
    name: str | None = None
    image: str | None = None
    google_sub: str | None = Field(None, description="Google subject (sub) claim")

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class RegisterBody(BaseModel):
    email: str
    password: str
    name: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v or "") < MIN_PASSWORD_LEN:
            raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
        return v


class LoginBody(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class EmailBody(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class TokenBody(BaseModel):
    token: str


class ResetBody(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v or "") < MIN_PASSWORD_LEN:
            raise ValueError(f"password must be at least {MIN_PASSWORD_LEN} characters")
        return v


def _user_payload(user: User, settings: Settings) -> dict:
    email = user.email.lower()
    bypass = email in settings.auth_bypass_email_set
    is_admin = email in settings.admin_email_set
    status = user.subscription_status or "none"
    subscribed = subscription_is_active(
        email=email,
        status=status,
        period_end=user.current_period_end,
        settings=settings,
    )
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
        "is_vip": bypass,
        "is_admin": is_admin,
        "email_verified": user.email_verified_at is not None,
        "has_password": bool(user.password_hash),
        # NULL (pre-migration rows) means the default: alerts on.
        "wave_alerts": user.wave_alerts is not False,
    }


def _identity(user: User) -> dict:
    return {"email": user.email, "name": user.name}


def _ensure_user(db: Session, email: str) -> User:
    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None:
        user = User(email=email)
        db.add(user)
        db.flush()
    return user


@router.post("/upsert")
def upsert_user(
    body: UpsertBody,
    caller: OptionalAuth,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Create or update a user row after sign-in (Google or credentials sync)."""
    email = body.email.strip().lower()
    if caller is not None and caller.email != email:
        raise HTTPException(status_code=403, detail="Token email mismatch")
    if settings.paywall_enabled and caller is None:
        raise HTTPException(status_code=401, detail="Sign in required")

    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None and body.google_sub:
        user = db.scalars(select(User).where(User.google_sub == body.google_sub)).first()

    created = False
    if user is None:
        user = User(email=email)
        db.add(user)
        created = True

    user.email = email
    if body.name is not None:
        user.name = body.name
    if body.image is not None:
        user.image = body.image
    if body.google_sub:
        user.google_sub = body.google_sub
        if user.email_verified_at is None:
            user.email_verified_at = datetime.utcnow()

    if created:
        via = "google" if body.google_sub else "sign-in"
        log_event(
            db,
            kind="user_created",
            email=email,
            message=f"New account: {email} ({via})",
            meta={"via": via},
            debounce_s=0,
        )

    db.commit()
    db.refresh(user)
    if created and auth_email.resend_configured(settings):
        auth_email.send_welcome(settings, email=user.email, name=user.name)
    payload = _user_payload(user, settings)
    payload["created"] = created
    return payload


@router.get("/me")
def me(
    caller: OptionalAuth,
    settings: Settings = Depends(get_settings),
) -> dict:
    if caller is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    if caller.db_user is None:
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
            "is_vip": bypass,
            "is_admin": is_admin,
            "email_verified": False,
            "has_password": False,
            "wave_alerts": True,
        }
    return _user_payload(caller.db_user, settings)


class PrefsBody(BaseModel):
    wave_alerts: bool


@router.post("/prefs")
def update_prefs(
    body: PrefsBody,
    caller: OptionalAuth,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Update notification preferences for the signed-in user."""
    if caller is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    user = caller.db_user or _ensure_user(db, caller.email.lower())
    user.wave_alerts = body.wave_alerts
    db.commit()
    db.refresh(user)
    return _user_payload(user, settings)


@router.post("/register")
def register(
    body: RegisterBody,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Create an email/password account and send a verification email."""
    if not auth_rate_limit.allow(_rate_key("register", body.email, request), limit=8):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    user = db.scalars(select(User).where(User.email == body.email)).first()
    if user is not None and user.password_hash:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Sign in or reset your password.",
        )

    created = False
    if user is None:
        user = User(email=body.email)
        db.add(user)
        created = True

    user.password_hash = hash_password(body.password)
    if body.name:
        user.name = body.name.strip() or user.name

    raw = auth_tokens.mint_token(
        db, email=user.email, purpose=auth_tokens.PURPOSE_VERIFY
    )
    if created:
        log_event(
            db,
            kind="user_created",
            email=user.email,
            message=f"New account: {user.email} (password)",
            meta={"via": "password"},
            debounce_s=0,
        )
    else:
        log_event(
            db,
            kind="password_set",
            email=user.email,
            message=f"Password set on existing account: {user.email}",
            meta={"via": "register"},
            debounce_s=0,
        )
    db.commit()

    if not auth_email.resend_configured(settings):
        # Account still created; verification email skipped until Resend is wired.
        return {
            "ok": True,
            "email": user.email,
            "verify_email_sent": False,
            "message": "Account created. Email delivery is not configured yet.",
        }

    sent = auth_email.send_verify_email(settings, email=user.email, token=raw)
    if created:
        auth_email.send_welcome(settings, email=user.email, name=user.name)
    return {
        "ok": True,
        "email": user.email,
        "verify_email_sent": sent,
        "message": "Account created. Check your inbox to verify your email.",
    }


@router.post("/login")
def login(
    body: LoginBody,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Verify email/password for the Auth.js Credentials provider."""
    if not auth_rate_limit.allow(
        _rate_key("login", body.email, request), limit=20, window_sec=900
    ):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    user = db.scalars(select(User).where(User.email == body.email)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail=_GENERIC_CREDS)
    return _identity(user)


@router.post("/magic/request")
def magic_request(
    body: EmailBody,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Email a magic sign-in link. Always returns a generic success payload."""
    if not auth_rate_limit.allow(_rate_key("magic", body.email, request), limit=5):
        return _OK_CHECK_INBOX

    if not auth_email.resend_configured(settings):
        raise HTTPException(
            status_code=503,
            detail="Email sign-in is not configured yet. Use Google or a password.",
        )

    existing = db.scalars(select(User).where(User.email == body.email)).first()
    user = existing or _ensure_user(db, body.email)
    created = existing is None
    raw = auth_tokens.mint_token(
        db, email=user.email, purpose=auth_tokens.PURPOSE_MAGIC
    )
    if created:
        log_event(
            db,
            kind="user_created",
            email=user.email,
            message=f"New account: {user.email} (magic link)",
            meta={"via": "magic"},
            debounce_s=0,
        )
    db.commit()
    sent = auth_email.send_magic_link(
        settings,
        email=user.email,
        token=raw,
        welcome_new_user=created,
    )
    if not sent:
        raise HTTPException(
            status_code=502,
            detail="Could not send the sign-in email. Try again, or use Google / password.",
        )
    return {
        "ok": True,
        "message": f"Check {user.email} for a sign-in link (and Spam / Promotions).",
    }


@router.post("/magic/consume")
def magic_consume(
    body: TokenBody,
    db: Session = Depends(get_db),
) -> dict:
    """One-time validate a magic-link token for the Credentials provider."""
    row = auth_tokens.consume_token(
        db, raw=body.token, purpose=auth_tokens.PURPOSE_MAGIC
    )
    if row is None:
        raise HTTPException(status_code=401, detail=_GENERIC_TOKEN)

    user = _ensure_user(db, row.email)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return _identity(user)


@router.post("/password/forgot")
def password_forgot(
    body: EmailBody,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Email a password-reset link. Always returns a generic success payload."""
    if not auth_rate_limit.allow(_rate_key("forgot", body.email, request), limit=5):
        return _OK_CHECK_INBOX

    if not auth_email.resend_configured(settings):
        raise HTTPException(
            status_code=503,
            detail="Password reset email is not configured yet.",
        )

    user = db.scalars(select(User).where(User.email == body.email)).first()
    # Send for any existing account so Google-only users can set a password.
    if user is not None:
        raw = auth_tokens.mint_token(
            db, email=user.email, purpose=auth_tokens.PURPOSE_RESET
        )
        db.commit()
        auth_email.send_password_reset(settings, email=user.email, token=raw)
    return _OK_CHECK_INBOX


@router.post("/password/reset")
def password_reset(
    body: ResetBody,
    db: Session = Depends(get_db),
) -> dict:
    row = auth_tokens.consume_token(
        db, raw=body.token, purpose=auth_tokens.PURPOSE_RESET
    )
    if row is None:
        raise HTTPException(status_code=401, detail=_GENERIC_TOKEN)

    user = _ensure_user(db, row.email)
    user.password_hash = hash_password(body.password)
    if user.email_verified_at is None:
        user.email_verified_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "email": user.email}


@router.post("/email/verify")
def email_verify(
    body: TokenBody,
    db: Session = Depends(get_db),
) -> dict:
    row = auth_tokens.consume_token(
        db, raw=body.token, purpose=auth_tokens.PURPOSE_VERIFY
    )
    if row is None:
        raise HTTPException(status_code=401, detail=_GENERIC_TOKEN)

    user = _ensure_user(db, row.email)
    user.email_verified_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "email": user.email}
