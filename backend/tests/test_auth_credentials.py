"""Email/password + magic-token auth routes (no live Resend)."""

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
os.environ.setdefault("AUTH_SECRET", "test-secret-for-auth-tests")
os.environ["RESEND_API_KEY"] = ""
os.environ["RESEND_FROM"] = ""

from app.db.models import Base, User  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import auth_tokens  # noqa: E402
from app.services.passwords import hash_password, verify_password  # noqa: E402


@pytest.fixture()
def client():
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
    with TestClient(app) as c:
        yield c, TestingSession
    app.dependency_overrides.clear()


def test_hash_roundtrip():
    h = hash_password("password123")
    assert verify_password("password123", h)
    assert not verify_password("wrong", h)
    assert not verify_password("password123", None)


def test_register_and_login(client):
    c, Session = client
    res = c.post(
        "/auth/register",
        json={"email": "Ada@Example.com", "password": "password123", "name": "Ada"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["email"] == "ada@example.com"
    assert body["verify_email_sent"] is False  # Resend not configured

    bad = c.post(
        "/auth/login",
        json={"email": "ada@example.com", "password": "nope-nope"},
    )
    assert bad.status_code == 401

    ok = c.post(
        "/auth/login",
        json={"email": "ada@example.com", "password": "password123"},
    )
    assert ok.status_code == 200
    assert ok.json()["email"] == "ada@example.com"
    assert ok.json()["name"] == "Ada"

    again = c.post(
        "/auth/register",
        json={"email": "ada@example.com", "password": "password123"},
    )
    assert again.status_code == 409


def test_register_attaches_password_to_google_only_user(client):
    c, Session = client
    with Session() as db:
        db.add(User(email="mixed@example.com", google_sub="g-1"))
        db.commit()

    res = c.post(
        "/auth/register",
        json={"email": "mixed@example.com", "password": "password123"},
    )
    assert res.status_code == 200

    ok = c.post(
        "/auth/login",
        json={"email": "mixed@example.com", "password": "password123"},
    )
    assert ok.status_code == 200


def test_magic_consume_once(client):
    c, Session = client
    with Session() as db:
        user = User(email="magic@example.com")
        db.add(user)
        raw = auth_tokens.mint_token(
            db, email="magic@example.com", purpose=auth_tokens.PURPOSE_MAGIC
        )
        db.commit()

    first = c.post("/auth/magic/consume", json={"token": raw})
    assert first.status_code == 200
    assert first.json()["email"] == "magic@example.com"

    second = c.post("/auth/magic/consume", json={"token": raw})
    assert second.status_code == 401

    with Session() as db:
        row = db.query(User).filter_by(email="magic@example.com").one()
        assert row.email_verified_at is not None


def test_password_forgot_always_200_when_resend_configured(client, monkeypatch):
    c, Session = client
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM", "Test <test@example.com>")

    # Settings are cached; clear so env picks up.
    from app.config import get_settings

    get_settings.cache_clear()

    sent: list[str] = []

    def _fake_send(settings, *, email, token):
        sent.append(email)
        return True

    monkeypatch.setattr(
        "app.services.auth_email.send_password_reset", _fake_send
    )
    monkeypatch.setattr(
        "app.services.auth_email.resend_configured", lambda settings: True
    )

    with Session() as db:
        db.add(User(email="reset@example.com", password_hash=hash_password("password123")))
        db.commit()

    known = c.post("/auth/password/forgot", json={"email": "reset@example.com"})
    assert known.status_code == 200
    assert known.json()["ok"] is True
    assert sent == ["reset@example.com"]

    unknown = c.post("/auth/password/forgot", json={"email": "nobody@example.com"})
    assert unknown.status_code == 200
    assert unknown.json()["ok"] is True
    assert sent == ["reset@example.com"]  # no leak / no send

    get_settings.cache_clear()


def test_password_reset_flow(client):
    c, Session = client
    with Session() as db:
        db.add(
            User(
                email="reset2@example.com",
                password_hash=hash_password("old-password"),
            )
        )
        raw = auth_tokens.mint_token(
            db, email="reset2@example.com", purpose=auth_tokens.PURPOSE_RESET
        )
        db.commit()

    res = c.post(
        "/auth/password/reset",
        json={"token": raw, "password": "new-password"},
    )
    assert res.status_code == 200

    bad = c.post(
        "/auth/login",
        json={"email": "reset2@example.com", "password": "old-password"},
    )
    assert bad.status_code == 401

    ok = c.post(
        "/auth/login",
        json={"email": "reset2@example.com", "password": "new-password"},
    )
    assert ok.status_code == 200
