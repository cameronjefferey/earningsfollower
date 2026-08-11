# earningsfollower

Trade smarter around earnings. A local-first web app that tracks earnings for the
larger, market-moving names in **tech/AI, space, quantum, and semis**, and tells you:

- **Who reports** today / this week / last week / upcoming, by theme.
- **What the options market expects** — the implied move from the ATM straddle, vs. the
  stock's own historical average move (cheap / in-line / rich).
- **How the stock historically reacts** — average move, up rate, beat streak, and
  post-earnings drift, with a reaction-history chart.
- **Peer "waves"** — when a peer reports, how the target has historically drifted into
  its own print. This is the SNOW → ORCL setup, quantified.
- **Post-earnings drift (PEAD)** — live setups on stocks that just delivered a strong
  print (beat + up move, or miss + down move), backed by that stock's own historical
  drift behavior, with a concrete entry / exit / stop plan for each.

> For research and educational purposes only. **Not financial advice.** Data may be
> delayed or inaccurate. Options-implied moves are estimates from ATM straddles.

## Architecture

```
backend/   FastAPI + SQLite + analytics (Python)
frontend/  Next.js + Tailwind + Recharts (TypeScript)
```

- **Data sources:** [Financial Modeling Prep](https://site.financialmodelingprep.com/)
  (earnings calendar, historical earnings, beat/miss, peers, profiles) and
  [yfinance](https://github.com/ranaroussi/yfinance) (option chains for implied move,
  daily prices, and an earnings-date fallback when no FMP key is set).
- **Storage:** SQLite locally (swappable to Postgres via `DATABASE_URL` for deployment).
- **Refresh:** an APScheduler job refreshes daily after the US close; you can also
  trigger refreshes manually.

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Optional but recommended: add a free FMP key to .env (FMP_API_KEY=...).
# Without it, the app still works using yfinance for prices + earnings dates.
```

Populate the database (first run pulls history; takes a couple of minutes for the full
universe over the network):

```bash
# Quick subset to try it out:
python -m app.refresh --tickers NVDA,SNOW,ORCL,AMD,CRM,MSFT,PLTR,NOW --no-peers

# Or the full curated universe (use --no-peers to skip FMP peer expansion):
python -m app.refresh
```

Run the API:

```bash
uvicorn app.main:app --reload --port 8000
# Docs at http://127.0.0.1:8000/docs
```

### 2. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # points at http://127.0.0.1:8000 by default
npm run dev
# App at http://localhost:3000
```

## Paywall (optional, free to set up)

Auth.js (Google, email/password, magic link) + Stripe subscriptions. **Off by
default** — the app stays fully open until you flip `PAYWALL_ENABLED` /
`NEXT_PUBLIC_PAYWALL_ENABLED`.

**What you get for $0:** Google OAuth, Auth.js, Stripe test mode, and (until someone
pays) no Stripe fees. You only pay Stripe’s cut on real charges. Magic-link /
verify / reset emails use [Resend](https://resend.com) on the API.

1. **Shared secret** — same value in backend `AUTH_SECRET` and frontend `AUTH_SECRET`:
   `openssl rand -base64 32`
2. **Google OAuth (free)** — [Google Cloud Console → Credentials](https://console.cloud.google.com/apis/credentials)
   → Create OAuth client (Web). Redirect URI: `http://localhost:3000/api/auth/callback/google`
   (plus your Render URL `/api/auth/callback/google`). Set `AUTH_GOOGLE_ID` /
   `AUTH_GOOGLE_SECRET` in `frontend/.env.local`.
3. **Resend (email auth)** — verify a sending domain, then set backend
   `RESEND_API_KEY` and `RESEND_FROM` (e.g. `Earnings Follower <login@mail.yoursite.com>`).
   Links use `PUBLIC_APP_URL`.
4. **Stripe (free test mode)** — [Stripe Dashboard](https://dashboard.stripe.com/test/apikeys):
   - Copy the **test** secret key → backend `STRIPE_SECRET_KEY`
   - Products → add a monthly Price → `STRIPE_PRICE_ID=price_...`
   - List every price you sell (annual, legacy, promo) in `STRIPE_PRICE_IDS`,
     comma-separated. Stripe fans an account's entire event stream out to every
     webhook endpoint on it, so if the account is shared with another product
     the webhook must confirm a price id it owns before granting or revoking
     access. Anything not in this list is treated as another product's traffic:
     forget a price and those subscribers get no access.
   - Developers → Webhooks → endpoint `http://localhost:8000/billing/webhook`
     (or your API URL) for `checkout.session.completed`,
     `customer.subscription.*` (including `updated`, which carries plan switches
     and cancel-at-period-end), `invoice.paid` → `STRIPE_WEBHOOK_SECRET`
   - Locally, `stripe listen --forward-to localhost:8000/billing/webhook` is easiest
5. **VIP / complimentary Pro** — `AUTH_BYPASS_EMAILS=friend@gmail.com` on the backend (Pro without Stripe; not admin)
6. **Turn the gate on** (both sides):
   - backend: `PAYWALL_ENABLED=true`, `PUBLIC_APP_URL=http://localhost:3000`
   - frontend: `NEXT_PUBLIC_PAYWALL_ENABLED=true`

**Freemium split:** Calendar (`/calendar`, `/themes`, `/earnings`) stays public. Live
Waves/Drift boards and full company detail are soft-gated (guests see demos/previews;
Pro unlocks live data). Paper, Learning, and Ops are admin-only. Pricing UI: `/pricing`.

### Production launch checklist

1. `PAYWALL_ENABLED=true` on the API; `PUBLIC_APP_URL=https://www.earningsfollower.com`
2. Live Stripe keys + price id; webhook to the API `/billing/webhook` for
   `checkout.session.*`, `customer.subscription.*`, `invoice.paid`,
   `invoice.payment_succeeded`, `invoice.payment_failed`
3. Google OAuth redirect: `https://www.earningsfollower.com/api/auth/callback/google`
4. Resend domain + `RESEND_API_KEY` / `RESEND_FROM` / `CONTACT_INBOX`
5. Telegram bot for signup/Stripe alerts (`TELEGRAM_*`, `TELEGRAM_NOTIFY_SIGNUP=true`)
6. `ADMIN_EMAILS` includes your email (Paper / Learning / Ops dashboard)
7. Smoke: sign up → Checkout → Pro boards → cancel in portal → Contact form

## Editing the universe

Tracked tickers and themes live in
[`backend/app/config/universe.yaml`](backend/app/config/universe.yaml). Add or remove
tickers, add new themes, or toggle `expand_with_fmp_peers`. Re-run `python -m app.refresh`
after changes.

## API endpoints

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/themes` | Themes and tracked ticker counts (public) |
| GET | `/earnings?window=today\|week\|last_week\|upcoming&theme=` | Earnings cards for a window (public) |
| GET | `/company/{ticker}` | Reaction history, implied move, peer waves (paid when paywall on) |
| GET | `/waves?recent_days=14&upcoming_days=21` | Live ride-the-wave setups (paid) |
| GET | `/drift?lookback_days=12` | Live post-earnings drift setups with trade plans (paid) |
| POST | `/refresh?background=true` | Trigger a data refresh (paid) |
| GET | `/refresh/status` | Last refresh result |
| POST | `/auth/upsert` | Create/update user after sign-in |
| POST | `/auth/register` | Email/password signup |
| POST | `/auth/login` | Email/password check (Auth.js Credentials) |
| POST | `/auth/magic/request` | Email a magic sign-in link |
| POST | `/auth/magic/consume` | One-time magic-link exchange |
| POST | `/auth/password/forgot` | Email a password-reset link |
| POST | `/auth/password/reset` | Set a new password from reset token |
| POST | `/auth/email/verify` | Confirm email from verify token |
| GET | `/auth/me` | Current user + subscription status |
| POST | `/billing/checkout-session` | Stripe Checkout URL |
| POST | `/billing/portal-session` | Stripe Customer Portal URL |
| POST | `/billing/webhook` | Stripe webhooks |

## How the analytics work

- **Reaction move (timing-aware):** for `bmo` reports, close-before vs. report-day close;
  for `amc`/unknown, report-day close vs. next-day close. Also computes the open gap and
  a 5-day post-earnings drift.
- **Implied move:** nearest post-earnings expiry ATM straddle (bid/ask mid when quoted)
  × 0.85 ≈ a one-standard-deviation expected move. Compared to the stock's historical
  average absolute move to gauge whether vol looks cheap or rich.
- **Peer waves (lead-lag):** for each past report of a peer, measure the target's return
  from the peer's report date to the close just before the target's own report. Aggregated
  across cycles into an average run-up, win rate, and sample size, conditioned on whether
  the peer's reaction was up or down.
- **Drift setups (PEAD):** a stock qualifies only if it (1) beat and jumped ≥2% (long)
  or missed and dropped ≥2% (short), (2) drifted the same way after ≥3 similar past
  prints (avg ≥0.5% in the trade direction), (3) hasn't closed back through its
  earnings-day pivot (thesis intact), and (4) is within the 5-trading-day drift window
  (or 10 days when its own history supports the extension). Each setup ships with a
  plain-English entry / exit / stop plan and the "why" behind it.

## Notes & limits

- Free FMP tier is 250 calls/day. Prices/implied-move come from yfinance (free) to
  conserve FMP quota; FMP is used for calendar, beat/miss, peers, and profiles.
- yfinance can be intermittently flaky; the daily refresh retries and is resilient to
  per-ticker failures.
- Designed to deploy on Render later (web service + Postgres + cron) — kept local-first
  for now.

<!-- ci: auto-deploy connectivity check, 2026-06-22 -->
