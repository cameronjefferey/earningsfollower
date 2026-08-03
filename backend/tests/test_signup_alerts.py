"""Tests for signup-funnel Telegram alert debounce."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import signup_alerts


def test_notify_signup_debounces_same_key():
    signup_alerts._last_sent.clear()
    settings = MagicMock(
        telegram_notify_signup=True,
        telegram_bot_token="t",
        telegram_chat_id="1",
    )
    with patch.object(signup_alerts, "telegram_configured", return_value=True), patch.object(
        signup_alerts, "send_telegram", return_value=True
    ) as send:
        assert signup_alerts.notify_signup(
            "auth_fail",
            "first",
            debounce_key="auth_fail:InvalidCheck",
            debounce_s=600,
            settings=settings,
        )
        assert not signup_alerts.notify_signup(
            "auth_fail",
            "second",
            debounce_key="auth_fail:InvalidCheck",
            debounce_s=600,
            settings=settings,
        )
        assert send.call_count == 1


def test_notify_signup_skips_when_disabled():
    signup_alerts._last_sent.clear()
    settings = MagicMock(telegram_notify_signup=False)
    with patch.object(signup_alerts, "telegram_configured", return_value=True), patch.object(
        signup_alerts, "send_telegram", return_value=True
    ) as send:
        assert not signup_alerts.notify_signup(
            "new_sub", "New Pro: a@b.com", settings=settings
        )
        send.assert_not_called()


def test_notify_signup_zero_debounce_always_sends():
    signup_alerts._last_sent.clear()
    settings = MagicMock(telegram_notify_signup=True)
    with patch.object(signup_alerts, "telegram_configured", return_value=True), patch.object(
        signup_alerts, "send_telegram", return_value=True
    ) as send:
        assert signup_alerts.notify_signup(
            "new_sub",
            "New Pro: a@b.com",
            debounce_key="new_sub:a@b.com",
            debounce_s=0,
            settings=settings,
        )
        assert signup_alerts.notify_signup(
            "new_sub",
            "New Pro: a@b.com again",
            debounce_key="new_sub:a@b.com",
            debounce_s=0,
            settings=settings,
        )
        assert send.call_count == 2
