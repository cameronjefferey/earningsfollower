from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.clients import yahoo
from app.clients.fmp import FMPClient, FMPError
from app.config import get_settings
from app.db.models import (
    AnalystSnapshot,
    Company,
    EarningsEvent,
    ImpliedMove,
    ImpliedMoveSnapshot,
    PeerLink,
    PriceBar,
    RefreshLog,
    ThemeMembership,
)
from app.universe import load_universe

logger = logging.getLogger(__name__)


def _timing_from_fmp(value: Any) -> str:
    """Normalize FMP-ish timing strings to bmo / amc / unknown.

    Stable FMP currently omits ``time`` entirely; keep parsers for the older
    calendar shapes and common prose variants in case they return later.
    """
    v = (str(value or "")).strip().lower()
    if not v:
        return "unknown"
    if v in {"bmo", "amc"}:
        return v
    if v in {"before market open", "before-open", "before open", "pre-market", "premarket"}:
        return "bmo"
    if v in {"after market close", "after-close", "after close", "post-market", "postmarket"}:
        return "amc"
    if "before" in v and "open" in v:
        return "bmo"
    if ("after" in v and "close" in v) or v.endswith("amc"):
        return "amc"
    if v.endswith("bmo") or v.startswith("bmo"):
        return "bmo"
    return "unknown"


def refresh_all(db: Session, *, expand_peers: bool | None = None) -> dict[str, Any]:
    """Full data refresh: build the universe, then ingest each tracked ticker.

    Resilient by design: a failure on one ticker is logged and skipped so the
    rest of the refresh still completes (important on free-tier rate limits).
    """
    # Drop cached calendar cards so the next /earnings read sees fresh stats.
    from app.cache import clear as clear_response_cache

    clear_response_cache()
    settings = get_settings()
    universe = load_universe()
    if expand_peers is None:
        expand_peers = universe.expand_with_fmp_peers

    log = RefreshLog(started_at=datetime.utcnow(), status="running")
    db.add(log)
    db.commit()

    processed = 0
    errors: list[str] = []
    # Data-quality counters: pieces that silently came back empty (vs. crashed).
    no_prices: list[str] = []
    no_earnings: list[str] = []
    no_implied: list[str] = []

    with FMPClient() as fmp:
        tracked = _build_universe(db, fmp, expand_peers=expand_peers)
        # Whole-market sweep: liquid names reporting in the calendar window, so
        # earnings + PEAD aren't limited to the curated themes. Curated names are
        # always kept (waves needs their theme/peer mapping).
        calendar, upcoming = _build_calendar_universe(db, fmp, settings)
        seed = set(tracked)
        all_tickers = sorted(seed | set(calendar))
        logger.info(
            "Tracking %d tickers (%d curated + %d calendar)",
            len(all_tickers), len(seed), len(set(calendar) - seed),
        )

        # Earnings come from FMP's per-symbol endpoint (full multi-year history +
        # upcoming estimates), set inside ingest_company. Implied move (yfinance)
        # is pulled only for curated names and names reporting soon, since it
        # rate-limits hard and the drift screen doesn't use it.
        for ticker in all_tickers:
            try:
                report = ingest_company(
                    db,
                    fmp,
                    ticker,
                    history_years=settings.history_years,
                    fmp_earnings=fmp.enabled,
                    fetch_earnings=not fmp.enabled,
                    fetch_implied=(ticker in seed or ticker in upcoming),
                )
                db.commit()
                processed += 1
                if not report["prices"]:
                    no_prices.append(ticker)
                if not report["earnings"]:
                    no_earnings.append(ticker)
                if not report["implied"]:
                    no_implied.append(ticker)
            except FMPError as exc:
                # Likely a bad key / hard rate-limit; stop hammering FMP but keep
                # whatever we already ingested.
                db.rollback()
                msg = f"FMP error on {ticker}: {exc}"
                logger.warning(msg)
                errors.append(msg)
                break
            except Exception as exc:  # noqa: BLE001 - keep refresh resilient
                db.rollback()
                msg = f"{ticker}: {exc}"
                logger.warning("Ingest failed for %s", ticker, exc_info=True)
                errors.append(msg)

    log.finished_at = datetime.utcnow()
    # "ok" only when nothing crashed AND core data (prices, earnings) landed for
    # every *curated* ticker. Gaps among the wide calendar sweep (odd ADRs, no
    # FMP coverage) are expected and shouldn't flip the health signal; missing
    # implied moves alone is a soft gap too.
    core_complete = (
        not errors
        and not (set(no_prices) & seed)
        and not (set(no_earnings) & seed)
    )
    log.status = "ok" if core_complete else "partial"
    detail_parts = [
        f"processed={processed}",
        f"tracked={len(all_tickers)}",
        f"curated={len(seed)}",
        f"calendar={len(set(calendar) - seed)}",
        f"errors={len(errors)}",
        f"no_prices={len(no_prices)}",
        f"no_earnings={len(no_earnings)}",
        f"no_implied={len(no_implied)}",
    ]
    if no_prices:
        detail_parts.append("prices_missing: " + ",".join(no_prices[:10]))
    if no_earnings:
        detail_parts.append("earnings_missing: " + ",".join(no_earnings[:10]))
    if errors:
        detail_parts.append("err: " + " | ".join(errors[:3]))
    log.detail = "; ".join(detail_parts)
    db.commit()

    # Persist board snapshots + daily digest so paid pages and the homepage
    # stay fast / useful after each refresh.
    board_stats: dict = {}
    digest_date: str | None = None
    boards_error: str | None = None
    try:
        from app.services import board_snapshots, digest as digest_svc

        board_stats = board_snapshots.refresh_board_snapshots(db)
        digest_payload = digest_svc.build_digest(db)
        digest_svc.persist_digest(db, digest_payload)
        digest_date = digest_payload.get("date")
    except Exception as exc:  # noqa: BLE001 - never fail the whole refresh on boards
        logger.warning("Board snapshot / digest failed: %s", exc, exc_info=True)
        boards_error = str(exc)
        if log.status == "ok":
            log.status = "partial"
            db.commit()

    return {
        "processed": processed,
        "tracked": len(all_tickers),
        "curated": len(seed),
        "calendar": len(set(calendar) - seed),
        "errors": errors,
        "no_prices": no_prices,
        "no_earnings": no_earnings,
        "no_implied": no_implied,
        "status": log.status,
        "boards": board_stats,
        "boards_error": boards_error,
        "digest_date": digest_date,
    }


def _build_universe(
    db: Session, fmp: FMPClient, *, expand_peers: bool
) -> list[str]:
    universe = load_universe()

    # ticker -> {theme_key: (label, is_seed)}
    membership: dict[str, dict[str, tuple[str, bool]]] = {}

    def add_member(ticker: str, key: str, label: str, seed: bool) -> None:
        ticker = ticker.upper()
        membership.setdefault(ticker, {})
        prev = membership[ticker].get(key)
        is_seed = seed or (prev[1] if prev else False)
        membership[ticker][key] = (label, is_seed)

    for theme in universe.themes:
        for t in theme.tickers:
            add_member(t, theme.key, theme.label, seed=True)

    # Expand each seed with its FMP peers, inheriting the seed's themes.
    if expand_peers and fmp.enabled:
        for theme in universe.themes:
            for seed in theme.tickers:
                try:
                    peers = fmp.stock_peers(seed)
                except FMPError as exc:
                    logger.warning("Peer fetch failed (%s): %s", seed, exc)
                    peers = []
                for peer in peers:
                    add_member(peer, theme.key, theme.label, seed=False)
                    _upsert_peer_link(db, seed, peer)
        db.commit()

    # Persist company + theme rows.
    for ticker, themes in membership.items():
        _ensure_company(db, ticker)
        existing = {
            m.theme_key: m
            for m in db.scalars(
                select(ThemeMembership).where(ThemeMembership.ticker == ticker)
            )
        }
        for key, (label, seed) in themes.items():
            if key in existing:
                existing[key].theme_label = label
                existing[key].is_seed = existing[key].is_seed or seed
            else:
                db.add(
                    ThemeMembership(
                        ticker=ticker, theme_key=key, theme_label=label, is_seed=seed
                    )
                )
    db.commit()
    return sorted(membership.keys())


def _sector_theme(sector: str) -> tuple[str, str]:
    """Map a company sector to a synthetic theme (key, label).

    Sector themes let wave detection group *any* co-sector names that come in
    through the whole-market calendar sweep, so the peer graph isn't limited to
    the hand-curated themes (e.g. DAL <-> UAL group under "Industrials").
    """
    label = sector.strip()
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return f"sector_{slug}", label


def _ensure_theme_membership(
    db: Session, ticker: str, key: str, label: str, *, seed: bool
) -> None:
    ticker = ticker.upper()
    existing = db.scalar(
        select(ThemeMembership).where(
            ThemeMembership.ticker == ticker,
            ThemeMembership.theme_key == key,
        )
    )
    if existing:
        existing.theme_label = label
        existing.is_seed = existing.is_seed or seed
    else:
        db.add(
            ThemeMembership(
                ticker=ticker, theme_key=key, theme_label=label, is_seed=seed
            )
        )


def _build_calendar_universe(
    db: Session, fmp: FMPClient, settings
) -> tuple[list[str], set[str]]:
    """Screen the whole market for liquid names reporting in the calendar window.

    Returns (names, upcoming) where ``names`` is the ranked list to ingest (the
    intersection of the liquidity screener and the earnings calendar, capped by
    ``calendar_max_names``) and ``upcoming`` is the subset reporting from today
    forward (those need an implied move for the pre-earnings playbook).
    """
    if not (settings.calendar_universe_enabled and fmp.enabled):
        return [], set()

    today = date.today()
    start = today - timedelta(days=settings.calendar_back_days)
    end = today + timedelta(days=settings.calendar_forward_days)

    # 1) Liquid, actively-traded US names above the size/price floor.
    try:
        screen = fmp.company_screener(
            market_cap_min=settings.calendar_min_market_cap,
            price_min=settings.calendar_min_price,
        )
    except FMPError as exc:
        logger.warning("Company screener failed: %s", exc)
        return [], set()
    liquid: dict[str, dict[str, Any]] = {}
    for r in screen:
        sym = (r.get("symbol") or "").upper()
        if sym:
            liquid[sym] = r
    if not liquid:
        logger.info("Company screener returned nothing; calendar universe off")
        return [], set()

    # 2) Who reports in the window (and who reports from today forward).
    try:
        cal = fmp.earnings_calendar(start.isoformat(), end.isoformat())
    except FMPError as exc:
        logger.warning("Earnings calendar %s..%s failed: %s", start, end, exc)
        return [], set()

    reporters: dict[str, dict[str, Any]] = {}
    upcoming: set[str] = set()
    for row in cal:
        sym = (row.get("symbol") or "").upper()
        if sym not in liquid:
            continue
        reporters.setdefault(sym, liquid[sym])
        d = _parse_date(row.get("date"))
        if d is not None and d >= today:
            upcoming.add(sym)

    # 3) Rank by market cap and cap the count to bound refresh load.
    ordered = sorted(
        reporters.items(),
        key=lambda kv: (kv[1].get("marketCap") or 0.0),
        reverse=True,
    )
    names = [sym for sym, _ in ordered[: settings.calendar_max_names]]

    # 4) Seed Company rows now so screens have sector/cap even if a later
    #    per-symbol profile call fails.
    for sym in names:
        info = reporters[sym]
        company = _ensure_company(db, sym)
        company.name = company.name or info.get("companyName")
        company.sector = company.sector or info.get("sector")
        company.exchange = (
            company.exchange
            or info.get("exchangeShortName")
            or info.get("exchange")
        )
        if not company.market_cap and info.get("marketCap"):
            try:
                company.market_cap = float(info["marketCap"])
            except (TypeError, ValueError):
                pass
        # Group by sector so wave/peer detection works across the whole market,
        # not just the curated themes. Curated seeds keep their richer themes and
        # simply gain their sector as an additional (non-seed) membership.
        if company.sector:
            key, label = _sector_theme(company.sector)
            _ensure_theme_membership(db, sym, key, label, seed=False)
    db.commit()

    logger.info(
        "Calendar universe: %d liquid names reporting %s..%s (%d upcoming)",
        len(names), start, end, len(upcoming & set(names)),
    )
    return names, upcoming


def ingest_company(
    db: Session,
    fmp: FMPClient,
    ticker: str,
    *,
    history_years: int = 5,
    fmp_earnings: bool | None = None,
    fetch_earnings: bool = True,
    fetch_implied: bool = True,
) -> dict[str, Any]:
    """Ingest one company's profile, earnings, prices, and implied move.

    Returns a quality report so the caller can tell whether each piece of data
    actually landed (vs. silently failing). On a paid FMP plan the per-symbol
    earnings endpoint is the primary source (full multi-year history); yfinance
    remains the fallback when FMP is unavailable.
    """
    ticker = ticker.upper()
    _ensure_company(db, ticker)
    if fmp_earnings is None:
        fmp_earnings = fmp.enabled

    got_fmp_earnings = False
    if fmp.enabled:
        try:
            _ingest_profile(db, fmp, ticker)
            if fmp_earnings:
                got_fmp_earnings = _ingest_earnings_fmp(
                    db, fmp, ticker, history_years
                )
            _ingest_analyst(db, fmp, ticker)
        except FMPError as exc:
            if "429" in str(exc):
                # Daily quota exhausted: stop using FMP for the rest of the run.
                logger.warning(
                    "FMP quota hit on %s; continuing without FMP", ticker
                )
                fmp.disable()
            else:
                raise

    # yfinance earnings scraping is unreliable on cloud IPs, so full history
    # ingest is only a fallback when FMP earnings aren't available. Timing
    # enrichment is cheaper and runs for names we already hit Yahoo for
    # (implied move) - FMP's stable calendar no longer returns BMO/AMC.
    got_yahoo_earnings = False
    if fetch_earnings and not got_fmp_earnings:
        got_yahoo_earnings = _ingest_earnings_yahoo(db, ticker)
    elif fetch_implied:
        # FMP stable earnings omit session time; pull BMO/AMC from Yahoo for
        # curated + upcoming names (same Yahoo budget as implied move).
        _enrich_earnings_timing_yahoo(db, ticker)

    price_source = _ingest_prices(db, ticker, history_years, fmp)
    # Implied move comes from yfinance, which rate-limits hard at scale. Only
    # pull it for names that need it (curated set + names reporting soon); the
    # post-earnings drift screen doesn't use it at all.
    got_implied = _ingest_implied_move(db, ticker) if fetch_implied else False

    return {
        "earnings": got_fmp_earnings or got_yahoo_earnings,
        "prices": price_source != "none",
        "price_source": price_source,
        "implied": got_implied,
    }


def _ingest_earnings_calendar(
    db: Session, fmp: FMPClient, tickers: list[str], history_years: int
) -> None:
    """Populate earnings events for all tracked tickers from FMP's bulk calendar.

    Fetches in <=90-day windows (free-tier range limit) across the history
    horizon plus near-future, and upserts the rows that match our universe.
    """
    if not fmp.enabled:
        return
    tracked = {t.upper() for t in tickers}
    today = date.today()
    start = today - timedelta(days=history_years * 365)
    end = today + timedelta(days=120)
    step = timedelta(days=90)

    cur = start
    matched = 0
    while cur < end:
        window_end = min(cur + step, end)
        try:
            rows = fmp.earnings_calendar(cur.isoformat(), window_end.isoformat())
        except FMPError as exc:
            logger.warning(
                "Earnings calendar %s..%s failed: %s", cur, window_end, exc
            )
            if "429" in str(exc):
                fmp.disable()
                break
            rows = []
        for row in rows:
            sym = (row.get("symbol") or "").upper()
            if sym not in tracked:
                continue
            d = _parse_date(row.get("date"))
            if d is None:
                continue
            matched += 1
            _upsert_earnings(
                db,
                ticker=sym,
                event_date=d,
                timing=_timing_from_fmp(row.get("time")),
                eps_estimate=_f(row.get("epsEstimated")),
                eps_actual=_f(row.get("epsActual")),
                revenue_estimate=_f(row.get("revenueEstimated")),
                revenue_actual=_f(row.get("revenueActual")),
                fiscal_period=None,
            )
        db.commit()
        cur = window_end
    logger.info("Earnings calendar: upserted %d events", matched)


def _ingest_profile(db: Session, fmp: FMPClient, ticker: str) -> None:
    profile = fmp.profile(ticker)
    if not profile:
        return
    company = db.get(Company, ticker)
    if company is None:
        company = Company(ticker=ticker)
        db.add(company)
    company.name = profile.get("companyName") or company.name
    company.sector = profile.get("sector") or company.sector
    company.industry = profile.get("industry") or company.industry
    company.exchange = (
        profile.get("exchange") or profile.get("exchangeShortName") or company.exchange
    )
    company.image = profile.get("image") or company.image
    mktcap = profile.get("marketCap") or profile.get("mktCap")
    if mktcap:
        try:
            company.market_cap = float(mktcap)
        except (TypeError, ValueError):
            pass


def _ingest_earnings_fmp(
    db: Session, fmp: FMPClient, ticker: str, history_years: int
) -> bool:
    """Returns True if any FMP earnings rows were ingested, else False."""
    limit = max(8, history_years * 4 + 8)
    rows = fmp.earnings(ticker, limit=limit)
    count = 0
    for row in rows:
        d = _parse_date(row.get("date"))
        if d is None:
            continue
        count += 1
        _upsert_earnings(
            db,
            ticker=ticker,
            event_date=d,
            timing=_timing_from_fmp(row.get("time")),
            eps_estimate=_f(row.get("epsEstimated")),
            eps_actual=_f(row.get("epsActual")),
            revenue_estimate=_f(row.get("revenueEstimated")),
            revenue_actual=_f(row.get("revenueActual")),
            fiscal_period=row.get("fiscalDateEnding"),
        )
    return count > 0


def _ingest_earnings_yahoo(db: Session, ticker: str) -> bool:
    rows = yahoo.get_earnings_dates(ticker, limit=28)
    for row in rows:
        _upsert_earnings(
            db,
            ticker=ticker,
            event_date=row["date"],
            timing=row.get("timing") or "unknown",
            eps_estimate=row.get("eps_estimate"),
            eps_actual=row.get("eps_actual"),
            revenue_estimate=None,
            revenue_actual=None,
            fiscal_period=None,
        )
    return bool(rows)


def _enrich_earnings_timing_yahoo(db: Session, ticker: str) -> int:
    """Fill bmo/amc from Yahoo when FMP left timing as unknown.

    Skips the Yahoo call when every event for the ticker already has a
    session. Returns the number of rows updated.
    """
    has_unknown = db.scalars(
        select(EarningsEvent.id).where(
            EarningsEvent.ticker == ticker,
            EarningsEvent.timing == "unknown",
        ).limit(1)
    ).first()
    if has_unknown is None:
        return 0

    rows = yahoo.get_earnings_dates(ticker, limit=28)
    if not rows:
        return 0

    by_date = {
        r["date"]: r.get("timing") or "unknown"
        for r in rows
        if r.get("date") is not None
    }
    updated = 0
    for event_date, timing in by_date.items():
        if timing not in {"bmo", "amc"}:
            continue
        event = db.scalars(
            select(EarningsEvent).where(
                EarningsEvent.ticker == ticker,
                EarningsEvent.date == event_date,
                EarningsEvent.timing == "unknown",
            )
        ).first()
        if event is None:
            continue
        event.timing = timing
        updated += 1
    return updated


def _ingest_analyst(db: Session, fmp: FMPClient, ticker: str) -> None:
    consensus = fmp.price_target_consensus(ticker)
    grades = fmp.grades_historical(ticker, limit=12)

    if not consensus and not grades:
        return

    row = db.get(AnalystSnapshot, ticker)
    if row is None:
        row = AnalystSnapshot(ticker=ticker)
        db.add(row)

    if consensus:
        row.price_target = _f(consensus.get("targetConsensus"))
        row.price_target_high = _f(consensus.get("targetHigh"))
        row.price_target_low = _f(consensus.get("targetLow"))

    if grades:
        latest = grades[0]
        row.strong_buy = _i(latest.get("analystRatingsStrongBuy"))
        row.buy = _i(latest.get("analystRatingsBuy"))
        row.hold = _i(latest.get("analystRatingsHold"))
        row.sell = _i(latest.get("analystRatingsSell"))
        row.strong_sell = _i(latest.get("analystRatingsStrongSell"))
        # Bullish count ~3 entries (months) earlier for a simple trend read.
        if len(grades) > 3:
            prior = grades[3]
            row.prev_bullish = (_i(prior.get("analystRatingsStrongBuy")) or 0) + (
                _i(prior.get("analystRatingsBuy")) or 0
            )

    row.updated_at = datetime.utcnow()


def _ingest_prices(
    db: Session, ticker: str, history_years: int, fmp: FMPClient | None = None
) -> str:
    """Ingest daily price bars. Prefers FMP (cloud-IP reliable) and falls back
    to yfinance. Returns the source actually used: "fmp", "yahoo", or "none"."""
    end = date.today() + timedelta(days=1)
    start = end - timedelta(days=int(history_years * 365.25) + 10)

    bars: list[dict[str, Any]] = []
    source = "none"
    if fmp is not None and fmp.enabled:
        try:
            raw = fmp.historical_prices(ticker, start.isoformat(), end.isoformat())
            bars = _map_fmp_prices(raw)
            if bars:
                source = "fmp"
        except FMPError as exc:
            if "429" in str(exc):
                logger.warning("FMP quota hit on %s prices; continuing", ticker)
                fmp.disable()
            else:
                logger.warning("FMP price fetch failed for %s: %s", ticker, exc)

    if not bars:
        bars = yahoo.get_prices(ticker, start, end)
        if bars:
            source = "yahoo"

    if not bars:
        return "none"

    # Replace the full window so corporate-action adjustments stay consistent.
    db.execute(delete(PriceBar).where(PriceBar.ticker == ticker))
    db.add_all(
        PriceBar(
            ticker=ticker,
            date=b["date"],
            open=b["open"],
            high=b["high"],
            low=b["low"],
            close=b["close"],
            adj_close=b["adj_close"],
            volume=b["volume"],
        )
        for b in bars
    )
    return source


def _map_fmp_prices(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    for r in raw:
        d = _parse_date(r.get("date"))
        if d is None:
            continue
        close = _f(r.get("close"))
        bars.append(
            {
                "date": d,
                "open": _f(r.get("open")),
                "high": _f(r.get("high")),
                "low": _f(r.get("low")),
                "close": close,
                # FMP's stable EOD close is split-adjusted; no separate adj field.
                "adj_close": close,
                "volume": _f(r.get("volume")),
            }
        )
    return bars


def _ingest_implied_move(db: Session, ticker: str) -> bool:
    next_event = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.ticker == ticker, EarningsEvent.date >= date.today())
        .order_by(EarningsEvent.date.asc())
    ).first()
    after = next_event.date if next_event else None
    result = yahoo.get_implied_move(ticker, after_date=after)
    if result.expected_move_pct is None:
        return False
    row = db.get(ImpliedMove, ticker)
    if row is None:
        row = ImpliedMove(ticker=ticker)
        db.add(row)
    row.expiry = result.expiry
    row.underlying_price = result.underlying_price
    row.atm_strike = result.atm_strike
    row.straddle_price = result.straddle_price
    row.expected_move_pct = result.expected_move_pct
    row.computed_at = datetime.utcnow()

    # Snapshot the priced-in move against the upcoming event so we can later
    # measure implied-vs-realized accuracy. One row per ticker/event/day.
    if next_event is not None:
        today = date.today()
        exists = db.scalars(
            select(ImpliedMoveSnapshot).where(
                ImpliedMoveSnapshot.ticker == ticker,
                ImpliedMoveSnapshot.event_date == next_event.date,
                ImpliedMoveSnapshot.snapshot_date == today,
            )
        ).first()
        if exists is None:
            db.add(
                ImpliedMoveSnapshot(
                    ticker=ticker,
                    event_date=next_event.date,
                    snapshot_date=today,
                    expected_move_pct=result.expected_move_pct,
                    underlying_price=result.underlying_price,
                )
            )
    return True


# --- upsert helpers ----------------------------------------------------------


def _ensure_company(db: Session, ticker: str) -> Company:
    company = db.get(Company, ticker)
    if company is None:
        company = Company(ticker=ticker)
        db.add(company)
        db.flush()
    return company


def _upsert_peer_link(db: Session, ticker: str, peer: str) -> None:
    ticker, peer = ticker.upper(), peer.upper()
    if ticker == peer:
        return
    exists = db.scalars(
        select(PeerLink).where(PeerLink.ticker == ticker, PeerLink.peer == peer)
    ).first()
    if exists is None:
        db.add(PeerLink(ticker=ticker, peer=peer))


def _upsert_earnings(
    db: Session,
    *,
    ticker: str,
    event_date: date,
    timing: str,
    eps_estimate: float | None,
    eps_actual: float | None,
    revenue_estimate: float | None,
    revenue_actual: float | None,
    fiscal_period: str | None,
) -> None:
    event = db.scalars(
        select(EarningsEvent).where(
            EarningsEvent.ticker == ticker, EarningsEvent.date == event_date
        )
    ).first()
    if event is None:
        event = EarningsEvent(ticker=ticker, date=event_date)
        db.add(event)
        # Session uses autoflush=False; flush now so a later upsert for the same
        # (ticker, date) within this batch finds it instead of inserting a dup.
        db.flush()
    if timing != "unknown":
        event.timing = timing
    elif not event.timing:
        event.timing = "unknown"
    # Only overwrite with non-null values so we never erase known actuals.
    if eps_estimate is not None:
        event.eps_estimate = eps_estimate
    if eps_actual is not None:
        event.eps_actual = eps_actual
    if revenue_estimate is not None:
        event.revenue_estimate = revenue_estimate
    if revenue_actual is not None:
        event.revenue_actual = revenue_actual
    if fiscal_period:
        event.fiscal_period = fiscal_period


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
