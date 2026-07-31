"""Persist cron/job outcomes for heartbeat + UI last-run status."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import JobRunLog


def record_job_run(
    db: Session,
    *,
    job: str,
    started_at: datetime,
    result: dict[str, Any],
) -> JobRunLog:
    status = str(result.get("status") or "unknown")
    errors = result.get("errors") or []
    detail = {
        "status": status,
        "errors": [str(e) for e in errors][:12],
        "opened": result.get("opened"),
        "closed": result.get("closed"),
        "skipped_n": len(result.get("skipped") or []),
        "market_open": result.get("market_open"),
        "equity": result.get("equity"),
        "telegram": result.get("telegram"),
        "reason": result.get("reason"),
        "processed": result.get("processed"),
        "boards": result.get("boards"),
    }
    row = JobRunLog(
        job=job,
        started_at=started_at,
        finished_at=datetime.utcnow(),
        status=status,
        detail=json.dumps(detail, default=str)[:8000],
        opened=int(result.get("opened") or 0),
        closed=int(result.get("closed") or 0),
        error_count=len(errors) if isinstance(errors, list) else 0,
    )
    db.add(row)
    db.commit()
    return row


def latest_job_run(db: Session, job: str) -> JobRunLog | None:
    return db.scalars(
        select(JobRunLog)
        .where(JobRunLog.job == job)
        .order_by(JobRunLog.id.desc())
    ).first()


def latest_healthy_job_run(db: Session, job: str) -> JobRunLog | None:
    return db.scalars(
        select(JobRunLog)
        .where(JobRunLog.job == job, JobRunLog.status == "ok")
        .order_by(JobRunLog.id.desc())
    ).first()


def job_run_payload(row: JobRunLog | None) -> dict[str, Any] | None:
    if row is None:
        return None
    detail: dict[str, Any] = {}
    if row.detail:
        try:
            detail = json.loads(row.detail)
        except json.JSONDecodeError:
            detail = {"raw": row.detail}
    return {
        "id": row.id,
        "job": row.job,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "opened": row.opened,
        "closed": row.closed,
        "error_count": row.error_count,
        "detail": detail,
    }


def minutes_since(row: JobRunLog | None) -> float | None:
    if row is None or row.finished_at is None:
        return None
    return (datetime.utcnow() - row.finished_at).total_seconds() / 60.0


def is_stale(
    row: JobRunLog | None,
    *,
    max_age_minutes: float,
) -> bool:
    age = minutes_since(row)
    if age is None:
        return True
    return age > max_age_minutes
