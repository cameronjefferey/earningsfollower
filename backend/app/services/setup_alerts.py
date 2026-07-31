"""Telegram alerts when Waves/Drift boards gain new setups after refresh."""

from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.services.notify import send_telegram, telegram_configured

logger = logging.getLogger(__name__)


def _targets_from_waves(payload: dict | None) -> set[str]:
    if not payload:
        return set()
    from app.services.waves import filter_by_min_peers

    return {
        str(s.get("target") or "").upper()
        for s in filter_by_min_peers(list(payload.get("signals") or []))
        if s.get("target")
    }


def _tickers_from_drift(payload: dict | None) -> set[str]:
    if not payload:
        return set()
    return {
        str(s.get("ticker") or "").upper()
        for s in (payload.get("setups") or [])
        if s.get("ticker")
    }


def notify_new_setups(
    *,
    prev_waves: dict | None,
    prev_drift: dict | None,
    new_waves: dict,
    new_drift: dict,
    settings: Settings | None = None,
) -> bool:
    """Ping Telegram when new wave targets or drift tickers appear."""
    settings = settings or get_settings()
    if not getattr(settings, "telegram_notify_setups", True):
        return False
    if not telegram_configured():
        return False

    # First snapshot after deploy isn't "new" — only alert on subsequent diffs.
    if prev_waves is None and prev_drift is None:
        return False

    new_wave_targets = sorted(_targets_from_waves(new_waves) - _targets_from_waves(prev_waves))
    new_drift_tickers = sorted(_tickers_from_drift(new_drift) - _tickers_from_drift(prev_drift))
    if not new_wave_targets and not new_drift_tickers:
        return False

    base = (settings.public_app_url or "").rstrip("/") or "https://www.earningsfollower.com"
    lines = ["earningsfollower — new research setups"]
    if new_wave_targets:
        lines.append(
            "Waves: " + ", ".join(new_wave_targets[:12])
            + (f" (+{len(new_wave_targets) - 12} more)" if len(new_wave_targets) > 12 else "")
        )
    if new_drift_tickers:
        lines.append(
            "Drift: " + ", ".join(new_drift_tickers[:12])
            + (f" (+{len(new_drift_tickers) - 12} more)" if len(new_drift_tickers) > 12 else "")
        )
    lines.append(f"Brief: {base}/brief")
    lines.append(f"Setups: {base}/setups")

    ok = send_telegram("\n".join(lines))
    if ok:
        logger.info(
            "Setup alert sent: +%d waves +%d drift",
            len(new_wave_targets),
            len(new_drift_tickers),
        )
    return ok
