from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.session import get_db
from app.main import app


def _override_db(db: MagicMock):
    def _gen():
        yield db

    return _gen


def test_ops_traffic_auth_fail_bot_tags_message():
    client = TestClient(app)
    settings = MagicMock(auth_secret="test-secret", telegram_notify_signup=True)
    db = MagicMock()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        with patch("app.api.ops_routes.log_event") as log_event:
            res = client.post(
                "/ops/traffic",
                headers={
                    "Authorization": "Bearer test-secret",
                    "User-Agent": "Mozilla/5.0 (compatible)",
                    "X-Forwarded-For": "23.23.253.54",
                },
                json={
                    "kind": "auth_fail",
                    "auth_error": "CallbackRouteError",
                    "path": "/api/auth/callback/google",
                },
            )
            assert res.status_code == 200
            body = res.json()
            assert body["bot"] is True
            assert body["telegram"] is True
            assert log_event.called
            kwargs = log_event.call_args.kwargs
            assert kwargs["kind"] == "auth_fail"
            assert "[BOT]" in kwargs["message"]
    finally:
        app.dependency_overrides.clear()


def test_ops_traffic_human_landing_no_telegram():
    client = TestClient(app)
    settings = MagicMock(auth_secret="test-secret", telegram_notify_signup=True)
    db = MagicMock()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = _override_db(db)
    try:
        with patch("app.api.ops_routes.log_event") as log_event:
            res = client.post(
                "/ops/traffic",
                headers={
                    "Authorization": "Bearer test-secret",
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Safari/605.1.15"
                    ),
                },
                json={
                    "kind": "ad_landing",
                    "rdt_cid": "abc123",
                    "utm_source": "reddit",
                    "utm_campaign": "launch1",
                    "path": "/start",
                },
            )
            assert res.status_code == 200
            body = res.json()
            assert body["bot"] is False
            assert body["telegram"] is False
            assert log_event.called
            assert log_event.call_args.kwargs["telegram"] is False
    finally:
        app.dependency_overrides.clear()
