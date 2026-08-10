"""Monitor Reddit and turn chatter into a per-ticker sentiment signal.

Pipeline (mirrors how the waves/drift screens produce signals the paper trader
consumes):

  1. Pull the configured subreddit listings (and optionally top comments).
  2. Extract candidate tickers from the text - cashtags ($TSLA) and bare symbols
     validated against names we actually track, with a stoplist so common
     English words that happen to be tickers (e.g. "IT", "ALL", "GO") don't leak
     in. This is also the universe guard the brief calls for: we only ever trade
     names that already exist in our DB.
  3. Per ticker: count distinct mentions and measure *velocity* - mentions this
     scan vs. the ticker's trailing baseline (the acceleration / anti-pump
     guard). Only tickers clearing both the mention floor and the velocity floor
     get scored.
  4. Score sentiment into a structured verdict (direction, conviction, pump_risk,
     is_noise, sentiment, rationale) - via an LLM when configured, else a
     transparent keyword heuristic.
  5. Journal one RedditSignal row per qualifying ticker (auditable) and return
     the freshly scored signals.

Everything is best-effort: network/scoring failures are logged and skipped so a
scan never raises into the executor.
"""

from __future__ import annotations

import json
import logging
import math
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clients.apewisdom import ApeWisdomClient
from app.clients.llm import LLMClient
from app.clients.reddit import RedditClient
from app.config import get_settings
from app.db.models import Company, RedditSignal
from app.services.prices import load_price_series

logger = logging.getLogger(__name__)

# Cashtag ($AAPL) and bare uppercase candidates (1-5 chars).
_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
_BARE_RE = re.compile(r"\b([A-Z]{2,5})\b")

# Uppercase tokens that are real tickers but, on these subreddits, are almost
# always English/slang - require a cashtag for these to count.
_STOPLIST = {
    "A", "I", "ALL", "GO", "ON", "IT", "FOR", "ARE", "BE", "BY", "OR", "SO",
    "AT", "AN", "AM", "PM", "US", "USA", "USD", "CEO", "CFO", "COO", "IPO",
    "ETF", "EPS", "GDP", "FED", "SEC", "FDA", "DD", "YOLO", "FD", "FDS", "ATH",
    "IMO", "TLDR", "EOD", "EOY", "WSB", "OP", "EDIT", "PR", "Q1", "Q2", "Q3",
    "Q4", "AI", "EV", "PT", "TA", "RH", "HODL", "FOMO", "OTM", "ITM", "ER",
    "CPI", "PPI", "ROI", "YTD", "LOL", "WTF", "IRA", "HSA", "ID", "TV", "OK",
    "NO", "YES", "NOW", "NEW", "BIG", "BUY", "SELL", "CALL", "PUT", "RED",
    "LONG", "ITS", "OUT", "UP", "WAY", "GET", "ANY", "CAN", "ETA",
}

# Sentiment lexicons for the heuristic fallback.
_BULLISH = {
    "moon", "mooning", "rocket", "rockets", "calls", "call", "long", "longs",
    "buy", "buying", "bought", "bull", "bullish", "squeeze", "squeezing",
    "breakout", "ripping", "pump", "pumping", "tendies", "yolo", "send", "green",
    "up", "gains", "lambo", "diamond", "hold", "hodl", "undervalued", "load",
    "loading", "printing", "beat", "beats", "strong", "surge", "soar", "ath",
}
_BEARISH = {
    "puts", "put", "short", "shorts", "shorting", "sell", "selling", "sold",
    "bear", "bearish", "dump", "dumping", "crash", "crashing", "tank", "tanking",
    "red", "drop", "dropping", "bagholder", "bagholding", "rug", "rugged",
    "overvalued", "miss", "misses", "weak", "guh", "fell", "down", "plunge",
    "collapse", "bleeding", "rip",  # "rip" = R.I.P. on these subs
}
_PUMP_WORDS = {"moon", "rocket", "squeeze", "yolo", "lambo", "tendies", "send"}
_ROCKET_EMOJI = ("🚀", "🌙", "💎", "🙌")


@dataclass
class TickerAgg:
    ticker: str
    mention_count: int = 0
    texts: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    subreddits: set[str] = field(default_factory=set)


@dataclass
class Attention:
    """Per-ticker attention from ApeWisdom: mentions now vs. 24h ago, plus which
    monitored subreddits the ticker actually showed up in (for attribution)."""

    ticker: str
    mentions: int
    mentions_24h_ago: int
    upvotes: int
    subreddits: set[str] = field(default_factory=set)


def current_reddit_signals(db: Session, *, persist: bool = True) -> list[dict]:
    """Run one scan and return the scored, qualifying signals (also journaled).

    Discovery + velocity come from ApeWisdom (free, no-auth, not IP-blocked).
    Direction/sentiment is layered on: Reddit post text via OAuth when available
    (scored by LLM or keyword heuristic), else the recent price momentum
    (continuation). A signal dict mirrors the shape the other strategies emit so
    the executor's Reddit scan can treat it uniformly:
        {ticker, direction, conviction, score, sentiment, mention_count,
         mention_velocity, pump_risk, is_noise, rationale, subreddits, samples,
         scored_by}
    """
    settings = get_settings()
    known = _known_tickers(db)
    if not known:
        logger.info("reddit scan: no tracked tickers yet; nothing to match")
        return []

    today = date.today()
    attention = _fetch_apewisdom(settings, known) if settings.reddit_use_apewisdom else {}
    # Reddit post text is best-effort: it powers true sentiment direction when
    # OAuth creds are configured, and is the sole source when ApeWisdom is off.
    # Skip it entirely when ApeWisdom is on but Reddit isn't authenticated - the
    # public endpoints block datacenter IPs, so hitting them just spams 403s.
    reddit_authed = bool(settings.reddit_client_id and settings.reddit_client_secret)
    if reddit_authed or not settings.reddit_use_apewisdom:
        text_aggs = _collect_text(settings, known)
    else:
        text_aggs = {}

    if attention:
        candidates = _candidates_from_apewisdom(attention, text_aggs, settings)
    else:
        # No ApeWisdom: fall back to direct Reddit listing aggregates + DB
        # baseline velocity (only works with reachable Reddit creds).
        baselines = _baselines(db, settings, today)
        candidates = _candidates_from_text(text_aggs, baselines, settings)

    if not candidates:
        logger.info("reddit scan: no candidates cleared the mention/velocity gates")
        return []

    llm = LLMClient()
    signals: list[dict] = []
    try:
        for cand in candidates[:20]:  # hard cap on scoring work per scan
            agg = cand["agg"]
            velocity = cand["velocity"]
            mention_count = cand["mention_count"]

            if agg is not None and agg.texts:
                verdict = _score_text(agg, velocity, llm)
            else:
                verdict = _score_momentum(db, cand["ticker"], velocity, settings)

            verdict["score"] = round(
                velocity
                * abs(verdict.get("sentiment") or 0.0)
                * math.log1p(mention_count),
                3,
            )
            sig = {
                "ticker": cand["ticker"],
                "mention_count": mention_count,
                "mention_velocity": round(velocity, 2),
                "subreddits": sorted(
                    (agg.subreddits if agg else set()) | set(cand.get("subreddits") or [])
                ),
                "samples": (agg.samples[:5] if agg else cand.get("samples", [])),
                **verdict,
            }
            signals.append(sig)
            if persist:
                _journal(db, today, sig)
        if persist:
            db.commit()
    finally:
        llm.close()

    signals.sort(key=lambda s: s.get("score") or 0.0, reverse=True)
    return signals


def _fetch_apewisdom(settings, known: set[str]) -> dict[str, Attention]:
    out: dict[str, Attention] = {}
    try:
        with ApeWisdomClient() as ape:
            rows = ape.rankings(
                filter_=settings.reddit_apewisdom_filter,
                pages=settings.reddit_apewisdom_pages,
            )
            for r in rows:
                sym = str(r.get("ticker", "")).upper()
                if not sym or sym not in known:
                    continue
                out[sym] = Attention(
                    ticker=sym,
                    mentions=int(r.get("mentions") or 0),
                    mentions_24h_ago=int(r.get("mentions_24h_ago") or 0),
                    upvotes=int(r.get("upvotes") or 0),
                )
            # Per-subreddit attribution: the primary filter (e.g. all-stocks) is
            # an aggregate and can't tell us *where* the chatter is, so we also
            # pull each monitored subreddit's board and tag the tickers we're
            # already tracking with the subs they surface in. This is what lets
            # the scorecard score which communities actually pay off.
            for sub in settings.reddit_apewisdom_sub_filter_list:
                try:
                    sub_rows = ape.rankings(filter_=sub, pages=settings.reddit_apewisdom_pages)
                except Exception as exc:  # noqa: BLE001 - one bad sub can't break the scan
                    logger.warning("ApeWisdom sub %s failed: %s", sub, exc)
                    continue
                for r in sub_rows:
                    att = out.get(str(r.get("ticker", "")).upper())
                    if att is not None:
                        att.subreddits.add(sub)
    except Exception as exc:  # noqa: BLE001 - never let the source break the scan
        logger.warning("ApeWisdom fetch failed: %s", exc)
        return {}
    logger.info("ApeWisdom: %d tracked names with mentions", len(out))
    return out


def _candidates_from_apewisdom(
    attention: dict[str, Attention],
    text_aggs: dict[str, TickerAgg],
    settings,
) -> list[dict]:
    """Build scored candidates using ApeWisdom mentions + its own 24h baseline
    for velocity, attaching Reddit post text for direction when we have it."""
    cands: list[dict] = []
    for sym, att in attention.items():
        if att.mentions < settings.reddit_min_mentions:
            continue
        baseline = att.mentions_24h_ago if att.mentions_24h_ago > 0 else None
        velocity = _velocity(att.mentions, baseline, settings)
        if velocity < settings.reddit_min_velocity:
            continue
        cands.append(
            {
                "ticker": sym,
                "mention_count": att.mentions,
                "velocity": velocity,
                "agg": text_aggs.get(sym),
                "subreddits": sorted(att.subreddits),
            }
        )
    cands.sort(key=lambda c: c["mention_count"], reverse=True)
    return cands


def _candidates_from_text(
    text_aggs: dict[str, TickerAgg], baselines: dict[str, float], settings
) -> list[dict]:
    cands: list[dict] = []
    for sym, agg in text_aggs.items():
        if agg.mention_count < settings.reddit_min_mentions:
            continue
        velocity = _velocity(agg.mention_count, baselines.get(sym), settings)
        if velocity < settings.reddit_min_velocity:
            continue
        cands.append(
            {
                "ticker": sym,
                "mention_count": agg.mention_count,
                "velocity": velocity,
                "agg": agg,
            }
        )
    cands.sort(key=lambda c: c["mention_count"], reverse=True)
    return cands


def latest_reddit_signal(db: Session, ticker: str) -> RedditSignal | None:
    """Most recent journaled signal for a ticker (used by the exit check)."""
    return db.scalars(
        select(RedditSignal)
        .where(RedditSignal.ticker == ticker.upper())
        .order_by(RedditSignal.scan_date.desc(), RedditSignal.id.desc())
    ).first()


def recent_reddit_signals(db: Session, *, limit: int = 50) -> list[dict]:
    """Read-side: the freshest journaled signals (no polling), for the UI/API."""
    latest = db.scalars(select(func.max(RedditSignal.scan_date))).first()
    if latest is None:
        return []
    rows = db.scalars(
        select(RedditSignal)
        .where(RedditSignal.scan_date == latest)
        .order_by(RedditSignal.score.desc())
        .limit(limit)
    ).all()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(r: RedditSignal) -> dict:
    try:
        samples = json.loads(r.samples or "[]")
    except json.JSONDecodeError:
        samples = []
    return {
        "scan_date": r.scan_date.isoformat() if r.scan_date else None,
        "ticker": r.ticker,
        "mention_count": r.mention_count,
        "mention_velocity": r.mention_velocity,
        "score": r.score,
        "sentiment": r.sentiment,
        "direction": r.direction,
        "conviction": r.conviction,
        "pump_risk": r.pump_risk,
        "is_noise": r.is_noise,
        "scored_by": r.scored_by,
        "rationale": r.rationale,
        "subreddits": (r.subreddits or "").split(",") if r.subreddits else [],
        "samples": samples,
    }


# --- collection --------------------------------------------------------------


def _known_tickers(db: Session) -> set[str]:
    return {t.upper() for t in db.scalars(select(Company.ticker)).all()}


def _collect_text(settings, known: set[str]) -> dict[str, TickerAgg]:
    """Pull listings/comments and aggregate mentions per known ticker.

    Best-effort: returns whatever Reddit text we can reach (everything when
    OAuth creds are set; nothing if the public endpoints block us). Used for
    sentiment direction on top of ApeWisdom's attention numbers."""
    aggregates: dict[str, TickerAgg] = {}

    def add(ticker: str, text: str, subreddit: str, permalink: str | None) -> None:
        agg = aggregates.get(ticker)
        if agg is None:
            agg = TickerAgg(ticker=ticker)
            aggregates[ticker] = agg
        agg.mention_count += 1
        agg.subreddits.add(subreddit)
        if text:
            agg.texts.append(text[:600])
        if permalink and len(agg.samples) < 5:
            agg.samples.append(f"https://www.reddit.com{permalink}")

    with RedditClient() as reddit:
        for sub in settings.reddit_subreddit_list:
            for kind in settings.reddit_listing_list:
                posts = reddit.listing(sub, kind=kind, limit=settings.reddit_posts_limit)
                for post in posts:
                    text = f"{post.get('title', '')} {post.get('selftext', '')}"
                    permalink = post.get("permalink")
                    for tk in _extract_tickers(text, known):
                        add(tk, text, sub, permalink)
                    if settings.reddit_read_comments and post.get("id"):
                        for c in reddit.comments(
                            sub, post["id"], limit=settings.reddit_comments_limit
                        ):
                            body = c.get("body", "")
                            for tk in _extract_tickers(body, known):
                                add(tk, body, sub, permalink)
    return aggregates


def _extract_tickers(text: str, known: set[str]) -> set[str]:
    if not text:
        return set()
    found: set[str] = set()
    # Cashtags are explicit - accept any that maps to a tracked ticker.
    for m in _CASHTAG_RE.findall(text):
        sym = m.upper()
        if sym in known:
            found.add(sym)
    # Bare uppercase tokens: must be tracked AND not a common-word stoplist hit.
    for m in _BARE_RE.findall(text):
        if m in _STOPLIST:
            continue
        if m in known:
            found.add(m)
    return found


# --- velocity / baseline -----------------------------------------------------


def _baselines(db: Session, settings, today: date) -> dict[str, float]:
    """Trailing mean mentions/scan per ticker over the baseline window."""
    start = today - timedelta(days=settings.reddit_baseline_days)
    rows = db.scalars(
        select(RedditSignal).where(
            RedditSignal.scan_date >= start, RedditSignal.scan_date < today
        )
    ).all()
    by_ticker: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        by_ticker[r.ticker].append(r.mention_count or 0)
    return {t: statistics.fmean(v) for t, v in by_ticker.items() if v}


def _velocity(count: int, baseline: float | None, settings) -> float:
    """Mentions this scan as a multiple of the trailing baseline.

    With no history we can't measure acceleration, so we anchor the baseline to
    the mention floor: a fresh spike must run ~2x the floor to clear a velocity
    threshold of 2.0, which keeps day-one signals from trading blind."""
    if not baseline or baseline <= 0:
        baseline = float(settings.reddit_min_mentions)
    return count / baseline


# --- scoring -----------------------------------------------------------------

_LLM_SYSTEM = (
    "You are a markets analyst grading Reddit chatter about a single stock. "
    "Reddit is sarcastic, ironic, slang- and emoji-heavy, and full of cope from "
    "people bagholding losing positions and of coordinated pump-and-dump hype. "
    "Judge the GENUINE, actionable directional lean of the crowd, not the volume "
    "of noise. Distinguish sincere bullishness from 'please save me' cope, and "
    "flag coordinated-pump language (rocket/moon/'get in now'/price targets with "
    "no thesis). Respond ONLY with a JSON object with keys: "
    "direction ('bullish'|'bearish'|'neutral'), conviction ('low'|'medium'|"
    "'high'), sentiment (number in [-1,1]), pump_risk ('low'|'medium'|'high'), "
    "is_noise (boolean), rationale (one sentence)."
)


def _score_text(agg: TickerAgg, velocity: float, llm: LLMClient) -> dict:
    """Direction/sentiment from the Reddit post text (LLM if configured, else a
    keyword heuristic). The caller adds the composite ranking score."""
    verdict = _score_llm(agg, velocity, llm) if llm.enabled else None
    if verdict is None:
        verdict = _score_heuristic(agg, velocity)
    return verdict


def _score_momentum(db: Session, ticker: str, velocity: float, settings) -> dict:
    """Direction fallback when we have no Reddit text: trade the continuation of
    the recent price move. The attention spike says people are watching; momentum
    says which way the crowd-fueled move is already going."""
    series = load_price_series(db, ticker)
    closes = [c for c in series.close if c]
    look = settings.reddit_momentum_lookback_days
    if len(closes) < look + 1:
        return {
            "direction": "neutral",
            "conviction": "low",
            "sentiment": 0.0,
            "pump_risk": "low",
            "is_noise": True,
            "rationale": "insufficient price history for a momentum read",
            "scored_by": "momentum",
        }
    now_px = closes[-1]
    past_px = closes[-(look + 1)]
    ret = (now_px / past_px - 1.0) if past_px else 0.0

    deadband = settings.reddit_momentum_deadband
    if ret > deadband:
        direction = "bullish"
    elif ret < -deadband:
        direction = "bearish"
    else:
        direction = "neutral"
    is_noise = direction == "neutral"

    # A 10% move over the window is treated as a full-strength sentiment read.
    sentiment = max(-1.0, min(1.0, ret / 0.10))
    abs_ret = abs(ret)

    # Pump/late-entry risk: a vertical mention spike on a name that has ALREADY
    # run hard is where you become exit liquidity.
    if velocity >= 6 and abs_ret >= 0.15:
        pump_risk = "high"
    elif velocity >= 4 or abs_ret >= 0.20:
        pump_risk = "medium"
    else:
        pump_risk = "low"

    if velocity >= 3 and abs_ret >= 0.06:
        conviction = "high"
    elif velocity >= 2 and abs_ret >= 0.02:
        conviction = "medium"
    else:
        conviction = "low"

    rationale = (
        f"No post text; trading momentum continuation: {ret * 100:+.1f}% over "
        f"{look} trading days on a {velocity:.1f}x mention spike."
    )
    return {
        "direction": direction,
        "conviction": conviction,
        "sentiment": round(sentiment, 3),
        "pump_risk": pump_risk,
        "is_noise": is_noise,
        "rationale": rationale,
        "scored_by": "momentum",
    }


def _score_llm(agg: TickerAgg, velocity: float, llm: LLMClient) -> dict | None:
    sample = "\n---\n".join(agg.texts[:25]) or "(no text captured)"
    user = (
        f"Ticker: ${agg.ticker}\n"
        f"Mentions this scan: {agg.mention_count} (velocity {velocity:.1f}x baseline)\n"
        f"Subreddits: {', '.join(sorted(agg.subreddits))}\n\n"
        f"Posts/comments mentioning it:\n{sample}"
    )
    data = llm.score_json(_LLM_SYSTEM, user)
    if not isinstance(data, dict):
        return None
    direction = str(data.get("direction", "neutral")).lower()
    if direction not in ("bullish", "bearish", "neutral"):
        direction = "neutral"
    conviction = str(data.get("conviction", "low")).lower()
    if conviction not in ("low", "medium", "high"):
        conviction = "low"
    pump_risk = str(data.get("pump_risk", "low")).lower()
    if pump_risk not in ("low", "medium", "high"):
        pump_risk = "low"
    try:
        sentiment = max(-1.0, min(1.0, float(data.get("sentiment", 0.0))))
    except (TypeError, ValueError):
        sentiment = 0.0
    return {
        "direction": direction,
        "conviction": conviction,
        "sentiment": round(sentiment, 3),
        "pump_risk": pump_risk,
        "is_noise": bool(data.get("is_noise", False)),
        "rationale": str(data.get("rationale", ""))[:1000],
        "scored_by": "llm",
    }


def _score_heuristic(agg: TickerAgg, velocity: float) -> dict:
    """Transparent keyword + emoji fallback when no LLM is configured."""
    bull = bear = pump_hits = emoji_hits = 0
    for text in agg.texts:
        lower = text.lower()
        tokens = re.findall(r"[a-z']+", lower)
        bull += sum(1 for t in tokens if t in _BULLISH)
        bear += sum(1 for t in tokens if t in _BEARISH)
        pump_hits += sum(1 for t in tokens if t in _PUMP_WORDS)
        emoji_hits += sum(text.count(e) for e in _ROCKET_EMOJI)

    total = bull + bear
    sentiment = (bull - bear) / total if total else 0.0
    direction = (
        "bullish" if sentiment > 0.1 else "bearish" if sentiment < -0.1 else "neutral"
    )
    is_noise = direction == "neutral" or total < 3

    # Pump risk: a vertical mention spike plus heavy hype/emoji language.
    pump_signal = pump_hits + emoji_hits
    if velocity >= 6 and pump_signal >= 5:
        pump_risk = "high"
    elif velocity >= 4 or pump_signal >= 5:
        pump_risk = "medium"
    else:
        pump_risk = "low"

    abs_sent = abs(sentiment)
    if agg.mention_count >= 16 and velocity >= 3 and abs_sent >= 0.4:
        conviction = "high"
    elif agg.mention_count >= 8 and velocity >= 2 and abs_sent >= 0.2:
        conviction = "medium"
    else:
        conviction = "low"

    rationale = (
        f"{bull} bullish vs {bear} bearish keyword hits across "
        f"{agg.mention_count} mentions ({velocity:.1f}x baseline); "
        f"pump signal {pump_signal}."
    )
    return {
        "direction": direction,
        "conviction": conviction,
        "sentiment": round(sentiment, 3),
        "pump_risk": pump_risk,
        "is_noise": is_noise,
        "rationale": rationale,
        "scored_by": "heuristic",
    }


# --- persistence -------------------------------------------------------------


def _journal(db: Session, scan_date: date, sig: dict) -> None:
    existing = db.scalars(
        select(RedditSignal).where(
            RedditSignal.scan_date == scan_date,
            RedditSignal.ticker == sig["ticker"],
        )
    ).first()
    row = existing or RedditSignal(scan_date=scan_date, ticker=sig["ticker"])
    row.mention_count = sig["mention_count"]
    row.mention_velocity = sig["mention_velocity"]
    row.score = sig.get("score")
    row.sentiment = sig.get("sentiment")
    row.direction = sig.get("direction", "neutral")
    row.conviction = sig.get("conviction", "low")
    row.pump_risk = sig.get("pump_risk", "low")
    row.is_noise = bool(sig.get("is_noise", False))
    row.scored_by = sig.get("scored_by", "heuristic")
    row.rationale = (sig.get("rationale") or "")[:1024]
    row.subreddits = ",".join(sig.get("subreddits") or [])[:256]
    row.samples = json.dumps(sig.get("samples") or [])[:1024]
    if existing is None:
        db.add(row)
