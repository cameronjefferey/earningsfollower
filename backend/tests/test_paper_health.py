"""Paper-run health: unhealthy results must fail the cron loudly."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper.health import (  # noqa: E402
    collect_anomalies,
    heartbeat_is_stale,
    previous_paper_cron_slot,
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


def test_overnight_gap_is_not_a_missed_cron():
    # First weekday fire (13:00 UTC / 6am PT) after yesterday's last slot (20:30).
    now = datetime(2026, 8, 28, 13, 0, 5)  # Friday
    assert previous_paper_cron_slot(now) == datetime(2026, 8, 27, 20, 30)
    last = datetime(2026, 8, 27, 20, 32)
    assert heartbeat_is_stale(last, now) is False


def test_weekend_gap_is_not_a_missed_cron():
    now = datetime(2026, 8, 31, 13, 0, 5)  # Monday
    assert previous_paper_cron_slot(now) == datetime(2026, 8, 28, 20, 30)
    last = datetime(2026, 8, 28, 20, 31)
    assert heartbeat_is_stale(last, now) is False


def test_missed_intraday_slots_are_stale():
    now = datetime(2026, 8, 27, 15, 30, 5)
    last = datetime(2026, 8, 27, 13, 1)  # last ok at 13:00; missed 13:30–15:00
    assert previous_paper_cron_slot(now) == datetime(2026, 8, 27, 15, 0)
    assert heartbeat_is_stale(last, now) is True


def test_refresh_partial_is_unhealthy():
    assert refresh_is_unhealthy({"status": "partial", "errors": []}) is True
    assert refresh_is_unhealthy({"status": "ok", "boards_error": "boom"}) is True
    assert refresh_is_unhealthy({"status": "ok", "errors": []}) is False


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
