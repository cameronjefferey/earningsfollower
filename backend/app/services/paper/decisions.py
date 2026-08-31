"""Feature/label store for the paper trader (Phase 1 of the learning loop).

Every scan the executor runs makes a series of per-name decisions: it either
OPENS a trade or SKIPS the setup for a reason. This module journals each of those
decisions to the ``trade_decisions`` table as a flat row of typed signal features,
so we can later learn which signals actually predict winners - including the
counterfactuals (the skips), which a fills-only journal can never tell us.

Three responsibilities:
  1. ``regime_snapshot`` - capture the code version + tunable knobs in force, so a
     P&L shift can be attributed to signal edge vs. a config change.
  2. ``*_features`` builders - turn each strategy's live signal object (playbook /
     wave / drift / reddit) into a flat dict of typed columns, identically for an
     opened trade and a skipped setup.
  3. ``record_decision`` / ``sync_labels`` - write a decision row, and later fill
     in the realized labels (at-exit P&L + multi-horizon underlying moves) from
     the linked ``PaperTrade`` and price bars.

Everything here is best-effort: a failure to journal a decision must NEVER break
the trader, so the public entry points swallow and log their own exceptions.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PaperTrade, PriceBar, TradeDecision

logger = logging.getLogger(__name__)

# Bump when the signal-generation logic changes in a way that makes older rows
# not directly comparable, so analysis can segment by regime.
#   1 -> initial journal.
#   2 -> global underlying take-profit turned on across the directional books
#        (exit discipline changed materially, so pre/post capture isn't comparable).
#   3 -> size/liquidity features (market cap, ADV, dollar volume) journaled and
#        a fitted logistic entry model scores setups in front of the gates.
#   4 -> reaction / analyst / realized-vol / timing context added to the model.
PLAYBOOK_VERSION = "4"

# The tunable knobs that shape which trades open and how they're sized. Snapshotted
# with every decision so results can be attributed to a specific config regime.
_REGIME_KEYS = (
    "paper_entry_window_days",
    "paper_sell_strike_em_frac",
    "paper_min_credit",
    "paper_min_credit_width_ratio",
    "paper_max_debit_width_frac",
    "paper_min_reward_risk",
    "paper_min_expected_value",
    "paper_max_leg_spread_frac",
    "paper_max_cross_slippage_frac",
    "paper_risk_high",
    "paper_risk_medium",
    "paper_risk_low",
    "paper_stops_enabled",
    "paper_wave_min_winrate",
    "paper_wave_min_samples",
    "paper_drift_min_score",
    "reddit_min_conviction",
    "reddit_max_pump_risk",
    "reddit_min_velocity",
    "paper_take_profit_enabled",
    "paper_take_profit_pct",
    "paper_exit_learning_enabled",
    "paper_entry_model_enabled",
    "paper_entry_model_min_prob",
    "paper_reversal_enabled",
    "paper_reversal_top_n",
    "paper_reversal_hold_days",
)


def regime_snapshot(settings) -> dict:
    """A JSON-able snapshot of the version + knobs in force for this decision."""
    snap = {"playbook_version": PLAYBOOK_VERSION}
    for key in _REGIME_KEYS:
        if hasattr(settings, key):
            snap[key] = getattr(settings, key)
    return snap


# --- feature builders --------------------------------------------------------
#
# Each returns a flat dict whose keys are TradeDecision column names. Callers pass
# the same builder output for both the opened and the skipped decision, so a skip
# and a fill on the same signal are directly comparable.


def _num(value):
    """Coerce to float when it looks numeric, else None (keeps JSON tidy)."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def earnings_features(
    pb: dict,
    im: dict | None = None,
    spec=None,
    contracts: int | None = None,
    risk_frac: float | None = None,
    equity: float | None = None,
) -> dict:
    """Features for the earnings sell-vol book, from the playbook + implied move."""
    basis = (pb or {}).get("conviction_basis") or {}
    im = im or {}
    win_prob = basis.get("seller_edge_at_strike") or basis.get("seller_edge")
    feats: dict = {
        "direction": pb.get("direction"),
        "vol_stance": pb.get("vol_stance"),
        "structure": pb.get("structure"),
        "conviction": pb.get("conviction"),
        "conviction_reason": basis.get("tier_reason"),
        "win_prob": _num(win_prob),
        "expected_move_pct": _num(im.get("expected_move_pct")),
        "spot": _num(im.get("underlying_price") or pb.get("spot")),
        "dir_score": _num(basis.get("dir_score")),
        "seller_edge": _num(basis.get("seller_edge")),
        "seller_edge_at_strike": _num(basis.get("seller_edge_at_strike")),
        "exceed_rate": _num(basis.get("exceed_rate")),
        "edge_sample": basis.get("edge_sample"),
        "richness": _num(basis.get("richness")),
        "data_suspect": basis.get("data_suspect"),
        "risk_frac": _num(risk_frac),
        "equity_at_decision": _num(equity),
    }
    _apply_spec(feats, spec, contracts, is_credit=True)
    return feats


def wave_features(
    sig: dict,
    conviction: str | None = None,
    spec=None,
    contracts: int | None = None,
    risk_frac: float | None = None,
    equity: float | None = None,
) -> dict:
    stats = (sig or {}).get("stats") or {}
    feats: dict = {
        "direction": sig.get("direction"),
        "vol_stance": "buy",
        "conviction": conviction,
        "trigger": sig.get("trigger"),
        "trigger_move_pct": _num(sig.get("trigger_move_pct")),
        "expected_runup_pct": _num(sig.get("expected_runup_pct")),
        "hist_win_rate": _num(stats.get("win_rate")),
        "hist_samples": stats.get("sample_size"),
        "win_prob": _num(stats.get("win_rate")),
        "risk_frac": _num(risk_frac),
        "equity_at_decision": _num(equity),
    }
    _apply_spec(feats, spec, contracts, is_credit=False)
    return feats


def drift_features(
    setup: dict,
    conviction: str | None = None,
    spec=None,
    contracts: int | None = None,
    risk_frac: float | None = None,
    equity: float | None = None,
) -> dict:
    history = (setup or {}).get("history") or {}
    long = setup.get("direction") == "long"
    feats: dict = {
        "direction": "bullish" if long else "bearish",
        "vol_stance": "buy",
        "conviction": conviction,
        "surprise_pct": _num(setup.get("surprise_pct")),
        "move_pct": _num(setup.get("move_pct")),
        "drift_edge_5d": _num(history.get("avg_drift_5d_pct")),
        "drift_score": _num(setup.get("score")),
        "hist_win_rate": _num(history.get("win_rate_5d")),
        "hist_samples": history.get("sample_size"),
        "win_prob": _num(history.get("win_rate_5d")),
        "risk_frac": _num(risk_frac),
        "equity_at_decision": _num(equity),
    }
    _apply_spec(feats, spec, contracts, is_credit=False)
    return feats


def reddit_features(
    sig: dict,
    conviction: str | None = None,
    win_prob: float | None = None,
    spec=None,
    contracts: int | None = None,
    risk_frac: float | None = None,
    equity: float | None = None,
) -> dict:
    bullish = sig.get("direction") == "bullish"
    feats: dict = {
        "direction": sig.get("direction"),
        "vol_stance": "buy",
        "conviction": conviction or sig.get("conviction"),
        "sentiment": _num(sig.get("sentiment")),
        "mention_count": sig.get("mention_count"),
        "mention_velocity": _num(sig.get("mention_velocity")),
        "pump_risk": sig.get("pump_risk"),
        "scored_by": sig.get("scored_by"),
        "win_prob": _num(win_prob),
        "risk_frac": _num(risk_frac),
        "equity_at_decision": _num(equity),
    }
    if bullish is not None and feats.get("structure") is None:
        feats["structure"] = "Bull call spread" if bullish else "Bear put spread"
    _apply_spec(feats, spec, contracts, is_credit=False)
    return feats


def _apply_spec(feats: dict, spec, contracts: int | None, is_credit: bool) -> None:
    """Fold a built TradeSpec/WaveSpec/DriftSpec/RedditSpec into the feature dict.

    All specs expose ``width`` and a spot; the sell-vol spec carries ``net_credit``
    and ``max_risk_per_contract`` while the debit specs carry ``net_debit``."""
    if spec is None:
        return
    feats["width"] = _num(getattr(spec, "width", None))
    if contracts is not None:
        feats["contracts"] = contracts
    spot = getattr(spec, "spot", None)
    if spot is not None and feats.get("spot") is None:
        feats["spot"] = _num(spot)
    if is_credit:
        feats["modeled_price"] = _num(getattr(spec, "net_credit", None))
        per_ct = getattr(spec, "max_risk_per_contract", None)
        if per_ct is not None and contracts is not None:
            feats["max_risk"] = round(per_ct * contracts, 2)
    else:
        debit = getattr(spec, "net_debit", None)
        feats["modeled_price"] = _num(debit)
        if debit is not None and contracts is not None:
            feats["max_risk"] = round(debit * 100 * contracts, 2)


# --- size / liquidity / research context -------------------------------------

_ADV_LOOKBACK = 20
_TREND_LOOKBACK = 60
_BAR_FETCH = _TREND_LOOKBACK + 2

_CONTEXT_KEYS = (
    "market_cap", "avg_volume", "dollar_volume", "rel_volume",
    "realized_vol_20d", "trend_60d", "up_rate", "last_move_pct",
    "beat_rate", "continuation_rate", "analyst_upside", "analyst_bullish_pct",
    "days_to_event", "earnings_timing", "seller_edge", "richness",
    "expected_move_pct", "exceed_rate", "edge_sample",
)


def liquidity_snapshot(
    db: Session,
    ticker: str,
    *,
    spot: float | None = None,
    as_of: date | None = None,
) -> dict:
    """Market cap, ADV, realized vol, and 60d trend as of ``as_of`` (or now)."""
    from app.db.models import Company, PriceBar

    ticker = (ticker or "").upper()
    out: dict = {
        "market_cap": None, "avg_volume": None, "dollar_volume": None,
        "rel_volume": None, "realized_vol_20d": None, "trend_60d": None,
    }
    if not ticker:
        return out
    try:
        company = db.get(Company, ticker)
        if company and company.market_cap:
            out["market_cap"] = _num(company.market_cap)
        q = (
            select(PriceBar)
            .where(PriceBar.ticker == ticker)
            .order_by(PriceBar.date.desc())
        )
        if as_of is not None:
            q = q.where(PriceBar.date <= as_of)
        bars = db.scalars(q.limit(_BAR_FETCH)).all()
        vols = [b.volume for b in bars if b.volume and b.volume > 0]
        if vols:
            n = min(len(vols), _ADV_LOOKBACK)
            out["avg_volume"] = round(sum(vols[:n]) / n, 2)
            if bars[0].volume and bars[0].volume > 0 and out["avg_volume"]:
                out["rel_volume"] = round(float(bars[0].volume) / out["avg_volume"], 4)
        close = _num(spot)
        if close is None:
            for b in bars:
                if b.close and b.close > 0:
                    close = float(b.close)
                    break
        if out["avg_volume"] is not None and close:
            out["dollar_volume"] = round(out["avg_volume"] * close, 2)
        closes = [float(b.close) for b in bars if b.close and b.close > 0]
        if len(closes) >= 12:
            look = min(_TREND_LOOKBACK, len(closes) - 1)
            past = closes[look]
            if past:
                out["trend_60d"] = round(closes[0] / past - 1.0, 4)
        if len(closes) >= 11:
            rets = []
            for i in range(min(_ADV_LOOKBACK, len(closes) - 1)):
                if closes[i + 1]:
                    rets.append(closes[i] / closes[i + 1] - 1.0)
            if len(rets) >= 8:
                mean = sum(rets) / len(rets)
                var = sum((r - mean) ** 2 for r in rets) / len(rets)
                out["realized_vol_20d"] = round(var ** 0.5, 5)
    except Exception as e:  # noqa: BLE001 - never break the trader for a snapshot
        logger.warning("liquidity snapshot failed for %s: %s", ticker, e)
    return out


def _research_snapshot(
    db: Session,
    ticker: str,
    *,
    spot: float | None = None,
    as_of: date | None = None,
    earnings_date: date | None = None,
) -> dict:
    """Reaction history, analyst, implied, and calendar timing. Best-effort."""
    from app.db.models import EarningsEvent

    out: dict = {
        "up_rate": None, "last_move_pct": None, "beat_rate": None,
        "continuation_rate": None, "analyst_upside": None,
        "analyst_bullish_pct": None, "days_to_event": None,
        "earnings_timing": None, "seller_edge": None, "richness": None,
        "expected_move_pct": None, "exceed_rate": None, "edge_sample": None,
    }
    ticker = (ticker or "").upper()
    if not ticker:
        return out
    cutoff = earnings_date or as_of or date.today()
    try:
        from app.services.reactions import compute_reactions, summarize

        rx = compute_reactions(db, ticker)
        prior = []
        for r in rx:
            try:
                d = date.fromisoformat(str(r.date)[:10])
            except ValueError:
                continue
            if d < cutoff:
                prior.append(r)
        summary = summarize(prior)
        out["up_rate"] = _num(summary.up_rate)
        out["last_move_pct"] = _num(summary.last_move_pct)
        out["beat_rate"] = _num(summary.beat_rate)
        out["continuation_rate"] = _num(summary.continuation_rate)
        if summary.sample_size:
            out["edge_sample"] = int(summary.sample_size)
        avg_abs = summary.avg_abs_move_pct
        from app.services.implied import implied_payload

        im = implied_payload(db, ticker, avg_abs, [
            abs(r.move_pct) for r in prior if r.move_pct is not None
        ])
        if im:
            out["expected_move_pct"] = _num(im.get("expected_move_pct"))
            out["richness"] = _num(im.get("richness"))
            out["exceed_rate"] = _num(im.get("exceed_rate"))
            if im.get("exceed_rate") is not None:
                out["seller_edge"] = round(1.0 - float(im["exceed_rate"]), 4)
            if im.get("edge_sample") is not None:
                out["edge_sample"] = im.get("edge_sample")
            if spot is None:
                spot = _num(im.get("underlying_price"))
        from app.services.analyst import analyst_payload

        an = analyst_payload(db, ticker, spot)
        if an:
            out["analyst_upside"] = _num(an.get("upside_pct"))
            out["analyst_bullish_pct"] = _num(an.get("bullish_pct"))
        ev = None
        if earnings_date is not None:
            ev = db.scalars(
                select(EarningsEvent).where(
                    EarningsEvent.ticker == ticker,
                    EarningsEvent.date == earnings_date,
                )
            ).first()
        if ev is None:
            ev = db.scalars(
                select(EarningsEvent)
                .where(EarningsEvent.ticker == ticker, EarningsEvent.date >= cutoff)
                .order_by(EarningsEvent.date.asc())
            ).first()
        if ev is not None:
            out["earnings_timing"] = ev.timing or "unknown"
            if as_of is not None:
                out["days_to_event"] = (ev.date - as_of).days
            elif earnings_date is not None:
                out["days_to_event"] = (ev.date - date.today()).days
    except Exception as e:  # noqa: BLE001
        logger.warning("research snapshot failed for %s: %s", ticker, e)
    return out


def attach_context_features(
    db: Session,
    ticker: str,
    feats: dict | None,
    *,
    as_of: date | None = None,
    earnings_date: date | None = None,
) -> dict:
    """Fill size, vol, reaction, analyst, and calendar fields when missing."""
    feats = dict(feats or {})
    need_mkt = any(feats.get(k) is None for k in (
        "market_cap", "avg_volume", "dollar_volume", "rel_volume",
        "realized_vol_20d", "trend_60d",
    ))
    if need_mkt:
        liq = liquidity_snapshot(db, ticker, spot=feats.get("spot"), as_of=as_of)
        for key, val in liq.items():
            if feats.get(key) is None and val is not None:
                feats[key] = val
    need_research = any(feats.get(k) is None for k in (
        "up_rate", "last_move_pct", "beat_rate", "continuation_rate",
        "analyst_upside", "analyst_bullish_pct", "days_to_event",
        "earnings_timing",
    ))
    if need_research:
        research = _research_snapshot(
            db, ticker, spot=feats.get("spot"), as_of=as_of,
            earnings_date=earnings_date or feats.get("earnings_date"),
        )
        for key, val in research.items():
            if feats.get(key) is None and val is not None:
                feats[key] = val
    return feats


# --- recording ---------------------------------------------------------------

# The subset of feature keys that map to typed TradeDecision columns. Anything
# else in a features dict still lands in features_json for the long tail.
_COLUMN_KEYS = {
    "direction", "vol_stance", "structure", "conviction", "conviction_reason",
    "win_prob", "expected_move_pct", "spot", "modeled_price", "width",
    "contracts", "max_risk", "risk_frac", "equity_at_decision",
    "dir_score", "seller_edge", "seller_edge_at_strike", "exceed_rate",
    "edge_sample", "richness", "data_suspect", "trigger", "trigger_move_pct",
    "expected_runup_pct", "surprise_pct", "move_pct", "drift_edge_5d",
    "drift_score", "hist_win_rate", "hist_samples", "sentiment",
    "mention_count", "mention_velocity", "pump_risk", "scored_by",
    "market_cap", "avg_volume", "dollar_volume", "rel_volume",
    "realized_vol_20d", "trend_60d", "up_rate", "last_move_pct",
    "beat_rate", "continuation_rate", "analyst_upside", "analyst_bullish_pct",
    "days_to_event", "earnings_timing", "model_win_prob",
}


def record_decision(
    db: Session,
    *,
    strategy: str,
    ticker: str,
    decision: str,
    earnings_date: date | None = None,
    skip_reason: str | None = None,
    signal_id: str | None = None,
    features: dict | None = None,
    regime: dict | None = None,
    decision_date: date | None = None,
) -> TradeDecision | None:
    """Journal one decision (``opened`` or ``skipped``) with its signal features.

    Best-effort: never raises into the trader. Returns the row (flushed, not
    committed - the caller's normal commit/rollback governs persistence, so a
    dry-run's rollback discards it just like a preview PaperTrade). The write is
    wrapped in a SAVEPOINT so a bad row rolls back only itself, never the
    surrounding scan's other (uncommitted) trades and decisions."""
    try:
        feats = attach_context_features(
            db, ticker, dict(features or {}),
            as_of=decision_date or date.today(),
            earnings_date=earnings_date,
        )
        row = TradeDecision(
            decision_date=decision_date or date.today(),
            strategy=strategy,
            ticker=ticker,
            earnings_date=earnings_date,
            decision=decision,
            skip_reason=(str(skip_reason)[:256] if skip_reason else None),
            signal_id=signal_id,
            playbook_version=PLAYBOOK_VERSION,
            regime_json=json.dumps(regime) if regime else None,
            features_json=json.dumps(feats, default=str) if feats else None,
            label_status="pending",
        )
        for key in _COLUMN_KEYS:
            if key in feats and feats[key] is not None:
                setattr(row, key, feats[key])
        with db.begin_nested():
            db.add(row)
        return row
    except Exception as e:  # noqa: BLE001 - journaling must never break the run
        logger.warning("failed to record %s decision for %s: %s", decision, ticker, e)
        return None


# --- backfill from existing PaperTrades --------------------------------------

_EQUITY_STRUCTURES = ("Long shares", "Short shares")


def features_from_paper_trade(t: PaperTrade) -> tuple[str, dict]:
    """Reconstruct a decision's features from an existing PaperTrade + its thesis
    JSON, for backfilling history. Returns ``(strategy_label, features)`` - the
    label separates the equity A/B books ("earnings_equity" / "reddit_equity")
    from their options siblings, matching what the live scans now record."""
    try:
        thesis = json.loads(t.thesis or "{}") or {}
    except (json.JSONDecodeError, TypeError):
        thesis = {}
    strat = t.strategy or "earnings"
    is_equity = (t.structure or "") in _EQUITY_STRUCTURES

    feats: dict = {
        "direction": t.direction,
        "vol_stance": t.vol_stance,
        "structure": t.structure,
        "conviction": t.conviction,
        "expected_move_pct": _num(t.expected_move_pct),
        "spot": _num(t.spot_entry),
        "width": _num(t.width),
        "contracts": t.contracts,
        "modeled_price": _num(t.modeled_credit),
        "max_risk": _num(t.max_risk),
        "equity_at_decision": _num(t.equity_at_entry),
    }

    if strat == "earnings":
        basis = thesis.get("conviction_basis") or {}
        feats.update({
            "conviction_reason": basis.get("tier_reason"),
            "dir_score": _num(basis.get("dir_score")),
            "seller_edge": _num(basis.get("seller_edge")),
            "seller_edge_at_strike": _num(basis.get("seller_edge_at_strike")),
            "exceed_rate": _num(basis.get("exceed_rate")),
            "edge_sample": basis.get("edge_sample"),
            "richness": _num(basis.get("richness")),
            "data_suspect": basis.get("data_suspect"),
            "win_prob": _num(
                basis.get("seller_edge_at_strike") or basis.get("seller_edge")
            ),
        })
        label = "earnings_equity" if is_equity else "earnings"
    elif strat == "waves":
        feats.update({
            "trigger": thesis.get("trigger"),
            "trigger_move_pct": _num(thesis.get("trigger_move_pct")),
            "expected_runup_pct": _num(thesis.get("expected_runup_pct")),
            "hist_win_rate": _num(thesis.get("win_rate")),
            "hist_samples": thesis.get("samples"),
            "win_prob": _num(thesis.get("win_rate")),
        })
        label = "waves"
    elif strat == "drift":
        feats.update({
            "surprise_pct": _num(thesis.get("surprise_pct")),
            "move_pct": _num(thesis.get("move_pct")),
            "drift_edge_5d": _num(thesis.get("edge_5d")),
            "hist_win_rate": _num(thesis.get("win_rate")),
            "hist_samples": thesis.get("samples"),
            "win_prob": _num(thesis.get("win_rate")),
        })
        label = "drift"
    elif strat == "reddit":
        feats.update({
            "sentiment": _num(thesis.get("sentiment")),
            "mention_count": thesis.get("mention_count"),
            "mention_velocity": _num(thesis.get("mention_velocity")),
            "pump_risk": thesis.get("pump_risk"),
            "scored_by": thesis.get("scored_by"),
        })
        label = "reddit_equity" if is_equity else "reddit"
    elif strat == "reversal":
        feats.update({
            "ret_5": _num(thesis.get("ret_5")),
            "hold_days": thesis.get("hold_days"),
            "lookback_days": thesis.get("lookback_days"),
            "dollar_vol": _num(thesis.get("dollar_vol")),
        })
        label = "reversal"
    else:
        label = strat

    return label, feats


# Trade status -> which decision it represents. Anything that reached the book
# (submitted or filled) is an "opened" decision; a canceled order never became a
# position, so it's the counterfactual "skipped".
_BACKFILL_OPENED_STATES = {"pending", "open", "closing", "closed"}


def backfill_from_paper_trades(db: Session) -> int:
    """Create a decision row for every PaperTrade that doesn't already have one,
    reconstructing features from its thesis JSON. Idempotent (skips trades whose
    signal_id is already journaled). Does not commit - the caller governs that."""
    existing = set(
        db.scalars(
            select(TradeDecision.signal_id).where(TradeDecision.signal_id.is_not(None))
        ).all()
    )
    created = 0
    for t in db.scalars(select(PaperTrade).order_by(PaperTrade.id.asc())).all():
        if t.signal_id in existing:
            continue
        label, feats = features_from_paper_trade(t)
        if t.status in _BACKFILL_OPENED_STATES:
            decision, reason = "opened", None
        else:  # canceled / rejected - a real setup we didn't end up holding
            decision, reason = "skipped", (t.note or "canceled")
        dd = t.created_at or t.opened_at
        row = record_decision(
            db,
            strategy=label,
            ticker=t.ticker,
            decision=decision,
            earnings_date=t.earnings_date,
            skip_reason=reason,
            signal_id=t.signal_id,
            features=feats,
            decision_date=dd.date() if dd else None,
        )
        if row is not None:
            created += 1
            existing.add(t.signal_id)
    return created


# --- labels ------------------------------------------------------------------


def _close_n_bars_after(db: Session, ticker: str, ref: date, n: int) -> float | None:
    """Close of the n-th price bar strictly after ``ref`` (≈ n trading days),
    or None if that many bars haven't printed yet."""
    bars = db.scalars(
        select(PriceBar)
        .where(PriceBar.ticker == ticker, PriceBar.date > ref)
        .order_by(PriceBar.date.asc())
    ).all()
    if len(bars) < n:
        return None
    bar = bars[n - 1]
    return bar.close


# A skipped decision has no trade to close, so its underlying-move labels can only
# resolve once bars exist. After this many days we stop retrying (bars would exist
# by now, or the ticker isn't tracked) and finalize the row so we don't rescan it.
_SKIP_LABEL_GIVEUP_DAYS = 15


def _fill_horizon_moves(
    db: Session, row: TradeDecision, ticker: str, entry_px: float | None, ref: date | None
) -> bool:
    """Write the +1d/+5d underlying move (signed and direction-adjusted) from an
    entry anchor, once the bars exist. Returns True if anything was written."""
    if not entry_px or not ref:
        return False
    changed = False
    long = row.direction == "bullish"
    for n, mcol, fcol in ((1, "move_1d", "fav_move_1d"), (5, "move_5d", "fav_move_5d")):
        if getattr(row, mcol) is not None:
            continue
        close = _close_n_bars_after(db, ticker, ref, n)
        if close:
            move = round(close / entry_px - 1, 4)
            setattr(row, mcol, move)
            if row.direction in ("bullish", "bearish"):
                setattr(row, fcol, round(move if long else -move, 4))
            changed = True
    return changed


def sync_labels(db: Session) -> int:
    """Fill in realized labels for decisions whose outcome has resolved.

    For ``opened`` decisions: copy the at-exit outcome/P&L from the linked
    PaperTrade (marking the row ``final`` once the trade closes) and compute the
    underlying's +1d/+5d move from the entry anchor.

    For ``skipped`` decisions (the counterfactuals): there's no trade, so only the
    underlying move from the decision date is computed - this is what lets us ask
    "did the gate reject winners?". These finalize once the +5d bar exists (or are
    given up on after a couple weeks so they aren't rescanned forever).

    Idempotent: only touches rows not yet ``final`` and only writes horizons once
    their bars exist, so it's safe to run every cycle."""
    updated = 0
    today = date.today()
    rows = db.scalars(
        select(TradeDecision).where(TradeDecision.label_status != "final")
    ).all()
    for row in rows:
        changed = False

        if row.decision == "opened" and row.signal_id:
            trade = db.scalars(
                select(PaperTrade).where(PaperTrade.signal_id == row.signal_id)
            ).first()
            if trade is None:
                continue
            # At-exit labels (only meaningful once the trade actually closed).
            if trade.status == "closed":
                row.outcome = trade.outcome
                row.realized_pnl = trade.realized_pnl
                row.realized_move_pct = trade.realized_move_pct
                row.breached_short = trade.breached_short
                row.label_status = "final"
                changed = True
            entry_px = trade.spot_entry or row.spot
            ref = (trade.opened_at.date() if trade.opened_at else None) or row.earnings_date
            if _fill_horizon_moves(db, row, trade.ticker, entry_px, ref):
                changed = True
        else:
            # Skipped counterfactual: underlying move from the decision date.
            if _fill_horizon_moves(db, row, row.ticker, row.spot, row.decision_date):
                changed = True
            # Finalize once the full horizon resolved, or give up after a while so
            # unpriceable/untracked skips don't get rescanned every cycle.
            aged_out = (today - row.decision_date).days >= _SKIP_LABEL_GIVEUP_DAYS
            if row.move_5d is not None or aged_out:
                row.label_status = "final"
                changed = True

        if changed:
            row.labels_updated_at = datetime.utcnow()
            updated += 1
    return updated
