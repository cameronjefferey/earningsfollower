from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(128))
    industry: Mapped[str | None] = mapped_column(String(128))
    exchange: Mapped[str | None] = mapped_column(String(32))
    market_cap: Mapped[float | None] = mapped_column(Float)
    image: Mapped[str | None] = mapped_column(String(512))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    themes: Mapped[list["ThemeMembership"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class ThemeMembership(Base):
    __tablename__ = "theme_memberships"
    __table_args__ = (UniqueConstraint("ticker", "theme_key", name="uq_theme_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(
        ForeignKey("companies.ticker", ondelete="CASCADE"), index=True
    )
    theme_key: Mapped[str] = mapped_column(String(64), index=True)
    theme_label: Mapped[str] = mapped_column(String(128))
    # True when the ticker was explicitly listed in universe.yaml (vs. peer-expanded).
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)

    company: Mapped[Company] = relationship(back_populates="themes")


class EarningsEvent(Base):
    __tablename__ = "earnings_events"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_earnings_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    # "bmo" (before market open), "amc" (after market close), or "unknown".
    timing: Mapped[str] = mapped_column(String(16), default="unknown")
    eps_estimate: Mapped[float | None] = mapped_column(Float)
    eps_actual: Mapped[float | None] = mapped_column(Float)
    revenue_estimate: Mapped[float | None] = mapped_column(Float)
    revenue_actual: Mapped[float | None] = mapped_column(Float)
    fiscal_period: Mapped[str | None] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("ticker", "date", name="uq_price_bar"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)


class PeerLink(Base):
    __tablename__ = "peer_links"
    __table_args__ = (UniqueConstraint("ticker", "peer", name="uq_peer_link"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    peer: Mapped[str] = mapped_column(String(16), index=True)


class ImpliedMove(Base):
    __tablename__ = "implied_moves"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    expiry: Mapped[date | None] = mapped_column(Date)
    underlying_price: Mapped[float | None] = mapped_column(Float)
    atm_strike: Mapped[float | None] = mapped_column(Float)
    straddle_price: Mapped[float | None] = mapped_column(Float)
    expected_move_pct: Mapped[float | None] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ImpliedMoveSnapshot(Base):
    """Point-in-time implied move logged each refresh, keyed to the upcoming
    earnings event. Lets us later compare what was priced in vs. the realized
    move once the event has passed (true implied-vs-realized accuracy)."""

    __tablename__ = "implied_move_snapshots"
    __table_args__ = (
        UniqueConstraint("ticker", "event_date", "snapshot_date", name="uq_im_snapshot"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date)
    expected_move_pct: Mapped[float | None] = mapped_column(Float)
    underlying_price: Mapped[float | None] = mapped_column(Float)


class AnalystSnapshot(Base):
    """Latest analyst price target + recommendation breakdown from FMP."""

    __tablename__ = "analyst_snapshots"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    price_target: Mapped[float | None] = mapped_column(Float)
    price_target_high: Mapped[float | None] = mapped_column(Float)
    price_target_low: Mapped[float | None] = mapped_column(Float)
    strong_buy: Mapped[int | None] = mapped_column(Integer)
    buy: Mapped[int | None] = mapped_column(Integer)
    hold: Mapped[int | None] = mapped_column(Integer)
    sell: Mapped[int | None] = mapped_column(Integer)
    strong_sell: Mapped[int | None] = mapped_column(Integer)
    # Net bullish count (strong_buy+buy) from ~3 months earlier, for trend.
    prev_bullish: Mapped[int | None] = mapped_column(Integer)
    eps_estimate_next: Mapped[float | None] = mapped_column(Float)
    revenue_estimate_next: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PaperTrade(Base):
    """A paper earnings trade placed on Alpaca from the playbook engine.

    Stores the full thesis and the chosen option legs so every fill is
    journalable (the `signal_id` is the unique tag to cross-reference elsewhere).
    """

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # Which strategy placed this:
    #   "earnings" - sell-vol around the print (IV crush)
    #   "waves"    - directional sympathy drift into a peer-driven build-up
    #   "drift"    - post-earnings announcement drift (PEAD)
    #   "reddit"   - social-attention sentiment from monitoring Reddit
    strategy: Mapped[str] = mapped_column(String(16), default="earnings", index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    earnings_date: Mapped[date | None] = mapped_column(Date, index=True)

    # Playbook snapshot at entry.
    structure: Mapped[str] = mapped_column(String(64))
    direction: Mapped[str] = mapped_column(String(16))
    vol_stance: Mapped[str] = mapped_column(String(16))
    conviction: Mapped[str] = mapped_column(String(16))
    thesis: Mapped[str | None] = mapped_column(String(2048))  # JSON

    # Execution.
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    legs: Mapped[str | None] = mapped_column(String(2048))  # JSON of leg dicts
    contracts: Mapped[int | None] = mapped_column(Integer)
    expiration: Mapped[date | None] = mapped_column(Date)
    width: Mapped[float | None] = mapped_column(Float)
    entry_credit: Mapped[float | None] = mapped_column(Float)  # per share (actual fill)
    modeled_credit: Mapped[float | None] = mapped_column(Float)  # per share (mid at entry)
    exit_debit: Mapped[float | None] = mapped_column(Float)    # per share
    max_risk: Mapped[float | None] = mapped_column(Float)      # total $ at risk
    realized_pnl: Mapped[float | None] = mapped_column(Float)  # total $

    # Entry-time conditions (features for later calibration/training).
    expected_move_pct: Mapped[float | None] = mapped_column(Float)  # implied move at entry
    spot_entry: Mapped[float | None] = mapped_column(Float)
    equity_at_entry: Mapped[float | None] = mapped_column(Float)

    # Realized outcome (labels), captured at exit.
    spot_at_exit: Mapped[float | None] = mapped_column(Float)
    realized_move_pct: Mapped[float | None] = mapped_column(Float)  # signed, entry->exit
    breached_short: Mapped[bool | None] = mapped_column(Boolean)    # price crossed a short strike
    outcome: Mapped[str | None] = mapped_column(String(16))         # "win" | "loss"

    entry_order_id: Mapped[str | None] = mapped_column(String(64))
    exit_order_id: Mapped[str | None] = mapped_column(String(64))

    opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class RedditSignal(Base):
    """A scored, per-ticker snapshot of Reddit chatter from one scan.

    Every scan journals one row per qualifying ticker so the social signal is
    fully auditable: how many mentions, how fast they're accelerating, the
    sentiment verdict and who scored it (LLM vs. heuristic), the pump-risk read,
    and a few sample permalinks to eyeball the source. The Reddit paper strategy
    reads the freshest rows to decide what to trade.
    """

    __tablename__ = "reddit_signals"
    __table_args__ = (
        UniqueConstraint("scan_date", "ticker", name="uq_reddit_signal"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_date: Mapped[date] = mapped_column(Date, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    # Mentions this scan as a multiple of the ticker's trailing baseline.
    mention_velocity: Mapped[float | None] = mapped_column(Float)
    # Composite attention*sentiment score used to rank/size.
    score: Mapped[float | None] = mapped_column(Float)
    # Signed mean sentiment in [-1, 1] (positive = bullish chatter).
    sentiment: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(16), default="neutral")
    conviction: Mapped[str] = mapped_column(String(16), default="low")
    pump_risk: Mapped[str] = mapped_column(String(8), default="low")
    is_noise: Mapped[bool] = mapped_column(Boolean, default=False)
    scored_by: Mapped[str] = mapped_column(String(16), default="heuristic")
    rationale: Mapped[str | None] = mapped_column(String(1024))
    subreddits: Mapped[str | None] = mapped_column(String(256))  # csv
    samples: Mapped[str | None] = mapped_column(String(1024))    # JSON of permalinks
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class RefreshLog(Base):
    __tablename__ = "refresh_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default="running")
    detail: Mapped[str | None] = mapped_column(String(1024))
