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

    # --- Telegram trade alerts (optional) ------------------------------------
    # When both a bot token and a chat id are set, the paper trader sends a short
    # message after each live run summarizing the trades it just opened/closed, so
    # you get pinged when there's something new to look at. Create a bot via
    # @BotFather for the token; get your chat id by messaging the bot once and
    # reading https://api.telegram.org/bot<token>/getUpdates (or message @userinfobot).
    # Empty config = silent (never sends), and dry-runs never notify.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_notify_trades: bool = True

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
    # drift before the print). Impact analysis showed 10 captures clean ~10-day-out
    # directional names (INTC/MXL/TXN) without dragging in the illiquid 14-day tail.
    paper_entry_window_days: int = 10
    # Where to place the SHORT strike of a sell-vol spread/condor, as a fraction of
    # the expected move. 1.0 sells a full move OTM, which on high-IV names collects
    # almost nothing vs the wing width and gets gated; pulling it in to ~0.65
    # collects real premium (win-probability is recomputed at this closer strike so
    # the EV gate stays honest).
    paper_sell_strike_em_frac: float = 0.65
    # Floor on the modeled credit (per share) worth trading.
    paper_min_credit: float = 0.10
    # Operational override: comma-separated signal ids to force-close on the next
    # run regardless of the usual exit rules (used to flatten a bad fill without
    # desyncing the DB — the close still goes through the normal code path). Clear
    # it once the positions are closed.
    paper_force_close_ids: str = ""
    # Reward/risk gate: floor on the credit collected as a fraction of the
    # spread width. A credit spread's max profit is the credit and its max loss
    # is (width - credit), so a credit/width ratio of r implies a max loss:profit
    # of (1 - r)/r : 1. The default 0.20 caps that at 4:1 (we won't sell a $5-wide
    # spread for less than ~$1.00 of credit), which rejects the lopsided 13:1 /
    # 43:1 setups. The width-fitting search pulls the wings in to try to meet this
    # before giving up. Raise toward 0.33 to demand the classic "third of width".
    paper_min_credit_width_ratio: float = 0.20
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
    # Liquidity guard on entries: skip opening a spread when crossing the market
    # would give up more than this fraction of the combo's mid value. Wide,
    # illiquid options (huge bid/ask) bleed far more on the round-trip cross than
    # the trade can make, so we simply don't trade them.
    paper_max_cross_slippage_frac: float = 0.25
    # --- Fair-trade economics gate (app/services/paper/economics.py) ----------
    # Every entry is checked at its *executable* price (the marketable-cross
    # limit, re-checked again on the actual fill), never the modeled mid -- the
    # mid/fill gap (modeled 12.92, filled 21.55) is what let structurally
    # negative-EV trades through. All four strategies pass through the same gate.
    #
    # Fair price for a DEBIT spread: never pay more than this fraction of the
    # width, so there's always real upside left. 0.60 => max profit >= 40% of
    # width and reward:risk >= 0.67 (rejects the 0.86-of-width MU/AMD fills).
    paper_max_debit_width_frac: float = 0.60
    # Reward:risk floor (max_profit : max_loss), applied to both directions. Set
    # to 0.25 so it matches the credit spread's own 0.20 credit/width floor (a
    # credit/width of r implies reward:risk = r/(1-r), and 0.20 => 0.25) -- credit
    # spreads aren't double-penalized -- and is comfortably met by the 0.60 debit
    # cap above. Raise it to demand richer trades across the board.
    paper_min_reward_risk: float = 0.25
    # Expected-value floor per share: win_prob*max_profit - loss_prob*max_loss.
    # 0.0 = only take trades that are at worst breakeven on the tail model; raise
    # above 0 to demand a positive edge. Skipped for a strategy only when it has
    # no win-probability estimate at all (the price/liquidity gates still apply).
    paper_min_expected_value: float = 0.0
    # Per-leg liquidity ceiling: reject any leg whose (ask-bid)/mid exceeds this,
    # or that lacks a two-sided quote. Keeps us out of options no one is really
    # trading, where the mid itself is fiction.
    paper_max_leg_spread_frac: float = 0.15
    # Only place orders when the market is open (skip the overnight and pre/post-
    # open cron ticks where options can't fill anyway).
    paper_market_hours_only: bool = True

    # --- Earnings equity book (options A/B twin) ------------------------------
    # Alongside the earnings options play, take a plain equity position on the same
    # directional lean (long a bullish name, short a bearish one) so we can compare
    # whether the shares beat the options on the same signal. Equity is inherently
    # directional, so NEUTRAL (iron condor) names get no equity leg. Fires two ways:
    #   - twin: when the options spread opens, size the shares to the SAME dollars
    #     the spread risks (its max loss) -- "an equal amount on equity as options".
    #   - standalone: when the options trade is gated (illiquid / too thin) or the
    #     name is directional but not a sell-vol setup, still take the shares, sized
    #     to the conviction budget the options WOULD have risked.
    paper_earnings_equity_enabled: bool = True
    # Cap on simultaneous open earnings-equity positions.
    paper_earnings_equity_max_open: int = 8
    # Underlying-move exits for the equity leg (held through the print, then the
    # post-earnings close mirrors the options harvest; these are the pre/at-print
    # guardrails). Earnings moves are larger than the intraday Reddit ride, so the
    # bands are wider than the Reddit equity twin's.
    paper_earnings_equity_take_profit_pct: float = 0.10
    paper_earnings_equity_stop_pct: float = 0.07

    # --- Waves strategy (peer-earnings sympathy ride) -------------------------
    # A separate, directional strategy: when a tracked peer reports a strong
    # earnings move, buy a themed name that historically drifts in sympathy, ride
    # the pop for a couple of days, and get out. This is decoupled from the
    # target's *own* earnings date — the catalyst is the peer's print, not the
    # target's — so we enter as early as the peer reports and hold a short, fixed
    # window. (A debit spread — not a naked long option — keeps high-priced names
    # like TSM/ASML affordable on a small budget and caps the risk.)
    paper_waves_enabled: bool = True
    # Only trigger on a peer that reported within this many days (be early: the
    # sympathy pop is a few-day move right after the peer's print).
    paper_wave_trigger_max_age_days: int = 2
    # The peer's own earnings-day move must be at least this big to count as a
    # catalyst worth riding (a flat print doesn't drag peers).
    paper_wave_min_trigger_move: float = 0.03
    # Historical edge is the target's return over this many *trading* days after
    # the peer's report; it also sets the live hold horizon below.
    paper_wave_hist_hold_days: int = 3
    # Fixed hold: exit this many calendar days after entry (≈ a couple trading
    # days), regardless of the target's own calendar.
    paper_wave_hold_days: int = 4
    # Don't hold a directional sympathy trade into the target's *own* print —
    # bail if its earnings land within this many days of the hold.
    paper_wave_avoid_earnings_within_days: int = 3
    # Bracket on the *underlying's* move from entry (favorable / adverse).
    paper_wave_gain_pct: float = 0.08
    paper_wave_loss_pct: float = 0.05
    # Quality filters on the historical sympathy edge before we'll trade it.
    paper_wave_min_winrate: float = 0.60
    paper_wave_min_samples: int = 4
    # Short-dated expiry window for the debit spread (enough time that a few-day
    # hold isn't eaten by theta, but we're not paying for months of premium).
    paper_wave_min_dte: int = 14
    paper_wave_max_dte: int = 45
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
    # debit spread (bull call / bear put), and exit fast — it's a pure momentum
    # trade, so we just ride the Reddit wave for a short window and take a quick
    # gain or a quick loss. Everything below is a knob to tune over time.
    paper_reddit_enabled: bool = True
    # Discovery + velocity source. ApeWisdom is a free, no-auth aggregator that
    # already crawls the retail subreddits and reports per-ticker mentions plus
    # the same count 24h ago (a ready-made acceleration signal). It's the
    # dependable default since Reddit blocks datacenter IPs and now gates app
    # creation. Direction/sentiment is layered on top (Reddit text when OAuth is
    # configured, else price momentum). Set False to use only direct Reddit
    # listing reads (requires working Reddit credentials).
    reddit_use_apewisdom: bool = True
    # ApeWisdom filter ("all-stocks" = stocks across all subs; or a single sub
    # like "wallstreetbets") and how many ~100-name pages to pull.
    reddit_apewisdom_filter: str = "all-stocks"
    reddit_apewisdom_pages: int = 2
    # Per-subreddit ApeWisdom boards to also pull each scan, purely so we can
    # attribute *which* subreddit(s) a tracked ticker is trending in (the primary
    # aggregate filter above can't tell us). Used for the scorecard's
    # by-subreddit breakdown; does not change which tickers qualify to trade.
    reddit_apewisdom_sub_filters: str = "wallstreetbets,stocks,options,investing,StockMarket"
    # Momentum fallback for direction when no Reddit text is available: trade the
    # continuation of the recent move. Lookback in trading days, plus a deadband
    # under which the move is too flat to call a direction (treated as noise).
    reddit_momentum_lookback_days: int = 5
    reddit_momentum_deadband: float = 0.01
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
    reddit_min_mentions: int = 20
    reddit_min_velocity: float = 3.0
    # Trailing window (days) used to compute each ticker's mention baseline.
    reddit_baseline_days: int = 7
    # Trade filters: require at least this conviction, and refuse anything whose
    # pump risk is at/above the ceiling (we never want to be late-stage exit
    # liquidity). is_noise signals are always skipped. Deliberately strict — this
    # is a speculative book, so we only want the rare, high-quality signal, not a
    # trade every day.
    reddit_min_conviction: str = "high"    # low | medium | high
    reddit_max_pump_risk: str = "low"      # low | medium | high  (ceiling, inclusive-below)
    # Max-loss budget per Reddit trade (the net debit), as a fraction of equity,
    # and a hard cap on simultaneous open Reddit positions. Sized small on
    # purpose — this is the most speculative book.
    paper_reddit_risk_frac: float = 0.01
    paper_reddit_max_open: int = 2
    # Trade-frequency guardrails so we don't churn: cap how many *new* Reddit
    # option entries we open per calendar day, and refuse to re-enter the same
    # ticker until this many days after its last entry (avoids chasing the same
    # name day after day).
    paper_reddit_max_new_per_day: int = 1
    paper_reddit_reentry_cooldown_days: int = 5
    # Conviction-weighted risk (fraction of equity) for Reddit trades.
    paper_reddit_risk_high: float = 0.015
    paper_reddit_risk_medium: float = 0.01
    paper_reddit_risk_low: float = 0.005
    # Exit rules — this is an intraday momentum ride: we're riding the Reddit
    # wave for a few hours, not holding overnight. Keep it tight:
    #   - hold_hours: close this many hours after the fill no matter what (the
    #     cron's ~30-min cadence is the granularity; e.g. 2.0 ≈ a couple hours).
    #   - take_profit: quick gain — close once the spread is worth this fraction
    #     of its max width.
    #   - stop_frac: quick loss — close once it has lost this fraction of the
    #     debit paid.
    #   - and we still bail if the chatter itself reverses or dies.
    paper_reddit_hold_hours: float = 1.0
    paper_reddit_take_profit: float = 0.5
    paper_reddit_stop_frac: float = 0.4
    # Equity twin: alongside each Reddit options spread, also open a stock
    # position on the same name/direction (short for bearish), sized to the same
    # dollar risk as the spread, so we can A/B whether buying the shares beats
    # the options (the momentum may already be priced into rich option premium).
    # Exits on the same hold_hours, plus its own %-move take-profit / stop.
    paper_reddit_equity_twin_enabled: bool = True
    paper_reddit_equity_take_profit_pct: float = 0.03
    paper_reddit_equity_stop_pct: float = 0.02
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
    def reddit_apewisdom_sub_filter_list(self) -> list[str]:
        return [s.strip() for s in self.reddit_apewisdom_sub_filters.split(",") if s.strip()]

    @property
    def reddit_listing_list(self) -> list[str]:
        return [s.strip() for s in self.reddit_listings.split(",") if s.strip()]

    @property
    def paper_force_close_id_set(self) -> set[str]:
        return {s.strip() for s in self.paper_force_close_ids.split(",") if s.strip()}

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
