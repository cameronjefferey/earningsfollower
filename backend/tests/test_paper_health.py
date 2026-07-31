"""Paper-run health: unhealthy results must fail the cron loudly."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper.health import (  # noqa: E402
    collect_anomalies,
    refresh_is_unhealthy,
    run_is_unhealthy,
)


def test_ok_run_is_healthy():
    result = {"status": "ok", "opened": 0, "skipped": [], "errors": []}
    assert collect_anomalies(result) == []
    assert run_is_unhealthy(result) is False


def test_error_status_is_unhealthy():
    assert run_is_unhealthy({"status": "error", "errors": ["boom"]}) is True


def test_disabled_is_unhealthy():
    assert run_is_unhealthy({"status": "disabled", "reason": "no Alpaca credentials"}) is True


def test_errors_list_is_unhealthy_even_if_status_ok():
    assert run_is_unhealthy({"status": "ok", "errors": ["waves: alpaca blew up"]}) is True


def test_failed_telegram_trade_alert_is_unhealthy():
    result = {
        "status": "ok",
        "errors": [],
        "telegram": {"attempted": True, "ok": False, "opened": 0, "closed": 2},
    }
    anomalies = collect_anomalies(result)
    assert any("Telegram trade alert FAILED" in a for a in anomalies)
    assert run_is_unhealthy(result, anomalies) is True


def test_stale_heartbeat_is_anomaly():
    anomalies = collect_anomalies({}, stale_healthy_minutes=120)
    assert any("stale heartbeat" in a for a in anomalies)


def test_refresh_partial_is_unhealthy():
    assert refresh_is_unhealthy({"status": "partial", "errors": []}) is True
    assert refresh_is_unhealthy({"status": "ok", "boards_error": "boom"}) is True
    assert refresh_is_unhealthy({"status": "ok", "errors": []}) is False
