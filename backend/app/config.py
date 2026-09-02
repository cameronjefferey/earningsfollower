from __future__ import annotations

from datetime import date
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

    # --- Auth + paywall (all optional; off until PAYWALL_ENABLED=true) ---------
    # Shared secret with the Next.js Auth.js install (AUTH_SECRET). Used to verify
    # HS256 access tokens the frontend sends as Bearer auth.
    auth_secret: str = ""
    # When false (default), API routes stay open so local/dev keeps working
    # without Google/Stripe. Flip true once auth + Stripe are configured.
    paywall_enabled: bool = False
    # Comma-separated VIP emails: full Pro (paywall bypass) without Stripe.
    # Does NOT grant admin (Paper / Learning / Ops). Use ADMIN_EMAILS for that.
    auth_bypass_emails: str = ""
    # Comma-separated emails with admin access (Paper, Learning, playbooks, drift
    # trade plans). Empty = nobody is admin; admin routes return 403.
    admin_emails: str = ""

    # --- Stripe billing -------------------------------------------------------
    stripe_secret_key: str = ""
    # Signing secret(s) for /billing/webhook. Comma-separated is allowed so a
    # rotated Dashboard secret and an old one can both verify during cutover.
    stripe_webhook_secret: str = ""
    # Price id for the monthly plan (create in Stripe Dashboard → Products).
    stripe_price_id: str = ""
    # Every price id that belongs to THIS app, comma-separated (monthly, annual,
    # legacy/grandfathered, promo). The Stripe account is shared with sibling
    # products, and Stripe delivers the whole account's event stream to every
    # endpoint, so price id is the only reliable "is this ours?" discriminator.
    # stripe_price_id is always included; list the rest here.
    stripe_price_ids: str = ""
    # Public site origin used to build Checkout success/cancel URLs when the
    # client doesn't pass them (e.g. https://earningsfollower-web.onrender.com).
    public_app_url: str = "http://localhost:3000"
    # This API's own public origin (e.g. https://api.earningsfollower.com), used
    # for links that must hit the API directly such as one-click email
    # unsubscribe. Empty = fall back to the account page for pref changes.
    api_public_url: str = ""

    # --- Transactional email (Resend) -----------------------------------------
    # Used for magic-link login, email verification, password reset, and contact.
    # Empty key = auth email endpoints no-op / return a clear config error.
    resend_api_key: str = ""
    # Verified sender, e.g. "Earnings Follower <login@mail.earningsfollower.com>".
    resend_from: str = ""
    # Inbox for /contact form submissions (Reply-To is the visitor's email).
    contact_inbox: str = "happyuphilltrader@gmail.com"

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
    # Ping when Waves/Drift boards gain new tickers after a refresh (same chat).
    telegram_notify_setups: bool = True
    # Ping when a live paper run errors / aborts a book so silent empty books
    # don't wait on someone noticing zero open positions.
    telegram_notify_paper_health: bool = True
    # Ping on signup-funnel events: auth failures, checkout/webhook failures,
    # and successful new paid subscriptions (same Telegram chat).
    telegram_notify_signup: bool = True

    # --- Wave alert emails (Pro) ----------------------------------------------
    # After the daily refresh, email subscribers when new wave targets appear on
    # the board (peers reported; a themed name reports soon). Requires Resend.
    email_wave_alerts: bool = True

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
    # desyncing the DB - the close still goes through the normal code path). Clear
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
    # Proactive loss-cutting on sell-vol / earnings credit trades. On by default:
    # without it, take-profits clip winners while losers can run toward full
    # defined risk - a 50% win rate still bleeds the book. Loss is measured as a
    # fraction of the trade's max risk, evaluated each run (so it's only as
    # timely as the cron cadence).
    paper_stops_enabled: bool = True
    # Hard stop: close any open position once its unrealized loss hits this.
    paper_stop_loss_frac: float = 0.20
    # Near expiry (<= this many days to expiration) tighten to a smaller stop.
    paper_late_dte: int = 1
    paper_late_stop_frac: float = 0.10
    # --- Fills ----------------------------------------------------------------
    # A limit at (or a few pennies off) the mid won't fill a wide, illiquid
    # options spread - we watched JEF/WOR spreads sit unfilled all session. To
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
    # --- Walk-limit exits -----------------------------------------------------
    # For urgent option-spread exits (manual close / stops) we don't just cross
    # the market and pay the touch. We "walk" the net limit: start patient at
    # ~mid and concede a penny every few seconds toward the marketable cross,
    # so we give up only as much edge as the book actually demands to fill. If
    # it still hasn't filled by the per-order budget, drop the final marketable
    # order and let the next reconcile finish it. Set enabled=False to fall back
    # to the immediate single cross.
    paper_walk_limit_enabled: bool = True
    paper_walk_step: float = 0.01            # net-price concession per step
    paper_walk_interval_seconds: float = 2.0  # dwell at each price before repricing
    paper_walk_max_seconds: float = 30.0      # per-order wall-clock budget
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

    # --- Calibration feedback (learning loop closes the loop) -----------------
    # Feed the realized-vs-predicted win rate learned from the trade-decision
    # store back into the entry EV gate: recalibrate each strategy's model
    # win-probability by how optimistic/pessimistic it has actually been. On
    # now that the journal has enough graded trades to be more than noise.
    # Sizing stays conviction-based; this only nudges the +EV gate (capped).
    paper_calibration_enabled: bool = True
    # Require at least this many graded (closed) trades in a strategy before its
    # calibration is trusted enough to apply.
    paper_calibration_min_samples: int = 20
    # Hard cap on how far calibration may move a win-probability, so even a wild
    # historical ratio can only nudge the gate, never swing it.
    paper_calibration_max_delta: float = 0.15

    # --- Entry model (joint logistic over size / vol / history) ----------------
    # Fit a regularized logistic regression on graded trade_decisions each run
    # and put its P(win) in front of the existing gates: veto names the model
    # scores below min_prob, and feed the model probability into the +EV gate
    # instead of the heuristic. Heuristic conviction / direction / liquidity
    # filters still run first. Falls back to calibrated heuristic when the
    # journal is too thin or the model's cross-validated AUC is coin-flip.
    paper_entry_model_enabled: bool = True
    paper_entry_model_min_samples: int = 30
    # Need both classes represented or the fit is a tautology.
    paper_entry_model_min_class: int = 8
    # Veto floor: skip a setup the model scores below this even if heuristics
    # like it. 0.45 = only reject the clearly worse-than-a-coin-flip names.
    # The model trains only on live earnings books, without a strategy dummy.
    paper_entry_model_min_prob: float = 0.45
    # Don't let the model veto/reprice until walk-forward AUC beats a coin flip.
    # Below this it is recorded but not applied.
    paper_entry_model_min_auc: float = 0.52

    # --- Exit discipline: underlying take-profit (learning loop acts) ----------
    # The exit-quality backtest showed retired directional debit books reach a
    # favorable underlying move and then hand most of it back. This is a global
    # take-profit on the direction-adjusted underlying move for waves/drift/reddit
    # (still managing open rows). Earnings sell-vol wins on IV crush, not
    # direction. Earnings stock has its own 10%/7% band and is excluded so the
    # 3% clip cannot bank a print move that sleeve is meant to hold.
    paper_take_profit_enabled: bool = True
    paper_take_profit_pct: float = 0.03
    # Auto-tune the threshold from the realized record each run (the weekly
    # learning acting on itself). Guardrailed like calibration: needs a minimum
    # graded sample, is clamped to a sane band, and is only adopted when it beats
    # how we actually exited. Falls back to the static pct above otherwise.
    paper_exit_learning_enabled: bool = True
    paper_exit_learning_min_samples: int = 20
    paper_take_profit_min: float = 0.015
    paper_take_profit_max: float = 0.08

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
    # Cap on simultaneous open earnings-equity positions. Set high on purpose:
    # this book is a data-gathering experiment (equity vs options on the same
    # signals), so we want breadth. The practical ceiling becomes Alpaca paper
    # buying power, not this number -- orders that would exceed it just don't fill.
    paper_earnings_equity_max_open: int = 40
    # Cap per sector so a single sector's earnings week (e.g. 20+ regional banks
    # all reporting together) can't flood the book with one correlated, same-
    # direction bet -- take a couple of the best names and let the waves strategy
    # ride the rest of the sector sympathy. 0 disables the per-sector cap.
    paper_earnings_equity_max_per_sector: int = 3
    # Underlying-move exits for the equity leg (held through the print, then the
    # post-earnings close mirrors the options harvest; these are the pre/at-print
    # guardrails). Earnings moves are larger than the intraday Reddit ride, so the
    # bands are wider than the Reddit equity twin's.
    paper_earnings_equity_take_profit_pct: float = 0.10
    paper_earnings_equity_stop_pct: float = 0.07
    # Own-book kill switch: stop opening new earnings-stock names after a
    # trailing 0-for-N closed streak. Does not disable the flag (the book is
    # still the control group) and does not flatten open rows. 12 matches the
    # waves retirement sample. One bad week cannot trip it.
    paper_earnings_equity_halt_enabled: bool = True
    paper_earnings_equity_halt_window: int = 12

    # --- 5-day loser weekly reversal (S&P 500, long shares) -------------------
    # Long the N worst 5-session names, hold 5 sessions or take-profit at +10%,
    # skip earnings ±5 sessions, equal-weight, non-overlapping. The 1.22 Sharpe
    # / +1.09%/hold backtest is current-membership, no TP — not a live
    # expectation. Live runs a different strategy (current S&P + 10% clip).
    # Interim edge: +0.55%/hold from the daily-close 10% TP grid, unknown
    # survivorship haircut. Size 1% equity/name off that, not 2% off the
    # retired Sharpe. Live 10% TP stays; a shadow marks the 5-session hold
    # on the same entries so the override has a falsification sample. PIT
    # membership rebuild due 2026-09-29; until then the ranker's live edge
    # is unknown. Long-only. Kill the book the same way as waves (0-for-12).
    paper_reversal_enabled: bool = True
    paper_reversal_top_n: int = 5
    paper_reversal_lookback_days: int = 5
    paper_reversal_hold_days: int = 5
    paper_reversal_take_profit_pct: float = 0.10
    paper_reversal_min_price: float = 10.0
    paper_reversal_min_dollar_vol: float = 50_000_000.0
    paper_reversal_earn_buffer_days: int = 5
    paper_reversal_risk_frac: float = 0.01
    paper_reversal_max_open: int = 5
    # Stated live expectation while PIT is unbuilt. Not the 1.09% no-TP mean.
    paper_reversal_expected_hold_pct: float = 0.0055
    paper_reversal_pit_rebuild_by: date = date(2026, 9, 29)

    # --- Waves strategy (RETIRED as option debit spreads) ---------------------
    # Peer-sympathy is real on the underlying, but expressing it as a debit
    # spread after a vol event has been 0-for-N live: theta + IV crush eat the
    # debit, then the hold-window dumps the spread at a fraction of what we paid.
    # Same pattern that retired Reddit. Keep the knobs so open trades still
    # manage and history still deserializes; do not open new wave option entries.
    # Next experiment, if any, should be equity (like the earnings-equity book).
    paper_waves_enabled: bool = False
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
    # Don't hold a directional sympathy trade into the target's *own* print -
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

    # --- Drift (PEAD) strategy (RETIRED as option debit spreads) --------------
    # Post-print drift on the stock is the thesis; the vehicle was the problem.
    # Three weeks of live fills: 0 wins on closed drift debit spreads. We pay
    # elevated IV into the print, then hold 7 days while crush + theta work
    # against a long vega debit, and time-exit into a wide book. Retired the
    # same way as Reddit. Open drift positions still exit on their own rules.
    paper_drift_enabled: bool = False
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

    # --- Reddit sentiment strategy (RETIRED) ----------------------------------
    # Formerly traded social-attention spikes as debit spreads. Disabled after
    # poor live results - keep the knobs so historical paper trades / research
    # still deserialize, but never open new reddit positions.
    paper_reddit_enabled: bool = False
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
    # liquidity). is_noise signals are always skipped. Deliberately strict - this
    # is a speculative book, so we only want the rare, high-quality signal, not a
    # trade every day.
    reddit_min_conviction: str = "high"    # low | medium | high
    reddit_max_pump_risk: str = "low"      # low | medium | high  (ceiling, inclusive-below)
    # Max-loss budget per Reddit trade (the net debit), as a fraction of equity,
    # and a hard cap on simultaneous open Reddit positions. Sized small on
    # purpose - this is the most speculative book.
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
    # Exit rules - this is an intraday momentum ride: we're riding the Reddit
    # wave for a few hours, not holding overnight. Keep it tight:
    #   - hold_hours: close this many hours after the fill no matter what (the
    #     cron's ~30-min cadence is the granularity; e.g. 2.0 ≈ a couple hours).
    #   - take_profit: quick gain - close once the spread is worth this fraction
    #     of its max width.
    #   - stop_frac: quick loss - close once it has lost this fraction of the
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
    paper_reddit_equity_twin_enabled: bool = False
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
    def stripe_webhook_secret_list(self) -> list[str]:
        return [s.strip() for s in self.stripe_webhook_secret.split(",") if s.strip()]

    @property
    def stripe_owned_price_ids(self) -> frozenset[str]:
        """Price ids this app sells. Empty = own nothing (fail closed)."""
        ids = {self.stripe_price_id.strip()}
        ids.update(p.strip() for p in self.stripe_price_ids.split(","))
        return frozenset(p for p in ids if p)

    @property
    def auth_bypass_email_set(self) -> set[str]:
        return {
            e.strip().lower()
            for e in self.auth_bypass_emails.split(",")
            if e.strip()
        }

    @property
    def admin_email_set(self) -> set[str]:
        return {
            e.strip().lower()
            for e in self.admin_emails.split(",")
            if e.strip()
        }

    @property
    def universe_path(self) -> Path:
        return BASE_DIR / "config" / "universe.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
