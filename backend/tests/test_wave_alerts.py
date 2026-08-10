"""Tests for wave alert email summarization, diffing, and unsubscribe signing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import wave_alerts


def _signal(
    trigger: str,
    target: str,
    *,
    move: float | None = 0.05,
    expected: float | None = 0.03,
    win: float = 0.7,
    n: int = 6,
    score: float = 0.02,
) -> dict:
    return {
        "trigger": trigger,
        "trigger_name": None,
        "trigger_report_date": "2026-08-05",
        "trigger_move_pct": move,
        "trigger_beat": True,
        "target": target,
        "target_name": f"{target} Inc",
        "target_report_date": "2026-08-12",
        "shared_themes": [{"key": "ai_tech", "label": "AI / Tech"}],
        "direction": "bullish",
        "expected_runup_pct": expected,
        "stats": {
            "trigger": trigger,
            "target": target,
            "sample_size": n,
            "avg_runup_pct": expected,
            "win_rate": win,
            "score": score,
        },
    }


def _payload(signals: list[dict]) -> dict:
    return {"signals": signals}


def test_summarize_groups_by_target_and_counts_rips():
    payload = _payload(
        [
            _signal("NVDA", "AMD", move=0.062),
            _signal("AVGO", "AMD", move=0.041),
            _signal("MU", "AMD", move=-0.02),
            # Single-peer target gets dropped by the min-peers filter.
            _signal("XYZ", "LONE"),
        ]
    )
    out = wave_alerts.summarize_wave_targets(payload)
    assert [w["target"] for w in out] == ["AMD"]
    amd = out[0]
    assert amd["peer_count"] == 3
    assert amd["ripped_count"] == 2  # NVDA and AVGO cleared RIP_MOVE_PCT; MU fell
    assert amd["target_report_date"] == "2026-08-12"
    assert amd["themes"] == ["AI / Tech"]
    assert amd["avg_expected_runup_pct"] is not None


def test_summarize_sorts_ripping_waves_first():
    payload = _payload(
        [
            _signal("A1", "COLD", move=0.0),
            _signal("A2", "COLD", move=-0.01),
            _signal("B1", "HOT", move=0.08),
            _signal("B2", "HOT", move=0.05),
        ]
    )
    out = wave_alerts.summarize_wave_targets(payload)
    assert [w["target"] for w in out] == ["HOT", "COLD"]


def test_unsubscribe_sig_is_stable_and_email_scoped():
    a = wave_alerts.unsubscribe_sig("user@example.com", "secret")
    assert a == wave_alerts.unsubscribe_sig("USER@example.com ", "secret")
    assert a != wave_alerts.unsubscribe_sig("other@example.com", "secret")
    assert a != wave_alerts.unsubscribe_sig("user@example.com", "other-secret")


def _settings(**over) -> MagicMock:
    base = dict(
        email_wave_alerts=True,
        public_app_url="https://www.example.com",
        api_public_url="https://api.example.com",
        auth_secret="s3cret",
    )
    base.update(over)
    return MagicMock(**base)


def test_send_skips_first_snapshot_and_no_diff():
    settings = _settings()
    db = MagicMock()
    new = _payload([_signal("NVDA", "AMD"), _signal("AVGO", "AMD")])
    with patch.object(wave_alerts, "resend_configured", return_value=True), patch.object(
        wave_alerts, "send_email", return_value=True
    ) as send:
        # First snapshot after deploy: everything looks new, alert on nothing.
        assert wave_alerts.send_wave_alert_emails(
            db, prev_waves=None, new_waves=new, settings=settings
        ) == 0
        # Same board twice: no new targets, no email.
        assert wave_alerts.send_wave_alert_emails(
            db, prev_waves=new, new_waves=new, settings=settings
        ) == 0
        send.assert_not_called()


def test_send_emails_new_targets_to_subscribers():
    settings = _settings()
    prev = _payload([_signal("NVDA", "AMD"), _signal("AVGO", "AMD")])
    new = _payload(
        [
            _signal("NVDA", "AMD"),
            _signal("AVGO", "AMD"),
            _signal("LRCX", "KLAC", move=0.07),
            _signal("AMAT", "KLAC", move=0.04),
        ]
    )
    user = MagicMock(email="pro@example.com")
    db = MagicMock()
    with patch.object(wave_alerts, "resend_configured", return_value=True), patch.object(
        wave_alerts, "_recipients", return_value=[user]
    ), patch.object(wave_alerts, "send_email", return_value=True) as send:
        sent = wave_alerts.send_wave_alert_emails(
            db, prev_waves=prev, new_waves=new, settings=settings
        )
    assert sent == 1
    kwargs = send.call_args.kwargs
    assert kwargs["to"] == "pro@example.com"
    assert "KLAC" in kwargs["subject"]
    assert "AMD" not in kwargs["subject"]  # already on the board, not "new"
    assert "unsubscribe" in kwargs["text"].lower() or "Turn off" in kwargs["text"]
    assert "/waves/alerts/unsubscribe" in kwargs["text"]


def test_send_respects_kill_switch():
    settings = _settings(email_wave_alerts=False)
    db = MagicMock()
    with patch.object(wave_alerts, "send_email", return_value=True) as send:
        assert (
            wave_alerts.send_wave_alert_emails(
                db, prev_waves={}, new_waves=_payload([]), settings=settings
            )
            == 0
        )
        send.assert_not_called()
