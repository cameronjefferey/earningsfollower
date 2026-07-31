"""Make paper-run failures loud.

The cron used to exit 0 even when Alpaca blew up mid-scan (BRK-B), so Render
reported success and nobody got pinged. This module decides when a run is
unhealthy and formats the alert.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.services.notify import send_telegram, telegram_configured


def run_is_unhealthy(result: dict[str, Any]) -> bool:
    """True when the process should fail the cron / page a human."""
    status = result.get("status")
    if status in ("error", "disabled"):
        return True
    if result.get("errors"):
        return True
    return False


def notify_paper_health(result: dict[str, Any], settings: Settings | None = None) -> bool:
    """Telegram a short failure note. No-op if unconfigured or healthy."""
    settings = settings or get_settings()
    if not getattr(settings, "telegram_notify_paper_health", True):
        return False
    if not telegram_configured():
        return False
    if not run_is_unhealthy(result):
        return False

    status = result.get("status") or "unknown"
    errors = [str(e) for e in (result.get("errors") or [])][:5]
    opened = result.get("opened", 0)
    skipped_n = len(result.get("skipped") or [])
    lines = [
        "earningsfollower — paper run unhealthy",
        f"status: {status}",
        f"opened: {opened}  skipped: {skipped_n}",
    ]
    if result.get("equity") is not None:
        lines.append(f"equity: {result['equity']}")
    if result.get("market_open") is not None:
        lines.append(f"market_open: {result['market_open']}")
    if errors:
        lines.append("errors:")
        for e in errors:
            lines.append(f"  • {e[:240]}")
    else:
        reason = result.get("reason")
        if reason:
            lines.append(f"reason: {reason}")
    return send_telegram("\n".join(lines))
