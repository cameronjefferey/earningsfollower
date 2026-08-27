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
    _ensure_user_columns()
    _ensure_trade_decision_columns()
    _backfill_paper_trade_max_risk()
    _seed_trade_decisions()


# Columns added to paper_trades after its initial release. SQLAlchemy's
# create_all won't ALTER an existing table, and there's no Alembic here, so we
# add any missing columns idempotently (safe on SQLite and Postgres).
_PAPER_TRADE_ADDED_COLUMNS = {
    "strategy": "VARCHAR(16) DEFAULT 'earnings'",
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


# Columns added to trade_decisions after the feature journal first shipped
# (size/liquidity + the fitted entry model's probability).
_TRADE_DECISION_ADDED_COLUMNS = {
    "market_cap": "FLOAT",
    "avg_volume": "FLOAT",
    "dollar_volume": "FLOAT",
    "rel_volume": "FLOAT",
    "realized_vol_20d": "FLOAT",
    "trend_60d": "FLOAT",
    "up_rate": "FLOAT",
    "last_move_pct": "FLOAT",
    "beat_rate": "FLOAT",
    "continuation_rate": "FLOAT",
    "analyst_upside": "FLOAT",
    "analyst_bullish_pct": "FLOAT",
    "days_to_event": "INTEGER",
    "earnings_timing": "VARCHAR(16)",
    "model_win_prob": "FLOAT",
}


def _ensure_trade_decision_columns() -> None:
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "trade_decisions" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("trade_decisions")}
    missing = {
        col: typ
        for col, typ in _TRADE_DECISION_ADDED_COLUMNS.items()
        if col not in existing
    }
    if not missing:
        return
    with engine.begin() as conn:
        for col, typ in missing.items():
            conn.execute(text(f"ALTER TABLE trade_decisions ADD COLUMN {col} {typ}"))


# Columns added to users after Google-only auth shipped.
_USER_ADDED_COLUMNS = {
    "password_hash": "VARCHAR(255)",
    "email_verified_at": "TIMESTAMP",
    "wave_alerts": "BOOLEAN DEFAULT TRUE",
}


def _ensure_user_columns() -> None:
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("users")}
    missing = {
        col: typ
        for col, typ in _USER_ADDED_COLUMNS.items()
        if col not in existing
    }
    if not missing:
        return
    with engine.begin() as conn:
        for col, typ in missing.items():
            conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {typ}"))


def _backfill_paper_trade_max_risk() -> None:
    """Heal historical paper_trades whose stored max_risk was modeled off the mid
    credit at record time instead of the actual fill. Idempotent: re-derives each
    row's max loss from its booked entry price and only writes the ones that
    disagree, so it's a no-op once corrected (safe to run on every startup)."""
    import logging

    from app.db.models import PaperTrade
    from app.services.paper.risk import defined_risk_max_loss

    with SessionLocal() as db:
        trades = db.query(PaperTrade).all()
        changed = 0
        for t in trades:
            correct = defined_risk_max_loss(
                t.strategy, t.width, t.entry_credit, t.contracts
            )
            if correct is not None and correct != t.max_risk:
                t.max_risk = correct
                changed += 1
        if changed:
            db.commit()
            logging.getLogger("earningsfollower").info(
                "Backfilled max_risk on %d paper trade(s).", changed
            )


def _seed_trade_decisions() -> None:
    """Keep the trade_decisions journal caught up with paper_trades.

    Idempotent: only inserts rows for signal_ids that aren't journaled yet, then
    labels anything that's since closed. Used to run only when the table was
    empty, which left the learning loop blind to history once a single live
    decision had been written. Cheap no-op when already caught up."""
    import logging

    from app.db.models import PaperTrade

    with SessionLocal() as db:
        try:
            from sqlalchemy import func, select as sel

            if not db.scalar(sel(func.count()).select_from(PaperTrade)):
                return
            from app.services.paper.decisions import (
                backfill_from_paper_trades,
                sync_labels,
            )

            created = backfill_from_paper_trades(db)
            if created:
                db.commit()
            labeled = sync_labels(db)
            if created or labeled:
                db.commit()
            if created:
                logging.getLogger("earningsfollower").info(
                    "Backfilled %d trade decision(s) from paper history.", created
                )
        except Exception as e:  # noqa: BLE001 - seeding must never block startup
            db.rollback()
            logging.getLogger("earningsfollower").warning(
                "trade_decisions seed skipped: %s", e
            )


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
