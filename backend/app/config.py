from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    fmp_api_key: str = ""
    database_url: str = "sqlite:///./earningsfollower.db"
    history_years: int = 5
    cors_origins: str = "http://localhost:3000"
    enable_scheduler: bool = True

    # --- Reddit (social sentiment) data --------------------------------------
    # Reads are best-effort. With a Reddit app (client id + secret) we use the
    # OAuth app-only token against oauth.reddit.com (higher, saner rate limits);
    # without one we fall back to the public www.reddit.com/.json endpoints with
    # a descriptive User-Agent. Create a "script"/"web app" credential at
    # https://www.reddit.com/prefs/apps. The whole strategy is gated off by
    # default (see paper_reddit_enabled) so an empty config never trades.
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "earningsfollower/0.1 (reddit-sentiment paper strategy)"

    # --- LLM scorer (optional) ------------------------------------------------
    # An OpenAI-compatible chat endpoint used to score Reddit chatter into a
    # structured (direction, conviction, pump_risk, is_noise) verdict. If no key
    # is set the sentiment service falls back to a transparent keyword heuristic,
    # so the strategy still runs end-to-end without an LLM bill.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    # --- Calendar-driven universe --------------------------------------------
    # Beyond the curated themes, screen the whole market: each refresh pulls the
    # earnings calendar for a window and ingests every liquid name reporting in
    # it, so earnings + PEAD coverage isn't capped at a hand-picked watchlist.
    # (Optionability enforces itself at trade time - the option builders bail on
    # names with no listed contracts - so the screen bar is just price + cap.)
    calendar_universe_enabled: bool = True
    # How far back / forward to scan the calendar. Back must cover the PEAD
    # lookback (~12 trading days) so just-reported names still surface as drift
    # setups; forward is "this week + next" for pre-earnings setups.
    calendar_back_days: int = 16
    calendar_forward_days: int = 14
    # Moderate liquidity bar for a name to be tradeable.
    calendar_min_market_cap: float = 2_000_000_000.0
    calendar_min_price: float = 10.0
    # Cap how many names a single refresh ingests (biggest market caps win), to
    # bound runtime and API spend. Raise once we're comfortable with the load.
    calendar_max_names: int = 300

    # --- Alpaca paper trading -------------------------------------------------
    # Paper accounts get Level 3 (multi-leg) options automatically. These come
    # from a *paper* key pair at https://app.alpaca.markets/paper/dashboard/overview.
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_paper: bool = True
    # Stock market-data feed for live underlying prices. "iex" is free but only
    # reflects IEX trades; "sip" is the full consolidated tape (real-time across
    # all exchanges) and needs a paid Alpaca market-data subscription. We fall
    # back to iex automatically if the chosen feed isn't entitled.
    alpaca_data_feed: str = "iex"
    # Conviction-weighted max-loss per trade, as a fraction of account equity.
    # High conviction risks the most (the ceiling); low risks the least.
    paper_risk_high: float = 0.05
    paper_risk_medium: float = 0.03
    paper_risk_low: float = 0.015
    # Max number of contracts per position (sanity cap).
    paper_max_contracts: int = 25
    # Max simultaneous open paper positions.
    paper_max_open: int = 12
    # Enter a setup only when earnings is within this many calendar days. Wider
    # gets us positioned earlier (more IV to sell, but more days of directional
    # drift before the print).
    paper_entry_window_days: int = 7
    # Floor on the modeled credit (per share) worth trading.
    paper_min_credit: float = 0.10
    # Proactive loss-cutting. Off to start — we exit only after the print and
    # gather data first; flip on once we know stops would have helped. Loss is
    # measured as a fraction of the trade's max risk, evaluated each run (so it's
    # only as timely as the cron cadence).
    paper_stops_enabled: bool = False
    # Hard stop: close any open position once its unrealized loss hits this.
    paper_stop_loss_frac: float = 0.20
    # Near expiry (<= this many days to expiration) tighten to a smaller stop.
    paper_late_dte: int = 1
    paper_late_stop_frac: float = 0.10
    # --- Fills ----------------------------------------------------------------
    # A limit at (or a few pennies off) the mid won't fill a wide, illiquid
    # options spread — we watched JEF/WOR spreads sit unfilled all session. To
    # actually get filled we price at the *marketable cross*: take the ask on
    # legs we buy, hit the bid on legs we sell, plus a small buffer. That fills
    # like a market order but with a sane worst-case price cap (you never pay
    # beyond the displayed ask / receive below the displayed bid). Only orders
    # that fill become tracked positions; unfilled ones don't count.
    paper_fill_cross: bool = True
    # Pennies past the touch (per share of net price) to ensure the cross fills.
    paper_fill_buffer: float = 0.03
    # Only place orders when the market is open (skip the overnight and pre/post-
    # open cron ticks where options can't fill anyway).
    paper_market_hours_only: bool = True

    # --- Waves strategy (directional sympathy drift) --------------------------
    # A separate, directional strategy: when a peer reports, take a directional
    # debit spread on a themed name that reports soon, ride the pre-earnings
    # runup, and exit on an underlying-move bracket or the day before its print.
    # (A debit spread — not a naked long option — keeps high-priced names like
    # TSM/ASML affordable on a small budget and caps the risk.)
    paper_waves_enabled: bool = True
    # Bracket on the *underlying's* move from entry (favorable / adverse).
    paper_wave_gain_pct: float = 0.10
    paper_wave_loss_pct: float = 0.05
    # Quality filters on the historical lead-lag before we'll trade a wave.
    paper_wave_min_winrate: float = 0.60
    paper_wave_min_samples: int = 4
    # Need at least this much runway before the target's own earnings (so there's
    # room to drift, and the exit-before-print rule leaves a real holding period).
    paper_wave_min_runway_days: int = 3
    # Max-loss budget per wave trade, as a fraction of equity, and a position cap.
    paper_wave_risk_frac: float = 0.02
    paper_wave_max_open: int = 6

    # --- Drift (PEAD) strategy ------------------------------------------------
    # Post-earnings announcement drift: after a name reports, beats (or misses)
    # and reacts strongly, it tends to keep drifting in the surprise direction
    # for ~5 trading days. We express that as a directional debit spread (defined
    # risk) and exit on a time horizon, a take-profit, or a broken-thesis stop.
    paper_drift_enabled: bool = True
    # Max-loss budget per drift trade (the net debit), as a fraction of equity.
    paper_drift_risk_frac: float = 0.015
    paper_drift_max_open: int = 8
    # Skip setups weaker than this score (the drift screen's own ranking metric).
    paper_drift_min_score: float = 0.0
    # Close the spread this many calendar days after the report (~5 trading days
    # is the horizon the historical edge is measured over).
    paper_drift_hold_days: int = 7
    # Take profit once the spread is worth this fraction of its max width.
    paper_drift_take_profit: float = 0.75
    # Broken-thesis stop only fires when the underlying is this fraction *beyond*
    # the earnings-day pivot (not just grazing it), so intraday noise around the
    # level doesn't whipsaw a fresh entry into a loss.
    paper_drift_stop_buffer: float = 0.015

    # --- Reddit sentiment strategy --------------------------------------------
    # A fourth, social-attention strategy: monitor Reddit, turn a sustained,
    # directional spike in chatter about a tradeable name into a defined-risk
    # debit spread (bull call / bear put), and exit fast — social attention
    # decays in days, not weeks. OFF by default: flip on only once you've watched
    # the dry-run signal log and are comfortable with what it would have traded.
    paper_reddit_enabled: bool = False
    # Which subreddits to monitor (comma-separated; broad retail + ticker chat).
    reddit_subreddits: str = "wallstreetbets,stocks,options,investing,StockMarket"
    # Per-subreddit listings to pull and how deep, each scan. "hot" + "rising"
    # surface what's gaining attention now; bump posts_limit for more coverage.
    reddit_listings: str = "hot,rising"
    reddit_posts_limit: int = 50
    # Also read the top comments on each scanned post (more signal, more spend).
    reddit_read_comments: bool = True
    reddit_comments_limit: int = 20
    # Gate before a ticker is even scored: it must clear this many distinct
    # mentions across the scan, AND its mentions must be running at least this
    # multiple of its trailing baseline (the "velocity" / acceleration guard).
    reddit_min_mentions: int = 8
    reddit_min_velocity: float = 2.0
    # Trailing window (days) used to compute each ticker's mention baseline.
    reddit_baseline_days: int = 7
    # Trade filters: require at least this conviction, and refuse anything whose
    # pump risk is at/above the ceiling (we never want to be late-stage exit
    # liquidity). is_noise signals are always skipped.
    reddit_min_conviction: str = "medium"  # low | medium | high
    reddit_max_pump_risk: str = "medium"   # low | medium | high  (ceiling, inclusive-below)
    # Max-loss budget per Reddit trade (the net debit), as a fraction of equity,
    # and a hard cap on simultaneous open Reddit positions. Sized small on
    # purpose — this is the most speculative book.
    paper_reddit_risk_frac: float = 0.01
    paper_reddit_max_open: int = 5
    # Conviction-weighted risk (fraction of equity) for Reddit trades.
    paper_reddit_risk_high: float = 0.015
    paper_reddit_risk_medium: float = 0.01
    paper_reddit_risk_low: float = 0.005
    # Exit rules. Attention is short-lived, so hold days are tight. Take profit
    # once the spread is worth this fraction of its width; stop once it has lost
    # this fraction of the debit paid; and bail if the chatter reverses/dies.
    paper_reddit_hold_days: int = 5
    paper_reddit_take_profit: float = 0.6
    paper_reddit_stop_frac: float = 0.5
    # Days out to target for the option expiry (short-dated, but enough time for
    # the move to play out before theta bites).
    paper_reddit_min_dte: int = 14
    paper_reddit_max_dte: int = 45

    def paper_reddit_risk_fraction(self, conviction: str) -> float:
        """Map a Reddit-signal conviction tier to the fraction of equity to risk."""
        return {
            "high": self.paper_reddit_risk_high,
            "medium": self.paper_reddit_risk_medium,
            "low": self.paper_reddit_risk_low,
        }.get(conviction, self.paper_reddit_risk_low)

    @property
    def reddit_subreddit_list(self) -> list[str]:
        return [s.strip() for s in self.reddit_subreddits.split(",") if s.strip()]

    @property
    def reddit_listing_list(self) -> list[str]:
        return [s.strip() for s in self.reddit_listings.split(",") if s.strip()]

    def paper_risk_fraction(self, conviction: str) -> float:
        """Map a playbook conviction tier to the fraction of equity to risk."""
        return {
            "high": self.paper_risk_high,
            "medium": self.paper_risk_medium,
            "low": self.paper_risk_low,
        }.get(conviction, self.paper_risk_low)

    @property
    def alpaca_trading_base(self) -> str:
        return (
            "https://paper-api.alpaca.markets"
            if self.alpaca_paper
            else "https://api.alpaca.markets"
        )

    @property
    def alpaca_data_base(self) -> str:
        return "https://data.alpaca.markets"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def universe_path(self) -> Path:
        return BASE_DIR / "config" / "universe.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
