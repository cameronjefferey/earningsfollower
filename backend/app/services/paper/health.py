"""Make paper-run failures and anomalies loud.

Prefer false positives: better a noisy Telegram than a silent empty book.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services.job_runs import (
    is_stale,
    latest_healthy_job_run,
    latest_job_run,
    minutes_since,
)
from app.services.notify import send_telegram, telegram_configured

# Must match render.yaml earningsfollower-paper: ``*/30 13-20 * * 1-5``.
# First fire 13:00 UTC (6am PT), last fire 20:30 UTC (1:30pm PT). Overnight and
# weekend silence is expected - do not page it as a dead cron.
PAPER_CRON_START_HOUR_UTC = 13
PAPER_CRON_END_HOUR_UTC = 20  # inclusive; 20:00 and 20:30 both fire
PAPER_STALE_MINUTES = 90
# Daily refresh should land every morning; alert if older than ~36h.
REFRESH_STALE_MINUTES = 36 * 60


def _is_paper_cron_slot(dt: datetime) -> bool:
    if dt.weekday() >= 5:
        return False
    if dt.minute not in (0, 30):
        return False
    return PAPER_CRON_START_HOUR_UTC <= dt.hour <= PAPER_CRON_END_HOUR_UTC


def previous_paper_cron_slot(now: datetime) -> datetime:
    """Most recent scheduled paper fire strictly before the current half-hour.

    At 13:00 UTC Tuesday this is Monday 20:30, not "90 minutes ago" - the
    overnight/weekend gap is closed market, not a missed cron.
    """
    t = now.replace(second=0, microsecond=0)
    t = t.replace(minute=30 if t.minute >= 30 else 0)
    t -= timedelta(minutes=30)
    for _ in range(48 * 5):
        if _is_paper_cron_slot(t):
            return t
        t -= timedelta(minutes=30)
    raise RuntimeError("no paper cron slot in the last 5 days")


def heartbeat_is_stale(last_healthy_at: datetime, now: datetime) -> bool:
    """True when a scheduled slot was missed, not when the market was closed."""
    prior = previous_paper_cron_slot(now)
    lag_min = (prior - last_healthy_at).total_seconds() / 60.0
    return lag_min > PAPER_STALE_MINUTES


def collect_anomalies(
    result: dict[str, Any],
    *,
    stale_healthy_minutes: float | None = None,
    never_ran: bool = False,
) -> list[str]:
    """Return human-readable anomaly strings. Empty = healthy enough."""
    anomalies: list[str] = []
    status = result.get("status")
    if status in ("error", "disabled"):
        anomalies.append(f"status={status}")
    if status == "partial":
        anomalies.append("status=partial")
    errors = result.get("errors") or []
    if errors:
        anomalies.append(f"{len(errors)} error(s): {errors[0]}")
    telegram = result.get("telegram") or {}
    if telegram.get("attempted") and not telegram.get("ok"):
        anomalies.append(
            f"Telegram trade alert FAILED "
            f"({telegram.get('opened', 0)} opened / {telegram.get('closed', 0)} closed)"
        )
    if never_ran:
        anomalies.append("no prior healthy paper run on record")
    elif stale_healthy_minutes is not None and stale_healthy_minutes > PAPER_STALE_MINUTES:
        anomalies.append(
            f"stale heartbeat: last healthy paper run {stale_healthy_minutes:.0f}m ago"
        )
    return anomalies


def run_is_unhealthy(result: dict[str, Any], anomalies: list[str] | None = None) -> bool:
    """True when the process should fail the cron / page a human."""
    if anomalies is None:
        anomalies = collect_anomalies(result)
    return bool(anomalies)


def notify_anomalies(
    *,
    title: str,
    anomalies: list[str],
    result: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    if not getattr(settings, "telegram_notify_paper_health", True):
        return False
    if not telegram_configured() or not anomalies:
        return False

    result = result or {}
    lines = [title, *[f"• {a}" for a in anomalies[:12]]]
    if result.get("equity") is not None:
        lines.append(f"equity: {result['equity']}")
    if result.get("market_open") is not None:
        lines.append(f"market_open: {result['market_open']}")
    if result.get("opened") is not None or result.get("closed") is not None:
        lines.append(
            f"opened: {result.get('opened', 0)}  closed: {result.get('closed', 0)}"
        )
    skipped_n = len(result.get("skipped") or [])
    if skipped_n:
        lines.append(f"skipped: {skipped_n}")
        # Surface a few concrete skip reasons - often the real "why empty book".
        reasons: dict[str, int] = {}
        for s in result.get("skipped") or []:
            r = str((s or {}).get("reason") or "unknown")
            # Collapse noisy per-ticker prefixes a bit.
            key = r.split("(", 1)[0].strip()[:80]
            reasons[key] = reasons.get(key, 0) + 1
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:5]
        for reason, n in top:
            lines.append(f"  skip×{n}: {reason}")
    errors = [str(e) for e in (result.get("errors") or [])][:5]
    if errors:
        lines.append("errors:")
        for e in errors:
            lines.append(f"  • {e[:240]}")
    return send_telegram("\n".join(lines))


def notify_paper_health(result: dict[str, Any], settings: Settings | None = None) -> bool:
    anomalies = collect_anomalies(result)
    if not anomalies:
        return False
    return notify_anomalies(
        title="earningsfollower - paper run unhealthy",
        anomalies=anomalies,
        result=result,
        settings=settings,
    )


def paper_heartbeat_anomalies(
    db: Session, *, now: datetime | None = None
) -> list[str]:
    """Call at the *start* of a live paper run to catch missed prior crons.

    Overnight / weekend gaps (last run yesterday 20:30 UTC, first fire 13:00)
    are expected and must not Telegram. A miss *inside* the weekday window
    still pages.
    """
    healthy = latest_healthy_job_run(db, "paper")
    if healthy is None:
        # First ever run after deploy - not an anomaly yet.
        prior = latest_job_run(db, "paper")
        if prior is None:
            return []
        return collect_anomalies({}, never_ran=True)
    finished = healthy.finished_at or healthy.started_at
    if finished is None:
        return []
    now = now or datetime.utcnow()
    if not heartbeat_is_stale(finished, now):
        return []
    age = minutes_since(healthy)
    return collect_anomalies({}, stale_healthy_minutes=age)


def refresh_is_unhealthy(result: dict[str, Any]) -> bool:
    status = result.get("status")
    if status in ("error", "partial", "disabled"):
        return True
    if result.get("errors"):
        return True
    # Board snapshots failing is worth knowing - empty Waves/Brief follow.
    if result.get("boards_error"):
        return True
    return False


def notify_refresh_health(result: dict[str, Any], settings: Settings | None = None) -> bool:
    anomalies: list[str] = []
    if result.get("status") == "partial":
        anomalies.append("refresh status=partial")
    if result.get("status") == "error":
        anomalies.append("refresh status=error")
    errors = result.get("errors") or []
    if errors:
        anomalies.append(f"{len(errors)} ingest error(s): {errors[0]}")
    if result.get("boards_error"):
        anomalies.append(f"boards/digest failed: {result['boards_error']}")
    no_prices = result.get("no_prices") or []
    no_earnings = result.get("no_earnings") or []
    # Soft gaps among curated names already flip status=partial; still list them.
    if no_prices:
        anomalies.append(f"no_prices×{len(no_prices)}: {','.join(no_prices[:8])}")
    if no_earnings:
        anomalies.append(f"no_earnings×{len(no_earnings)}: {','.join(no_earnings[:8])}")
    if not anomalies:
        return False
    return notify_anomalies(
        title="earningsfollower - refresh unhealthy",
        anomalies=anomalies,
        result=result,
        settings=settings,
    )


def refresh_stale_anomaly(db: Session) -> list[str]:
    healthy = latest_healthy_job_run(db, "refresh")
    if is_stale(healthy, max_age_minutes=REFRESH_STALE_MINUTES):
        age = minutes_since(healthy)
        if age is None:
            return ["no healthy refresh on record"]
        return [f"stale refresh: last healthy run {age / 60:.1f}h ago"]
    return []
