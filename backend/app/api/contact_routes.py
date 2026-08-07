"""Public contact form → Resend email to the site inbox."""

from __future__ import annotations

import html as html_lib
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.config import Settings, get_settings
from app.services import auth_email, auth_rate_limit

router = APIRouter(prefix="/contact", tags=["contact"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ContactBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: str = Field(..., min_length=3, max_length=320)
    message: str = Field(..., min_length=10, max_length=5000)
    # Honeypot — bots fill this; humans leave it blank.
    website: str | None = Field(default="", max_length=200)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        name = (v or "").strip()
        if not name:
            raise ValueError("name is required")
        return name

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        email = (v or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("invalid email")
        return email

    @field_validator("message")
    @classmethod
    def _message(cls, v: str) -> str:
        msg = (v or "").strip()
        if len(msg) < 10:
            raise ValueError("message is too short")
        return msg


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


@router.post("")
def submit_contact(
    body: ContactBody,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict:
    # Silent success for honeypot fills so scrapers don't learn.
    if (body.website or "").strip():
        return {"ok": True}

    ip = _client_ip(request)
    if not auth_rate_limit.allow(f"contact:{ip}", limit=5, window_sec=3600):
        raise HTTPException(status_code=429, detail="Too many messages. Try again later.")
    if not auth_rate_limit.allow(
        f"contact:{body.email}", limit=3, window_sec=3600
    ):
        raise HTTPException(status_code=429, detail="Too many messages. Try again later.")

    if not auth_email.resend_configured(settings):
        raise HTTPException(status_code=503, detail="Contact form is temporarily unavailable.")

    inbox = (settings.contact_inbox or "").strip()
    if not inbox or "@" not in inbox:
        raise HTTPException(status_code=503, detail="Contact form is temporarily unavailable.")

    safe_name = html_lib.escape(body.name)
    safe_email = html_lib.escape(body.email)
    safe_msg = html_lib.escape(body.message).replace("\n", "<br>")

    subject = f"[earningsfollower] Message from {body.name}"
    text = (
        f"From: {body.name} <{body.email}>\n"
        f"IP: {ip}\n\n"
        f"{body.message}\n"
    )
    html = (
        f"<p><strong>From:</strong> {safe_name} &lt;{safe_email}&gt;</p>"
        f"<p><strong>IP:</strong> {html_lib.escape(ip)}</p>"
        f"<hr><p>{safe_msg}</p>"
    )

    sent = auth_email.send_email(
        settings,
        to=inbox,
        subject=subject,
        text=text,
        html=html,
        reply_to=body.email,
    )
    if not sent:
        raise HTTPException(
            status_code=502,
            detail="Could not send your message. Please try again shortly.",
        )
    return {"ok": True, "message": "Thanks — we’ll get back to you by email."}
