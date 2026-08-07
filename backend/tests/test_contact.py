"""Contact form route (Resend mocked)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("PAYWALL_ENABLED", "false")
os.environ.setdefault("AUTH_SECRET", "test-secret")
os.environ["RESEND_API_KEY"] = "re_test"
os.environ["RESEND_FROM"] = "Test <test@example.com>"
os.environ["CONTACT_INBOX"] = "inbox@example.com"

from app.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402

get_settings.cache_clear()


@pytest.fixture()
def client(monkeypatch):
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override
    sent: list[dict] = []

    def _fake_send(settings, **kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setattr("app.services.auth_email.send_email", _fake_send)
    monkeypatch.setattr(
        "app.services.auth_email.resend_configured", lambda settings: True
    )

    with TestClient(app) as c:
        yield c, sent

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_contact_sends_to_inbox(client):
    c, sent = client
    res = c.post(
        "/contact",
        json={
            "name": "Sam",
            "email": "sam@example.com",
            "message": "How does Waves work for small caps?",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert len(sent) == 1
    assert sent[0]["to"] == "inbox@example.com"
    assert sent[0]["reply_to"] == "sam@example.com"
    assert "Sam" in sent[0]["subject"]


def test_contact_honeypot_silent(client):
    c, sent = client
    res = c.post(
        "/contact",
        json={
            "name": "Bot",
            "email": "bot@example.com",
            "message": "spam spam spam spam",
            "website": "http://spam.example",
        },
    )
    assert res.status_code == 200
    assert sent == []
