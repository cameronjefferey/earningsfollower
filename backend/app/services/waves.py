from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EarningsEvent
from app.services.peers import get_peers, shared_themes
from app.services.prices import load_price_series
from app.services.reactions import compute_reactions

# Window during which a peer's report can plausibly influence a target's
# pre-earnings drift (a target reports within ~1 quarter of the peer).
MAX_GAP_DAYS = 100
MIN_SAMPLE = 3


@dataclass
class LeadLagStats:
    trigger: str
    target: str
    sample_size: int
    avg_runup_pct: float | None
    win_rate: float | None
    avg_runup_when_trigger_up_pct: float | None
    avg_runup_when_trigger_down_pct: float | None
    score: float


@dataclass
class WaveSignal:
    trigger: str
    trigger_name: str | None
    trigger_report_date: str
    trigger_move_pct: float | None
    trigger_beat: bool | None
    target: str
    target_name: str | None
    target_report_date: str | None
    shared_themes: list[dict]
    direction: str  # "bullish" / "bearish" lean for the target
    expected_runup_pct: float | None
    stats: dict


def _report_dates(db: Session, ticker: str, *, past_only: bool) -> list[date]:
    stmt = select(EarningsEvent.date).where(EarningsEvent.ticker == ticker.upper())
    if past_only:
        stmt = stmt.where(EarningsEvent.date <= date.today())
    return sorted(db.scalars(stmt.order_by(EarningsEvent.date.asc())).all())


def lead_lag(
    db: Session,
    trigger: str,
    target: str,
    *,
    series_cache: dict[str, object] | None = None,
    reports_cache: dict[str, list[date]] | None = None,
    reactions_cache: dict[str, dict[date, float | None]] | None = None,
) -> LeadLagStats:
    """How the target drifts between a trigger peer's report and its own report.

    For each past trigger report, measure the target's price return from the
    trigger date up to the close just before the target's next report.
    """
    trigger, target = trigger.upper(), target.upper()

    def _series(ticker: str):
        if series_cache is not None:
            if ticker not in series_cache:
                series_cache[ticker] = load_price_series(db, ticker)
            return series_cache[ticker]
        return load_price_series(db, ticker)

    def _reports(ticker: str) -> list[date]:
        if reports_cache is not None:
            if ticker not in reports_cache:
                reports_cache[ticker] = _report_dates(db, ticker, past_only=True)
            return reports_cache[ticker]
        return _report_dates(db, ticker, past_only=True)

    def _trigger_moves(ticker: str) -> dict[date, float | None]:
        if reactions_cache is not None and ticker in reactions_cache:
            return reactions_cache[ticker]
        moves = {r.date: r.move_pct for r in compute_reactions(db, ticker, series=_series(ticker))}
        if reactions_cache is not None:
            reactions_cache[ticker] = moves
        return moves

    target_series = _series(target)
    target_reports = _reports(target)
    trigger_reports = _reports(trigger)
    trigger_moves = _trigger_moves(trigger)

    runups: list[float] = []
    runups_trigger_up: list[float] = []
    runups_trigger_down: list[float] = []

    for rp in trigger_reports:
        ra = _next_after(target_reports, rp, MAX_GAP_DAYS)
        if ra is None:
            continue
        start_idx = target_series.index_on_or_after(rp)
        end_idx = target_series.index_strictly_before(ra)
        if start_idx is None or end_idx is None or end_idx <= start_idx:
            continue
        start_close = target_series.close[start_idx]
        end_close = target_series.close[end_idx]
        if not start_close or not end_close:
            continue
        runup = end_close / start_close - 1.0
        runups.append(runup)

        tmove = trigger_moves.get(rp)
        if tmove is not None:
            if tmove > 0:
                runups_trigger_up.append(runup)
            elif tmove < 0:
                runups_trigger_down.append(runup)

    n = len(runups)
    avg = statistics.fmean(runups) if runups else None
    win_rate = (sum(1 for r in runups if r > 0) / n) if n else None
    avg_up = (
        statistics.fmean(runups_trigger_up) if runups_trigger_up else None
    )
    avg_down = (
        statistics.fmean(runups_trigger_down) if runups_trigger_down else None
    )

    # Confidence scales with sample size; score rewards a consistent, sizable run.
    confidence = (win_rate or 0) * min(n / 6.0, 1.0)
    score = abs(avg or 0) * confidence * math.log1p(n)

    return LeadLagStats(
        trigger=trigger,
        target=target,
        sample_size=n,
        avg_runup_pct=_round(avg),
        win_rate=_round(win_rate),
        avg_runup_when_trigger_up_pct=_round(avg_up),
        avg_runup_when_trigger_down_pct=_round(avg_down),
        score=round(score, 6),
    )


def peers_lead_lag(db: Session, target: str, *, limit: int = 12) -> list[dict]:
    """Rank a target's peers by how reliably the target rides their earnings."""
    target = target.upper()
    series_cache: dict[str, object] = {}
    reports_cache: dict[str, list[date]] = {}
    reactions_cache: dict[str, dict[date, float | None]] = {}
    out: list[LeadLagStats] = []
    for peer in get_peers(db, target):
        stats = lead_lag(
            db,
            peer,
            target,
            series_cache=series_cache,
            reports_cache=reports_cache,
            reactions_cache=reactions_cache,
        )
        if stats.sample_size >= MIN_SAMPLE and stats.avg_runup_pct is not None:
            out.append(stats)
    out.sort(key=lambda s: s.score, reverse=True)
    return [asdict(s) for s in out[:limit]]


def current_waves(
    db: Session,
    *,
    recent_days: int = 14,
    upcoming_days: int = 21,
    limit: int = 40,
) -> tuple[list[dict], bool]:
    """Live "ride the wave" opportunities.

    A peer reported recently AND a themed target reports soon -> surface the
    historical lead-lag so the user can decide whether to ride the wave.

    Stops once ``limit + 1`` qualifying signals are found so small first-page
    requests stay cheap. Returns ``(page, has_more)``.
    """
    today = date.today()
    recent_start = today - timedelta(days=recent_days)
    upcoming_end = today + timedelta(days=upcoming_days)
    probe = max(limit + 1, 1)

    recent = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.date >= recent_start, EarningsEvent.date <= today)
        .order_by(EarningsEvent.date.desc())
    ).all()
    upcoming = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.date > today, EarningsEvent.date <= upcoming_end)
        .order_by(EarningsEvent.date.asc())
    ).all()

    if not recent or not upcoming:
        return [], False

    upcoming_by_ticker: dict[str, EarningsEvent] = {}
    for ev in upcoming:
        upcoming_by_ticker.setdefault(ev.ticker, ev)

    series_cache: dict[str, object] = {}
    reports_cache: dict[str, list[date]] = {}
    reactions_cache: dict[str, dict[date, float | None]] = {}
    name_cache: dict[str, str | None] = {}

    signals: list[WaveSignal] = []
    seen: set[tuple[str, str]] = set()

    for trig_event in recent:
        if len(signals) >= probe:
            break
        trig = trig_event.ticker
        if trig not in reactions_cache:
            series = series_cache.get(trig) or load_price_series(db, trig)
            series_cache[trig] = series
            reactions_cache[trig] = {
                r.date: r.move_pct for r in compute_reactions(db, trig, series=series)
            }
        trig_move = reactions_cache[trig].get(trig_event.date)
        trig_beat = _beat(trig_event)

        for target in get_peers(db, trig):
            if len(signals) >= probe:
                break
            target_event = upcoming_by_ticker.get(target)
            if target_event is None:
                continue
            key = (trig, target)
            if key in seen:
                continue
            seen.add(key)

            stats = lead_lag(
                db,
                trig,
                target,
                series_cache=series_cache,
                reports_cache=reports_cache,
                reactions_cache=reactions_cache,
            )
            if stats.sample_size < MIN_SAMPLE or stats.avg_runup_pct is None:
                continue

            # Directional expectation conditioned on how the trigger just moved.
            if trig_move is not None and trig_move > 0:
                expected = stats.avg_runup_when_trigger_up_pct
            elif trig_move is not None and trig_move < 0:
                expected = stats.avg_runup_when_trigger_down_pct
            else:
                expected = stats.avg_runup_pct
            if expected is None:
                expected = stats.avg_runup_pct

            direction = "bullish" if (expected or 0) >= 0 else "bearish"

            if trig not in name_cache:
                name_cache[trig] = _name(db, trig)
            if target not in name_cache:
                name_cache[target] = _name(db, target)

            signals.append(
                WaveSignal(
                    trigger=trig,
                    trigger_name=name_cache[trig],
                    trigger_report_date=trig_event.date.isoformat(),
                    trigger_move_pct=_round(trig_move),
                    trigger_beat=trig_beat,
                    target=target,
                    target_name=name_cache[target],
                    target_report_date=target_event.date.isoformat(),
                    shared_themes=_shared(db, trig, target),
                    direction=direction,
                    expected_runup_pct=expected,
                    stats=asdict(stats),
                )
            )

    signals.sort(
        key=lambda s: (s.stats["score"], abs(s.expected_runup_pct or 0)),
        reverse=True,
    )
    has_more = len(signals) > limit
    return [asdict(s) for s in signals[:limit]], has_more


# --- peer-earnings sympathy ride (short, fixed hold) -------------------------
# Unlike `lead_lag` (which measures the runup all the way to the target's *own*
# print), this measures the target's return over a short, fixed window right
# after the peer reports — the "ride the pop for a couple days" edge. It's
# independent of the target's earnings calendar, so it can fire whenever a peer
# reports strongly, and it directly matches the short live hold.


@dataclass
class SympathyStats:
    trigger: str
    target: str
    hold_days: int          # trading-day window the edge is measured over
    sample_size: int
    avg_return_pct: float | None
    win_rate: float | None
    avg_when_trigger_up_pct: float | None
    avg_when_trigger_down_pct: float | None
    score: float


def sympathy_stats(
    db: Session, trigger: str, target: str, *, hold_days: int
) -> SympathyStats:
    """How the target moved over the `hold_days` trading days following each of
    the trigger peer's past reports, conditioned on the peer's own reaction."""
    trigger, target = trigger.upper(), target.upper()
    target_series = load_price_series(db, target)
    trigger_reports = _report_dates(db, trigger, past_only=True)
    trigger_moves = {r.date: r.move_pct for r in compute_reactions(db, trigger)}

    rets: list[float] = []
    rets_up: list[float] = []
    rets_down: list[float] = []

    for rp in trigger_reports:
        start_idx = target_series.index_on_or_after(rp)
        if start_idx is None:
            continue
        end_idx = start_idx + hold_days
        if end_idx >= len(target_series):
            continue
        start_close = target_series.close[start_idx]
        end_close = target_series.close[end_idx]
        if not start_close or not end_close:
            continue
        ret = end_close / start_close - 1.0
        rets.append(ret)

        tmove = trigger_moves.get(rp)
        if tmove is not None:
            if tmove > 0:
                rets_up.append(ret)
            elif tmove < 0:
                rets_down.append(ret)

    n = len(rets)
    avg = statistics.fmean(rets) if rets else None
    win_rate = (sum(1 for r in rets if r > 0) / n) if n else None
    avg_up = statistics.fmean(rets_up) if rets_up else None
    avg_down = statistics.fmean(rets_down) if rets_down else None

    confidence = (win_rate or 0) * min(n / 6.0, 1.0)
    score = abs(avg or 0) * confidence * math.log1p(n)

    return SympathyStats(
        trigger=trigger,
        target=target,
        hold_days=hold_days,
        sample_size=n,
        avg_return_pct=_round(avg),
        win_rate=_round(win_rate),
        avg_when_trigger_up_pct=_round(avg_up),
        avg_when_trigger_down_pct=_round(avg_down),
        score=round(score, 6),
    )


def _next_report_after_today(db: Session, ticker: str) -> date | None:
    """The target's next scheduled/known report strictly after today, if any."""
    today = date.today()
    for d in _report_dates(db, ticker, past_only=False):
        if d > today:
            return d
    return None


def current_sympathy_waves(
    db: Session,
    *,
    trigger_max_age_days: int = 2,
    min_trigger_move: float = 0.03,
    hold_days: int = 3,
    limit: int = 40,
) -> list[dict]:
    """Live peer-sympathy rides: a tracked peer reported a strong move in the
    last few days -> surface its themed peers as sympathy buys, with the
    short-window historical edge. Decoupled from the target's own earnings date.
    """
    today = date.today()
    recent_start = today - timedelta(days=trigger_max_age_days)
    recent = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.date >= recent_start, EarningsEvent.date <= today)
        .order_by(EarningsEvent.date.desc())
    ).all()
    if not recent:
        return []

    trigger_move_cache: dict[str, dict[date, float | None]] = {}
    signals: list[WaveSignal] = []
    seen: set[tuple[str, str]] = set()

    for trig_event in recent:
        trig = trig_event.ticker
        if trig not in trigger_move_cache:
            trigger_move_cache[trig] = {
                r.date: r.move_pct for r in compute_reactions(db, trig)
            }
        trig_move = trigger_move_cache[trig].get(trig_event.date)
        # Require a real catalyst: the peer must have moved enough on its print.
        if trig_move is None or abs(trig_move) < min_trigger_move:
            continue
        trig_beat = _beat(trig_event)

        for target in get_peers(db, trig):
            key = (trig, target)
            if key in seen:
                continue
            seen.add(key)

            stats = sympathy_stats(db, trig, target, hold_days=hold_days)
            if stats.sample_size < MIN_SAMPLE or stats.avg_return_pct is None:
                continue

            # Directional expectation conditioned on how the peer just moved.
            if trig_move > 0:
                expected = stats.avg_when_trigger_up_pct
            else:
                expected = stats.avg_when_trigger_down_pct
            if expected is None:
                expected = stats.avg_return_pct

            direction = "bullish" if (expected or 0) >= 0 else "bearish"
            target_report = _next_report_after_today(db, target)

            # Shape the signal to match the WaveSignal the trader/executor
            # already consume (stats keys: win_rate, sample_size, score, ...).
            stat_dict = {
                "win_rate": stats.win_rate,
                "sample_size": stats.sample_size,
                "score": stats.score,
                "avg_return_pct": stats.avg_return_pct,
                "hold_days": stats.hold_days,
            }
            signals.append(
                WaveSignal(
                    trigger=trig,
                    trigger_name=_name(db, trig),
                    trigger_report_date=trig_event.date.isoformat(),
                    trigger_move_pct=_round(trig_move),
                    trigger_beat=trig_beat,
                    target=target,
                    target_name=_name(db, target),
                    target_report_date=(
                        target_report.isoformat() if target_report else None
                    ),
                    shared_themes=_shared(db, trig, target),
                    direction=direction,
                    expected_runup_pct=expected,
                    stats=stat_dict,
                )
            )

    signals.sort(
        key=lambda s: (s.stats["score"], abs(s.expected_runup_pct or 0)),
        reverse=True,
    )
    return [asdict(s) for s in signals[:limit]]


# --- helpers -----------------------------------------------------------------


def _next_after(dates: list[date], after: date, max_gap_days: int) -> date | None:
    for d in dates:
        if d > after:
            return d if (d - after).days <= max_gap_days else None
    return None


def _beat(ev: EarningsEvent) -> bool | None:
    if ev.eps_actual is None or ev.eps_estimate in (None, 0):
        return None
    return ev.eps_actual >= ev.eps_estimate


def _name(db: Session, ticker: str) -> str | None:
    from app.db.models import Company

    company = db.get(Company, ticker)
    return company.name if company else None


def _shared(db: Session, a: str, b: str) -> list[dict]:
    a_themes = {t["key"]: t for t in shared_themes(db, a)}
    b_keys = {t["key"] for t in shared_themes(db, b)}
    return [v for k, v in a_themes.items() if k in b_keys]


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)
