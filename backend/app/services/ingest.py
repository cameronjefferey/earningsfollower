from __future__ import annotations

import logging
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
    v = (str(value or "")).strip().lower()
    if v in {"bmo", "amc"}:
        return v
    return "unknown"


def refresh_all(db: Session, *, expand_peers: bool | None = None) -> dict[str, Any]:
    """Full data refresh: build the universe, then ingest each tracked ticker.

    Resilient by design: a failure on one ticker is logged and skipped so the
    rest of the refresh still completes (important on free-tier rate limits).
    """
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
        logger.info("Tracking %d tickers", len(tracked))

        # Earnings now come from FMP's per-symbol endpoint (full multi-year
        # history + upcoming estimates), set inside ingest_company. The bulk
        # calendar is intentionally not used: paid tiers cap its history at a
        # few months, so it can't backfill the reaction stats the app needs.
        for ticker in tracked:
            try:
                report = ingest_company(
                    db,
                    fmp,
                    ticker,
                    history_years=settings.history_years,
                    fmp_earnings=fmp.enabled,
                    fetch_earnings=not fmp.enabled,
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
    # every tracked ticker. Missing implied moves alone is a soft/expected gap.
    core_complete = not errors and not no_prices and not no_earnings
    log.status = "ok" if core_complete else "partial"
    detail_parts = [
        f"processed={processed}",
        f"tracked={len(tracked)}",
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
    return {
        "processed": processed,
        "tracked": len(tracked),
        "errors": errors,
        "no_prices": no_prices,
        "no_earnings": no_earnings,
        "no_implied": no_implied,
        "status": log.status,
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


def ingest_company(
    db: Session,
    fmp: FMPClient,
    ticker: str,
    *,
    history_years: int = 5,
    fmp_earnings: bool | None = None,
    fetch_earnings: bool = True,
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

    # yfinance earnings scraping is unreliable on cloud IPs, so it's only a
    # fallback when FMP earnings aren't available (e.g. no API key).
    got_yahoo_earnings = False
    if fetch_earnings and not got_fmp_earnings:
        got_yahoo_earnings = _ingest_earnings_yahoo(db, ticker)

    price_source = _ingest_prices(db, ticker, history_years, fmp)
    got_implied = _ingest_implied_move(db, ticker)

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
            timing="unknown",
            eps_estimate=row.get("eps_estimate"),
            eps_actual=row.get("eps_actual"),
            revenue_estimate=None,
            revenue_actual=None,
            fiscal_period=None,
        )
    return bool(rows)


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
