"""Paper-run health: unhealthy results must fail the cron loudly."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper.health import run_is_unhealthy  # noqa: E402


def test_ok_run_is_healthy():
    assert run_is_unhealthy({"status": "ok", "opened": 0, "skipped": [], "errors": []}) is False


def test_error_status_is_unhealthy():
    assert run_is_unhealthy({"status": "error", "errors": ["boom"]}) is True


def test_disabled_is_unhealthy():
    assert run_is_unhealthy({"status": "disabled", "reason": "no Alpaca credentials"}) is True


def test_errors_list_is_unhealthy_even_if_status_ok():
    assert run_is_unhealthy({"status": "ok", "errors": ["waves: alpaca blew up"]}) is True
