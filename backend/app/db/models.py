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
    Text,
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


class TradeDecision(Base):
    """A flat, append-only feature/label store for the paper trader's decisions.

    One row per (strategy, ticker, event) decision the executor makes on a scan -
    both trades it OPENED and setups it SKIPPED - so we can later learn which
    signals actually predict winners without survivorship bias (the skips are the
    counterfactuals). Unlike ``PaperTrade.thesis`` (a truncated JSON blob), every
    signal that drove the decision is promoted to a typed column so it can be
    grouped/filtered/regressed directly in SQL or handed to a model.

    Design notes ("build it right"):
      - Immutable at decision time: features are snapshotted when the call is made,
        never rewritten. Only the *label* columns are filled in later (at exit).
      - Regime-versioned: ``playbook_version`` + ``regime_json`` capture the code
        version and the tunable knobs in force, so a P&L shift can be attributed
        to signal edge vs. a config change.
      - Multi-horizon labels: the underlying's move at +1d / +5d is stored
        alongside the at-exit realized P&L, so signal quality (was the lean right?)
        is separable from exit-policy quality (did we harvest it well?).
      - Wide + sparse on purpose: strategy-specific columns are nullable and only
        filled for the strategy they belong to. ``features_json`` keeps the full,
        untruncated feature dict for auditing / the long tail.
    """

    __tablename__ = "trade_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
    decision_date: Mapped[date] = mapped_column(Date, index=True)
    strategy: Mapped[str] = mapped_column(String(16), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    earnings_date: Mapped[date | None] = mapped_column(Date)
    # "opened" (a trade was placed) or "skipped" (rejected on this scan).
    decision: Mapped[str] = mapped_column(String(16), index=True)
    # Why it was skipped (None for opened) - the executor's own reason string.
    skip_reason: Mapped[str | None] = mapped_column(String(256))
    # Links an "opened" decision to its PaperTrade (for label sync). Not unique:
    # a ticker can be skipped many times before it ever opens.
    signal_id: Mapped[str | None] = mapped_column(String(32), index=True)

    # Regime: what code + knobs produced this decision.
    playbook_version: Mapped[str] = mapped_column(String(16), default="1")
    regime_json: Mapped[str | None] = mapped_column(Text)

    # --- Common signal features ---------------------------------------------
    direction: Mapped[str | None] = mapped_column(String(16))
    vol_stance: Mapped[str | None] = mapped_column(String(16))
    structure: Mapped[str | None] = mapped_column(String(64))
    conviction: Mapped[str | None] = mapped_column(String(16))
    conviction_reason: Mapped[str | None] = mapped_column(String(256))
    # The win probability actually fed to the EV gate (the model's own belief),
    # so realized outcome vs. this gives calibration directly, across strategies.
    win_prob: Mapped[float | None] = mapped_column(Float)
    expected_move_pct: Mapped[float | None] = mapped_column(Float)
    spot: Mapped[float | None] = mapped_column(Float)
    # Modeled trade shape (mid), before the fill: credit for sell-vol, debit for
    # the directional books. Width/contracts/max_risk describe the sizing.
    modeled_price: Mapped[float | None] = mapped_column(Float)
    width: Mapped[float | None] = mapped_column(Float)
    contracts: Mapped[int | None] = mapped_column(Integer)
    max_risk: Mapped[float | None] = mapped_column(Float)
    risk_frac: Mapped[float | None] = mapped_column(Float)
    equity_at_decision: Mapped[float | None] = mapped_column(Float)

    # --- Earnings (sell-vol) features ---------------------------------------
    dir_score: Mapped[float | None] = mapped_column(Float)
    seller_edge: Mapped[float | None] = mapped_column(Float)
    seller_edge_at_strike: Mapped[float | None] = mapped_column(Float)
    exceed_rate: Mapped[float | None] = mapped_column(Float)
    edge_sample: Mapped[int | None] = mapped_column(Integer)
    richness: Mapped[float | None] = mapped_column(Float)
    data_suspect: Mapped[bool | None] = mapped_column(Boolean)

    # --- Waves (sympathy) features ------------------------------------------
    trigger: Mapped[str | None] = mapped_column(String(16))
    trigger_move_pct: Mapped[float | None] = mapped_column(Float)
    expected_runup_pct: Mapped[float | None] = mapped_column(Float)

    # --- Drift (PEAD) features ----------------------------------------------
    surprise_pct: Mapped[float | None] = mapped_column(Float)
    move_pct: Mapped[float | None] = mapped_column(Float)
    drift_edge_5d: Mapped[float | None] = mapped_column(Float)
    drift_score: Mapped[float | None] = mapped_column(Float)

    # --- Waves/Drift shared history edge (win rate + sample size) -----------
    hist_win_rate: Mapped[float | None] = mapped_column(Float)
    hist_samples: Mapped[int | None] = mapped_column(Integer)

    # --- Reddit (social) features -------------------------------------------
    sentiment: Mapped[float | None] = mapped_column(Float)
    mention_count: Mapped[int | None] = mapped_column(Integer)
    mention_velocity: Mapped[float | None] = mapped_column(Float)
    pump_risk: Mapped[str | None] = mapped_column(String(8))
    scored_by: Mapped[str | None] = mapped_column(String(16))

    # Full, untruncated feature dict for auditing and the long tail.
    features_json: Mapped[str | None] = mapped_column(Text)

    # --- Labels (filled in later by sync_labels, from the linked PaperTrade
    #     and price bars). "pending" until the trade closes, then "final". -----
    label_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    outcome: Mapped[str | None] = mapped_column(String(16))
    realized_pnl: Mapped[float | None] = mapped_column(Float)
    realized_move_pct: Mapped[float | None] = mapped_column(Float)
    breached_short: Mapped[bool | None] = mapped_column(Boolean)
    # Underlying move from entry at fixed horizons (signed, and direction-adjusted
    # so positive = the trade's thesis was right regardless of long/short).
    move_1d: Mapped[float | None] = mapped_column(Float)
    move_5d: Mapped[float | None] = mapped_column(Float)
    fav_move_1d: Mapped[float | None] = mapped_column(Float)
    fav_move_5d: Mapped[float | None] = mapped_column(Float)
    labels_updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class RefreshLog(Base):
    __tablename__ = "refresh_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default="running")
    detail: Mapped[str | None] = mapped_column(String(1024))


class JobRunLog(Base):
    """Persisted cron/job outcomes so we can heartbeat and surface last-run status."""

    __tablename__ = "job_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(32), index=True)  # paper | refresh
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    opened: Mapped[int] = mapped_column(Integer, default=0)
    closed: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)


class BoardSnapshot(Base):
    """Persisted Waves/Drift board payloads so paid pages serve instantly."""

    __tablename__ = "board_snapshots"
    __table_args__ = (UniqueConstraint("kind", "params_key", name="uq_board_snapshot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # waves | drift
    params_key: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DailyDigest(Base):
    """One row per calendar day: 'what changed' bullets for the homepage."""

    __tablename__ = "daily_digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    digest_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    """App account (Google, email/password, or magic link); Stripe owns subscription state."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    image: Mapped[str | None] = mapped_column(String(512))
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    # bcrypt hash; null for Google-only / magic-link-only accounts until they set one.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    # none | active | trialing | past_due | canceled | unpaid | incomplete | ...
    subscription_status: Mapped[str] = mapped_column(String(32), default="none", index=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AuthToken(Base):
    """One-time tokens for magic login, password reset, and email verify."""

    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    # magic_login | password_reset | email_verify
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AppEvent(Base):
    """Ops timeline for the admin dashboard (signups, Stripe, contact, etc.)."""

    __tablename__ = "app_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    message: Mapped[str] = mapped_column(Text)
    meta_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
