"""Transactional auth email via Resend's HTTP API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


def resend_configured(settings: Settings) -> bool:
    return bool(settings.resend_api_key.strip() and settings.resend_from.strip())


def send_email(
    settings: Settings,
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    reply_to: str | None = None,
) -> bool:
    """Send one email. Returns True on success. Never raises to callers."""
    if not resend_configured(settings):
        logger.warning("Resend not configured; skipped email to %s (%s)", to, subject)
        return False
    payload: dict[str, Any] = {
        "from": settings.resend_from.strip(),
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    if reply_to:
        payload["reply_to"] = reply_to.strip()
    try:
        res = httpx.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key.strip()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20.0,
        )
        if res.status_code >= 400:
            logger.warning(
                "Resend error %s for %s: %s", res.status_code, to, res.text[:300]
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Resend send failed for %s: %s", to, exc)
        return False


def _app_url(settings: Settings) -> str:
    return (settings.public_app_url or "http://localhost:3000").rstrip("/")


def send_magic_link(
    settings: Settings,
    *,
    email: str,
    token: str,
    welcome_new_user: bool = False,
) -> bool:
    link = f"{_app_url(settings)}/login/magic?token={token}"
    calendar = f"{_app_url(settings)}/calendar"
    welcome_text = ""
    welcome_html = ""
    if welcome_new_user:
        welcome_text = (
            "Welcome - your account is ready. The earnings calendar is free "
            f"({calendar}). Pro unlocks Drift and Waves boards when you're ready.\n\n"
        )
        welcome_html = (
            "<p>Welcome - your account is ready. The earnings calendar is free. "
            "Pro unlocks Drift and Waves boards when you&apos;re ready.</p>"
        )
    return send_email(
        settings,
        to=email,
        subject="Your Earnings Follower sign-in link",
        text=(
            f"{welcome_text}"
            f"Sign in to Earnings Follower:\n\n{link}\n\n"
            "This link expires in 15 minutes."
        ),
        html=(
            f"{welcome_html}"
            "<p>Sign in to Earnings Follower:</p>"
            f'<p><a href="{link}">Continue to Earnings Follower</a></p>'
            "<p style='color:#666;font-size:13px'>This link expires in 15 minutes. "
            "If you didn't request it, you can ignore this email.</p>"
        ),
    )


def send_welcome(
    settings: Settings,
    *,
    email: str,
    name: str | None = None,
) -> bool:
    """Short onboarding email after password / Google account creation."""
    calendar = f"{_app_url(settings)}/calendar"
    boards = f"{_app_url(settings)}/boards"
    greeting = f"Hi {name}," if name and name.strip() else "Hi,"
    return send_email(
        settings,
        to=email,
        subject="Welcome to Earnings Follower",
        text=(
            f"{greeting}\n\n"
            "Your account is ready. The earnings calendar is free - who reports "
            "and what's priced in:\n\n"
            f"{calendar}\n\n"
            "When you want live Drift and Waves boards, Pro unlocks them:\n\n"
            f"{boards}\n\n"
            "- Earnings Follower"
        ),
        html=(
            f"<p>{greeting}</p>"
            "<p>Your account is ready. The earnings calendar is free - who reports "
            "and what&apos;s priced in.</p>"
            f'<p><a href="{calendar}">Open the calendar</a></p>'
            "<p>When you want live Drift and Waves boards, Pro unlocks them.</p>"
            f'<p><a href="{boards}">Preview the boards</a></p>'
            "<p style='color:#666;font-size:13px'>- Earnings Follower</p>"
        ),
    )


def send_verify_email(settings: Settings, *, email: str, token: str) -> bool:
    link = f"{_app_url(settings)}/login/verify?token={token}"
    return send_email(
        settings,
        to=email,
        subject="Verify your Earnings Follower email",
        text=f"Verify your email for Earnings Follower:\n\n{link}\n\nThis link expires in 48 hours.",
        html=(
            "<p>Verify your email for Earnings Follower:</p>"
            f'<p><a href="{link}">Verify email</a></p>'
            "<p style='color:#666;font-size:13px'>This link expires in 48 hours.</p>"
        ),
    )


def send_password_reset(settings: Settings, *, email: str, token: str) -> bool:
    link = f"{_app_url(settings)}/login/reset?token={token}"
    return send_email(
        settings,
        to=email,
        subject="Reset your Earnings Follower password",
        text=f"Reset your password:\n\n{link}\n\nThis link expires in 1 hour.",
        html=(
            "<p>Reset your Earnings Follower password:</p>"
            f'<p><a href="{link}">Choose a new password</a></p>'
            "<p style='color:#666;font-size:13px'>This link expires in 1 hour. "
            "If you didn't request a reset, you can ignore this email.</p>"
        ),
    )


def mailer_status(settings: Settings) -> dict[str, Any]:
    return {"configured": resend_configured(settings)}
