# candlechaser — realtime headline alerts for day trading

Chase the big green candle the moment the headline prints.

Everything below is a complete, paste-able build-out for a new repo. Create each file
with the exact contents shown, or paste this whole document into Cursor in the new repo
and say "create all of these files".

## What it does

A single always-on Python worker:

1. Streams every headline in realtime from Alpaca's free news websocket (Benzinga wire,
   sub-second delivery).
2. Runs cheap pre-filters (dedupe, market-hours window).
3. Sends each surviving headline to an LLM that scores 0–100 the probability it moves a
   specific stock ≥2% intraday — and identifies the *tradeable* ticker, including
   cross-ticker cases (NVDA CEO praises MRVL → alert on MRVL).
4. If score ≥ threshold, pushes a Telegram alert to your phone within a few seconds of
   the headline hitting the wire.
5. Logs every headline + score to SQLite so you can backtest and tune the threshold later.

## Costs

| Service | Purpose | Cost |
|---|---|---|
| Alpaca (free account, no funding needed) | realtime news websocket | $0 |
| OpenAI API (`gpt-5.4-mini`) | headline classification | roughly $1–3/day at full wire volume during market hours |
| Telegram | push alerts | $0 |
| Render background worker | hosting | ~$7/mo (or run it on your Mac for free) |

Upgrade path if you outgrow it: Benzinga Pro API or Polygon news for broader/faster wire
coverage, but start here — same architecture either way.

## Accounts to set up (15 min)

1. **Alpaca**: sign up at alpaca.markets (paper account is fine), generate API key + secret.
2. **OpenAI**: API key from platform.openai.com.
3. **Telegram bot**:
   - Message `@BotFather` in Telegram → `/newbot` → pick a name → copy the bot token.
   - Send your new bot any message (e.g. "hi").
   - Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and copy
     `result[0].message.chat.id` — that's your `TELEGRAM_CHAT_ID`.

## File tree

```
candlechaser/
├── README.md
├── .gitignore
├── .env.example
├── requirements.txt
├── render.yaml
└── app/
    ├── __init__.py
    ├── config.py
    ├── stream.py
    ├── filters.py
    ├── prompts.py
    ├── classifier.py
    ├── notifier.py
    ├── store.py
    └── main.py
```

---

## `README.md`

```markdown
# candlechaser

Realtime headline alerts for intraday trading. Streams the Benzinga news wire via
Alpaca's free websocket, scores each headline with an LLM for "will this move a stock
≥2% intraday", and pushes Telegram alerts within seconds.

## Setup

1. Copy `.env.example` to `.env` and fill in your keys (see comments in the file).
2. Install and run:

   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt

3. Verify the plumbing:

   python -m app.main --test-telegram
   python -m app.main --classify "NVDA CEO says Marvell will be the next trillion dollar company"

4. Run the worker:

   python -m app.main

Every headline is logged to SQLite (`candlechaser.db`) with its score, whether it alerted,
and the classifier's rationale — use it to tune `ALERT_SCORE_THRESHOLD`.

## Tuning

- Start with `ALERT_SCORE_THRESHOLD=70`. After a few days, query the DB: if you're
  getting spammed, raise it; if you're missing movers, lower it and tighten the prompt.
- `MARKET_HOURS_ONLY=true` limits alerts to 07:00–16:00 ET weekdays (premarket included).
  Set `false` to also catch after-hours headlines.
- Per-ticker cooldown (default 15 min) stops repeat alerts on follow-up coverage.

## Deploy

`render.yaml` defines a Render background worker (~$7/mo) with a persistent disk for
the SQLite log. Set the secret env vars in the Render dashboard.
```

---

## `.gitignore`

```
.env
*.db
__pycache__/
*.pyc
.venv/
```

---

## `.env.example`

```
# Alpaca — free account at https://alpaca.markets (paper account is fine).
# Used only for the realtime news websocket; no trading happens.
ALPACA_KEY_ID=
ALPACA_SECRET_KEY=

# OpenAI — headline classification.
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.4-mini

# Telegram — create a bot via @BotFather, then get your chat id from
# https://api.telegram.org/bot<TOKEN>/getUpdates after messaging the bot once.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Behavior
ALERT_SCORE_THRESHOLD=70
TICKER_COOLDOWN_MINUTES=15
MARKET_HOURS_ONLY=true
ALERT_START_ET=07:00
ALERT_END_ET=16:00
DB_PATH=./candlechaser.db
```

---

## `requirements.txt`

```
websockets>=12.0
openai>=1.40.0
httpx>=0.27.0
pydantic-settings>=2.3.0
```

---

## `render.yaml`

```yaml
# Render Blueprint for candlechaser.
# Background workers have no free tier; starter is ~$7/mo.
services:
  - type: worker
    name: candlechaser
    runtime: python
    region: oregon
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: python -m app.main
    disk:
      name: candlechaser-data
      mountPath: /data
      sizeGB: 1
    envVars:
      - key: ALPACA_KEY_ID
        sync: false # set in the dashboard
      - key: ALPACA_SECRET_KEY
        sync: false
      - key: OPENAI_API_KEY
        sync: false
      - key: TELEGRAM_BOT_TOKEN
        sync: false
      - key: TELEGRAM_CHAT_ID
        sync: false
      - key: OPENAI_MODEL
        value: gpt-5.4-mini
      - key: ALERT_SCORE_THRESHOLD
        value: "70"
      - key: DB_PATH
        value: /data/candlechaser.db
```

---

## `app/__init__.py`

```python
```

(empty file)

---

## `app/config.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Alpaca (news websocket)
    alpaca_key_id: str
    alpaca_secret_key: str

    # OpenAI (headline classification)
    openai_api_key: str
    openai_model: str = "gpt-5.4-mini"

    # Telegram (alert delivery)
    telegram_bot_token: str
    telegram_chat_id: str

    # Behavior
    alert_score_threshold: int = 70
    ticker_cooldown_minutes: int = 15
    market_hours_only: bool = True
    alert_start_et: str = "07:00"
    alert_end_et: str = "16:00"
    db_path: str = "./candlechaser.db"


settings = Settings()
```

---

## `app/stream.py`

```python
import asyncio
import json

import websockets

from .config import settings

WS_URL = "wss://stream.data.alpaca.markets/v1beta1/news"


async def news_stream():
    """Yield news items forever, reconnecting with backoff on any failure."""
    backoff = 1
    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                await _handshake(ws)
                print("connected to news stream, subscribed to all symbols")
                backoff = 1
                async for raw in ws:
                    for msg in json.loads(raw):
                        kind = msg.get("T")
                        if kind == "n":
                            yield msg
                        elif kind == "error":
                            print(f"stream error message: {msg}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"stream disconnected ({exc!r}); reconnecting in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def _handshake(ws):
    await ws.recv()  # [{"T":"success","msg":"connected"}]
    await ws.send(json.dumps({
        "action": "auth",
        "key": settings.alpaca_key_id,
        "secret": settings.alpaca_secret_key,
    }))
    reply = json.loads(await ws.recv())
    if not any(m.get("msg") == "authenticated" for m in reply):
        raise RuntimeError(f"alpaca auth failed: {reply}")
    await ws.send(json.dumps({"action": "subscribe", "news": ["*"]}))
```

---

## `app/filters.py`

```python
import hashlib
import re
import time
from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


class Filters:
    """Cheap checks that run before spending an LLM call, plus alert cooldowns."""

    def __init__(self, settings):
        self.settings = settings
        self._seen_ids: OrderedDict = OrderedDict()
        self._seen_headlines: OrderedDict = OrderedDict()
        self._cooldowns: dict[str, float] = {}

    def pre_skip(self, item: dict) -> str | None:
        """Return a skip reason, or None if the item should be classified."""
        if not item.get("headline"):
            return "empty_headline"
        if not self._in_alert_window():
            return "outside_alert_window"
        item_id = item.get("id")
        if item_id in self._seen_ids:
            return "duplicate_id"
        self._remember(self._seen_ids, item_id)
        digest = self._headline_digest(item["headline"])
        if digest in self._seen_headlines:
            return "duplicate_headline"
        self._remember(self._seen_headlines, digest)
        return None

    def tradeable_symbols(self, symbols: list[str]) -> list[str]:
        """Drop symbols that alerted within the cooldown window."""
        now = time.time()
        window = self.settings.ticker_cooldown_minutes * 60
        return [s for s in symbols if now - self._cooldowns.get(s, 0) > window]

    def mark_alerted(self, symbols: list[str]) -> None:
        now = time.time()
        for s in symbols:
            self._cooldowns[s] = now

    def _in_alert_window(self) -> bool:
        if not self.settings.market_hours_only:
            return True
        now = datetime.now(ET)
        if now.weekday() >= 5:
            return False
        hhmm = now.strftime("%H:%M")
        return self.settings.alert_start_et <= hhmm < self.settings.alert_end_et

    @staticmethod
    def _headline_digest(headline: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", headline.lower()).strip()
        return hashlib.sha1(normalized.encode()).hexdigest()

    @staticmethod
    def _remember(cache: OrderedDict, key, max_size: int = 5000) -> None:
        cache[key] = time.time()
        while len(cache) > max_size:
            cache.popitem(last=False)
```

---

## `app/prompts.py`

```python
SYSTEM_PROMPT = """You are a senior trading-desk analyst screening a realtime equity news wire.
For each headline, estimate the probability that it causes an intraday move of 2% or more
in a specific US-listed stock within the next 30 minutes, BECAUSE the headline contains new,
surprising, material information.

Respond with ONLY a JSON object in this exact shape:
{
  "score": <integer 0-100>,
  "tickers": [{"symbol": "<TICKER>", "direction": "up" | "down" | "unclear"}],
  "category": "<one of: m&a, guidance, earnings_surprise, fda_regulatory, exec_comment, analyst_action, activist_stake, short_report, contract_win, product, legal, macro, halt_or_offering, other>",
  "rationale": "<one short sentence>"
}

Rules:
- "tickers" must list EVERY stock likely to move, not just the company named first.
  Example: "NVDA CEO says Marvell will be the next trillion-dollar company" -> the
  tradeable ticker is MRVL (direction up), not NVDA.
- Use the ticker of the affected US-listed stock. If no specific tradeable ticker exists,
  return an empty tickers list and a low score.
- Score 80-100: clearly market-moving and surprising. Unexpected M&A or takeover interest,
  FDA approval/rejection/clinical results, guidance raised or cut, activist stake disclosed,
  short-seller report published, surprise CEO/CFO exit, major exec commenting on ANOTHER
  company, large contract win or loss, surprise capital raise or offering, trading halt news.
- Score 50-79: plausibly moving but less certain. Analyst upgrade/downgrade with a large
  price-target change, meaningful product launches, partnerships with mega-caps, clear
  sympathy plays off another stock's news.
- Score 0-30: routine or stale. Recap articles ("Why X stock is moving today"), top-movers
  lists, scheduled events already on the calendar, opinion pieces and listicles, reiterated
  ratings, small price-target tweaks, generic sector or macro commentary, old news rehashed,
  crypto/forex-only items.
- Headlines that merely DESCRIBE a move already underway ("Shares of X jump 8%") are stale:
  score 30 or below.
- Micro-caps and penny stocks move on anything; only score them high for truly major news,
  since they are hard to trade.
- Be skeptical. The wire produces thousands of headlines a day; only a handful deserve 70+.
"""
```

---

## `app/classifier.py`

```python
import json

from openai import AsyncOpenAI

from .config import settings
from .prompts import SYSTEM_PROMPT

_client = AsyncOpenAI(api_key=settings.openai_api_key)


async def classify(item: dict) -> dict | None:
    payload = {
        "headline": item.get("headline", ""),
        "summary": (item.get("summary") or "")[:600],
        "tagged_symbols": item.get("symbols") or [],
        "source": item.get("source", ""),
        "created_at": item.get("created_at", ""),
    }
    try:
        resp = await _client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
            response_format={"type": "json_object"},
            timeout=15,
        )
        return _sanitize(json.loads(resp.choices[0].message.content))
    except Exception as exc:
        print(f"classification failed: {exc!r}")
        return None


def _sanitize(data: dict) -> dict:
    tickers = []
    for t in data.get("tickers") or []:
        if isinstance(t, dict) and t.get("symbol"):
            direction = t.get("direction", "unclear")
            if direction not in ("up", "down", "unclear"):
                direction = "unclear"
            tickers.append({"symbol": str(t["symbol"]).upper(), "direction": direction})
    try:
        score = max(0, min(100, int(data.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    return {
        "score": score,
        "tickers": tickers,
        "category": str(data.get("category", "other")),
        "rationale": str(data.get("rationale", ""))[:300],
    }
```

---

## `app/notifier.py`

```python
import httpx

from .config import settings


async def send_alert(item: dict, result: dict, pipeline_seconds: float) -> None:
    tickers = "  ".join(f"{t['symbol']} {t['direction'].upper()}" for t in result["tickers"])
    lines = [
        f"<b>{tickers}</b> — score {result['score']}/100",
        item.get("headline", ""),
        f"<i>{result['rationale']}</i>",
    ]
    if item.get("url"):
        lines.append(item["url"])
    lines.append(
        f"{result['category']} | {item.get('source', '')} | {pipeline_seconds:.1f}s wire-to-alert"
    )
    await _send("\n".join(lines))


async def send_test() -> None:
    await _send("candlechaser test message: Telegram wiring works.")


async def _send(text: str) -> None:
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json={
            "chat_id": settings.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        resp.raise_for_status()
```

---

## `app/store.py`

```python
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS headlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wire_id TEXT,
    received_at REAL NOT NULL,
    headline TEXT,
    symbols TEXT,
    source TEXT,
    url TEXT,
    skip_reason TEXT,
    score INTEGER,
    category TEXT,
    rationale TEXT,
    result_tickers TEXT,
    alerted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_headlines_received ON headlines (received_at);
"""


class Store:
    """Logs every headline and classification so thresholds can be tuned later."""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def log(self, item: dict, skip_reason: str | None = None,
            result: dict | None = None, alerted: bool = False) -> None:
        result = result or {}
        self.conn.execute(
            """INSERT INTO headlines (wire_id, received_at, headline, symbols, source, url,
               skip_reason, score, category, rationale, result_tickers, alerted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(item.get("id", "")),
                time.time(),
                item.get("headline"),
                json.dumps(item.get("symbols") or []),
                item.get("source"),
                item.get("url"),
                skip_reason,
                result.get("score"),
                result.get("category"),
                result.get("rationale"),
                json.dumps(result.get("tickers") or []),
                int(alerted),
            ),
        )
        self.conn.commit()
```

---

## `app/main.py`

```python
import argparse
import asyncio
import json
import time

from .classifier import classify
from .config import settings
from .filters import Filters
from .notifier import send_alert, send_test
from .store import Store
from .stream import news_stream


async def run() -> None:
    store = Store(settings.db_path)
    filters = Filters(settings)
    print(
        f"candlechaser starting "
        f"(threshold={settings.alert_score_threshold}, model={settings.openai_model})"
    )
    async for item in news_stream():
        received = time.time()
        reason = filters.pre_skip(item)
        if reason:
            # Don't log outside-window skips; overnight wire volume would bloat the DB.
            if reason != "outside_alert_window":
                store.log(item, skip_reason=reason)
            continue

        result = await classify(item)
        if result is None:
            store.log(item, skip_reason="classifier_error")
            continue

        alerted = False
        if result["score"] >= settings.alert_score_threshold:
            symbols = filters.tradeable_symbols([t["symbol"] for t in result["tickers"]])
            if symbols:
                alert_result = {
                    **result,
                    "tickers": [t for t in result["tickers"] if t["symbol"] in symbols],
                }
                try:
                    await send_alert(item, alert_result, time.time() - received)
                    filters.mark_alerted(symbols)
                    alerted = True
                except Exception as exc:
                    print(f"alert send failed: {exc!r}")

        store.log(item, result=result, alerted=alerted)
        flag = "ALERT" if alerted else "     "
        print(f"{flag} [{result['score']:3d}] {item.get('headline', '')[:110]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="candlechaser: realtime headline alerts")
    parser.add_argument("--test-telegram", action="store_true",
                        help="send a test Telegram message and exit")
    parser.add_argument("--classify", metavar="HEADLINE",
                        help="classify a single headline and print the result")
    args = parser.parse_args()

    if args.test_telegram:
        asyncio.run(send_test())
        print("test message sent")
        return
    if args.classify:
        fake = {"headline": args.classify, "summary": "", "symbols": [],
                "source": "manual", "created_at": ""}
        print(json.dumps(asyncio.run(classify(fake)), indent=2))
        return
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

---

## First-run checklist

```bash
git init && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys
python -m app.main --test-telegram
python -m app.main --classify "NVDA CEO says Marvell will be the next trillion dollar company"
python -m app.main     # leave running during market hours
```

Expected from `--classify`: score 80+, tickers `[{"symbol": "MRVL", "direction": "up"}]`,
category `exec_comment`.

## Tuning after the first week

Query the log to see what you would have been alerted on at different thresholds:

```sql
SELECT score, headline, result_tickers, datetime(received_at, 'unixepoch', 'localtime') AS at
FROM headlines
WHERE score >= 60
ORDER BY received_at DESC
LIMIT 50;
```

Then compare against intraday charts for those tickers. Raise/lower
`ALERT_SCORE_THRESHOLD` and tighten the prompt's scoring rubric based on the false
positives you see — the prompt is the product; expect to iterate on it weekly.

## V2 roadmap (don't build yet)

- **Price confirmation**: before alerting, pull a realtime quote/volume snapshot from
  Alpaca and include "already moved +3.2%" in the alert so you know if you're early or late.
- **Feedback loop**: nightly job joins the headlines log with actual price moves to measure
  classifier precision/recall and auto-suggest threshold changes.
- **Faster/wider wire**: Benzinga Pro API or Polygon news if Alpaca's coverage misses things.
- **Dashboard**: small Next.js UI over the SQLite log (reuse earningsfollower patterns).
- **Paper-trade execution**: auto-fire Alpaca paper orders on 90+ scores to measure realized
  edge before risking money.
