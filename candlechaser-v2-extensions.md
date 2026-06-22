# candlechaser v2 — multi-source signal engine

Paste this whole document into Cursor in the candlechaser repo and say:
"Implement Phase 0 of this spec." Then ship phases one at a time, in order.
Do NOT build everything at once — each phase is independently shippable and testable.

## Context for the agent

You are working in the candlechaser repo. The v1 codebase is a single Python worker:

- `app/stream.py` — Alpaca news websocket (async generator yielding news dicts)
- `app/filters.py` — dedupe, market-hours window, per-ticker cooldown
- `app/classifier.py` + `app/prompts.py` — OpenAI scoring (0–100 "will this move a stock ≥2% intraday"), returns `{score, tickers: [{symbol, direction}], category, rationale}`
- `app/notifier.py` — Telegram alerts
- `app/store.py` — SQLite log of every headline + score
- `app/main.py` — orchestration loop + `--test-telegram` / `--classify` CLI flags
- `app/config.py` — pydantic-settings, env-driven

v2 turns this from a single-source news alerter into a multi-source event engine.
Critical requirement throughout: **every alert must carry a unique, human-readable
alert ID and source tag** so the owner can journal each trade against the exact alert
that triggered it in a separate trade-journaling app (happytrader).

---

## Phase 0 — core refactor: event model, alert IDs, journaling export

This phase changes no trading logic. It restructures so new sources plug in cleanly.

### 0.1 Normalized Event model

Create `app/events.py` with a dataclass all sources emit:

```python
@dataclass
class Event:
    source: str        # "news" | "filing" | "halt" | "options"
    source_id: str     # unique id within the source (wire id, accession number, etc.)
    ts: float          # time.time() when we received it
    text: str          # headline / filing summary / halt description
    symbols: list[str] # tagged symbols if the source provides them
    url: str
    meta: dict         # source-specific extras (form_type, halt_code, etc.)
```

### 0.2 Sources package

- Move `app/stream.py` to `app/sources/news.py`; wrap its yielded dicts into `Event`s.
- Each source module exposes `async def stream() -> AsyncIterator[Event]` and handles
  its own reconnect/poll loop forever.
- `app/main.py` runs all enabled sources concurrently (one asyncio task per source,
  all pushing into a single `asyncio.Queue`; the pipeline consumes the queue).
- Per-source enable flags in config: `ENABLE_NEWS=true`, `ENABLE_FILINGS=false`,
  `ENABLE_HALTS=false`, `ENABLE_OPTIONS=false` (later phases flip them on).

### 0.3 Alert IDs (the journaling key)

- Format: `CC-YYYYMMDD-NNN` (e.g. `CC-20260611-007`), where NNN is a per-day sequence
  persisted in SQLite — must survive restarts (derive next NNN from the alerts table).
- New `alerts` table:

```sql
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,        -- CC-20260611-007
    created_at REAL NOT NULL,
    source TEXT NOT NULL,             -- news | filing | halt | options
    subtype TEXT,                     -- e.g. 8-K, LUDP, cluster_buy, exec_comment
    tickers TEXT NOT NULL,            -- JSON: [{"symbol","direction"}]
    score INTEGER,
    headline TEXT,
    url TEXT,
    sympathy TEXT                     -- JSON list, filled in Phase 1
);
```

- Every Telegram alert MUST begin with a tag line:

```
[CC-20260611-007 | NEWS:exec_comment]
MRVL UP — score 84/100
NVDA CEO says Marvell will be the next trillion-dollar company
...
```

  The bracket tag is what gets copy-pasted into the happytrader journal entry, so keep
  it short, on its own line, and always first.

### 0.4 Journaling export

- `python -m app.main --export-alerts [--since YYYY-MM-DD]` writes `alerts.csv` with
  columns: `alert_id, created_at_iso, source, subtype, symbol, direction, score, headline, url`
  (one row per ticker per alert).
- This CSV is the hand-off format to happytrader. Keep the schema stable.

### Phase 0 acceptance

- Worker runs exactly as v1 (news only), but alerts now show the `[CC-...]` tag.
- `--export-alerts` produces a valid CSV.
- Restarting the worker continues the day's alert sequence without duplicate IDs.

---

## Phase 1 — sympathy enricher (second-order plays)

When a stock moves on news, its basket peers move minutes later. Make every alert
include "who else moves on this."

- Create `data/baskets.yaml`: curated theme baskets, e.g.

```yaml
ai_semis: [NVDA, AMD, AVGO, MRVL, MU, SMCI, ARM, TSM]
ai_power: [VST, CEG, OKLO, SMR, TLN]
crypto_proxies: [COIN, MSTR, HOOD, MARA, RIOT]
glp1: [LLY, NVO, VKTX, HIMS]
# ... seed ~15 baskets; owner will curate over time
```

- Create `app/sympathy.py`: `def sympathy_for(symbols: list[str]) -> list[str]` —
  union of basket members sharing any basket with an alerted symbol, minus the alerted
  symbols themselves, capped at 6.
- Also add an optional `"sympathy_tickers"` field to the classifier JSON output
  (update the prompt: "list up to 3 OTHER tickers likely to move in sympathy").
  Merge LLM suggestions with basket lookups, dedupe.
- Alert format gains one line: `Sympathy: AVGO AMD SMCI`.
- Store the sympathy list in the `alerts.sympathy` column.

### Phase 1 acceptance

`--classify "NVDA CEO says Marvell will be the next trillion dollar company"` returns
MRVL as primary and other ai_semis names as sympathy.

---

## Phase 2 — SEC filing source (the news before the news)

Filings hit EDGAR minutes before wire services write the headline. Source: `app/sources/filings.py`.

### Ingest

- Poll the EDGAR current-filings Atom feed every 10 seconds:
  `https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&company=&dateb=&owner=include&count=100&output=atom`
- REQUIRED by SEC: send a real User-Agent header like
  `candlechaser/1.0 (your-email@example.com)` (make it an env var, `SEC_USER_AGENT`).
  Stay well under 10 requests/second.
- Dedupe by accession number.
- Map CIK → ticker using `https://www.sec.gov/files/company_tickers.json`
  (download at startup, refresh daily, cache to disk). Skip filings with no ticker.

### Filter to high-signal form types only

| Form | Why it moves stocks | Handling |
|---|---|---|
| 8-K | guidance, CEO exits, material agreements | fetch filing text, extract Item numbers, send items + first ~1500 chars to the classifier with a filing-specific prompt |
| SC 13D / 13D/A | activist stake | alert directly, score 85, direction up, subtype `activist_stake` — no LLM needed |
| Form 4 | insider buys/sells | parse the XML; only open-market purchases (transaction code P). Track per-ticker: if 2+ distinct insiders buy within 5 trading days → alert subtype `cluster_buy`, score 75. Single buys: log only, no alert |
| S-1 / 424B5 | dilution / offering | alert subtype `offering`, direction down, score 70 |

Everything else: ignore (do not even log; volume is huge).

- Add `app/prompts.py` second prompt `FILING_PROMPT` tuned for 8-Ks: emphasize Item
  5.02 (executive departures), 1.01 (material agreements), 2.02 (results), 7.01/8.01
  (reg-FD / other events); recaps of already-public news score low.
- Filing alerts use source tag `FILING`, e.g. `[CC-20260611-012 | FILING:8-K]`.
- Respect the same per-ticker cooldown, BUT a filing alert and a news alert on the same
  ticker within the cooldown are both allowed (different sources often confirm each
  other — that is information, not spam). Cooldown is per (ticker, source).

### Phase 2 acceptance

- Worker logs filings during market hours; an 8-K with a 5.02 item produces an alert.
- A simulated pair of Form 4 P-purchases by two insiders triggers a `cluster_buy` alert.

---

## Phase 3 — halt source (LULD resumes)

Source: `app/sources/halts.py`. Pure rules, no LLM.

- Poll `https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts` every 5 seconds during
  market hours.
- On NEW halt: immediate alert, subtype = halt code (`LUDP`, `T1`, `T12`, ...),
  direction `unclear`, score fixed at 80. Include halt time and reason code.
- When the resumption time appears in the feed: send a second alert
  `[CC-... | HALT:resume]` ~1 minute before resumption, referencing the original
  alert ID in the message body ("resume for CC-20260611-015").
- Halted tickers bypass the cooldown (a halt IS the confirmation).
- Bonus integration: if a halt arrives for a ticker that had any candlechaser alert in
  the last 30 minutes, prepend `CONFIRMED:` to the tag line and mention the earlier
  alert ID. This is the highest-conviction signal the system can produce.

### Phase 3 acceptance

Replay a sample of the halts RSS (save a real snapshot as a test fixture) and verify
halt + resume alerts fire once each with correct tags.

---

## Phase 4 — options flow source (OPTIONAL, gated, costs money)

Do not build until phases 0–3 are running live. Requires a Polygon.io options
subscription (websocket trades feed). Keep behind `ENABLE_OPTIONS=false` by default.

- Source: `app/sources/options.py`, Polygon options trades websocket.
- Rule-based detection (no LLM): flag a ticker when, within a 5-minute window:
  - aggregate premium of ask-side trades in a single contract > $200k, AND
  - volume > 5x that contract's open interest, AND
  - expiry ≤ 30 days, AND strike ≥ 5% OTM.
- Alert subtype `sweep`, direction = call→up / put→down, score 70.
- These alerts are *anticipatory* (no news yet) — say so in the alert body:
  "No public news. Possible positioning ahead of a catalyst."
- Same confirmation logic as halts: a later news/filing alert on the same ticker
  references the sweep's alert ID.

---

## Cross-cutting requirements (all phases)

1. **Alert ID discipline**: no Telegram message ever goes out without a `[CC-...]` tag.
   One alert ID per event, even if it covers multiple tickers.
2. **Everything logged**: events that don't alert still go in the `headlines`/events
   log with their source, for threshold tuning.
3. **Source isolation**: one source crashing (EDGAR down, RSS schema change) must not
   kill the worker — each source task catches its own exceptions, logs, backs off,
   retries forever.
4. **Config**: every threshold (scores, cooldowns, poll intervals, premium minimums)
   is an env var with the defaults above.
5. **Tests**: each source gets a fixture-based test (saved real payloads) so parsing
   regressions are caught without live connections. Add `pytest` to requirements.
6. **README**: update with the alert tag format, a table of source/subtype values, and
   the journaling workflow (copy the `[CC-...]` tag into the happytrader journal entry;
   export `alerts.csv` weekly for reconciliation).

## Suggested env additions

```
ENABLE_NEWS=true
ENABLE_FILINGS=true
ENABLE_HALTS=true
ENABLE_OPTIONS=false
SEC_USER_AGENT=candlechaser/1.0 you@example.com
EDGAR_POLL_SECONDS=10
HALTS_POLL_SECONDS=5
CLUSTER_BUY_WINDOW_DAYS=5
CLUSTER_BUY_MIN_INSIDERS=2
POLYGON_API_KEY=
```
