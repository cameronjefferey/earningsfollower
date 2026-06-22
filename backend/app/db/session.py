from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()


def _normalize_db_url(url: str) -> str:
    # Render (and some hosts) hand out the deprecated "postgres://" scheme, which
    # SQLAlchemy 2.x no longer accepts; rewrite it to the canonical driver URL.
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url


DATABASE_URL = _normalize_db_url(_settings.database_url)

# check_same_thread is only relevant for SQLite; harmless to pass for others.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create all tables. Imported here to avoid circular imports."""
    from app.db import models  # noqa: F401

    models.Base.metadata.create_all(bind=engine)
    _ensure_paper_trade_columns()


# Columns added to paper_trades after its initial release. SQLAlchemy's
# create_all won't ALTER an existing table, and there's no Alembic here, so we
# add any missing columns idempotently (safe on SQLite and Postgres).
_PAPER_TRADE_ADDED_COLUMNS = {
    "modeled_credit": "FLOAT",
    "expected_move_pct": "FLOAT",
    "spot_entry": "FLOAT",
    "equity_at_entry": "FLOAT",
    "spot_at_exit": "FLOAT",
    "realized_move_pct": "FLOAT",
    "breached_short": "BOOLEAN",
    "outcome": "VARCHAR(16)",
}


def _ensure_paper_trade_columns() -> None:
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "paper_trades" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("paper_trades")}
    missing = {
        col: typ
        for col, typ in _PAPER_TRADE_ADDED_COLUMNS.items()
        if col not in existing
    }
    if not missing:
        return
    with engine.begin() as conn:
        for col, typ in missing.items():
            conn.execute(text(f"ALTER TABLE paper_trades ADD COLUMN {col} {typ}"))


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for use outside request handlers (jobs, scripts)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
