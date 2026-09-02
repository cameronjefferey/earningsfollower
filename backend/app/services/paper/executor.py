"""The paper earnings trader.

Daily flow:
  1. reconcile  - update pending/closing trades from Alpaca order status
  2. expire     - journal-settle options past expiration at intrinsic (quotes
                  disappear after expiry, so the normal close path can't run)
  3. manage     - close open positions whose earnings print has passed (capture
                  the post-earnings IV crush the sell-premium thesis relies on)
  4. scan       - find tickers reporting within the entry window, run the
                  playbook, and open premium-selling trades sized to ~risk budget

Everything is journaled to the `paper_trades` table with a unique signal id.
Set dry_run=True to preview without submitting any orders.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.alpaca import AlpacaClient, AlpacaError
from app.config import get_settings
from app.db.models import Company, EarningsEvent, PaperTrade, PriceBar
from app.services.dashboard import company_detail
from app.services.notify import send_telegram, telegram_configured
from app.services.paper.calibration import adjust_win_prob, compute_calibration
from app.services.paper.contracts import TradeSpec, build_trade_spec
from app.services.paper.exit_learning import (
    compute_learned_take_profit,
    effective_take_profit,
)
from app.services.paper.decisions import (
    attach_context_features,
    backfill_from_paper_trades,
    drift_features,
    earnings_features,
    record_decision,
    reddit_features,
    regime_snapshot,
    sync_labels,
    wave_features,
)
from app.services.paper.entry_model import fit_entry_model, resolve_entry_probability
from app.services.paper.economics import evaluate_entry, fill_within_plan
from app.services.paper.risk import DEBIT_STRATEGIES, defined_risk_max_loss
from app.services.paper.drift_trader import DriftSpec, build_drift_spec, drift_conviction
from app.services.paper.reddit_trader import (
    RedditSpec,
    build_reddit_spec,
    reddit_conviction,
)
from app.services.paper.waves_trader import WaveSpec, build_wave_spec, wave_conviction
from app.services.paper.reversal import (
    STRATEGY as REVERSAL_STRATEGY,
    rank_live,
    reversal_exit_reason,
    tickers_in_earn_buffer,
    write_watch,
)
from app.services.reddit_sentiment import current_reddit_signals, latest_reddit_signal
from app.services.waves import current_sympathy_waves

logger = logging.getLogger(__name__)

SELLING_STRUCTURES = {
    "Bear call (call credit) spread",
    "Bull put (put credit) spread",
    "Iron condor",
}

OPEN_STATES = ("pending", "open", "closing")

# Note sentinel for a fill that breached the fair-trade plan (filled worse than
# the limit we sent). Flagged trades are flattened on the next manage-exits pass
# via _exit_reason, which checks this prefix before any strategy-specific logic.
_BAD_FILL_PREFIX = "bad fill:"

# Equity twin (Reddit): a plain long/short stock position placed alongside the
# options spread so we can compare which instrument captures the momentum better.
EQUITY_LONG = "Long shares"
EQUITY_SHORT = "Short shares"
EQUITY_STRUCTURES = (EQUITY_LONG, EQUITY_SHORT)


def _is_equity(t: PaperTrade) -> bool:
    return (t.structure or "") in EQUITY_STRUCTURES


def run(db: Session, dry_run: bool = False) -> dict:
    settings = get_settings()
    client = AlpacaClient()
    if not client.enabled:
        logger.warning("Alpaca credentials not set; paper trader is idle.")
        return {"status": "disabled", "reason": "no Alpaca credentials"}

    summary: dict = {
        "status": "ok",
        "dry_run": dry_run,
        "reconciled": 0,
        "closed": 0,
        "opened": 0,
        "skipped": [],
        "errors": [],
    }
    # Snapshot / notify flag live outside the try so an Alpaca blow-up mid-scan
    # still fires Telegram for closes that already happened this cycle.
    pre_status: dict[str, str] = {}
    notify_on = False
    try:
        equity = client.equity()
        summary["equity"] = equity

        # Only place orders when the market is open - options can't fill
        # overnight or pre/post-open, which is what left whole batches expiring.
        # dry-runs ignore this (they never submit). Reconcile always runs so
        # fills from the prior session still get picked up.
        market_open = True
        if settings.paper_market_hours_only and not dry_run:
            market_open = client.is_market_open()
        summary["market_open"] = market_open

        # Snapshot the book BEFORE reconcile/scan so the Telegram alert catches
        # fills the reconcile step flips from "pending"->"open" and positions it
        # closes this cycle. Snapshotting *after* reconcile (the old behavior)
        # hid every fill that landed between runs -- the common case for resting
        # limit orders -- so almost nothing ever alerted. Live runs only;
        # dry-runs and an unconfigured bot stay silent.
        notify_on = (
            settings.telegram_notify_trades and not dry_run and telegram_configured()
        )
        if not notify_on and settings.telegram_notify_trades and not dry_run:
            logger.info("telegram alerts enabled but bot token/chat id not configured")
        # Every trade's status before this run so the alert fires on the actual
        # FILL (status reaches "open"/"closed"), never on mere order submission
        # ("pending"/"closing") -- a resting limit that hasn't filled is not a
        # trade yet, and a re-armed close shouldn't read as a new open.
        if notify_on:
            pre_status = {
                sig: status
                for sig, status in db.execute(
                    select(PaperTrade.signal_id, PaperTrade.status)
                ).all()
            }

        summary["reconciled"] = _reconcile(db, client, dry_run)

        # Settle options that already expired. Does not need the market open -
        # there is nothing left to trade; we just journal intrinsic P&L so
        # stale "open" rows (DAL/PENG-style) don't linger forever.
        expired = _settle_expired_options(db, client, dry_run)
        summary["expired"] = expired
        summary["closed"] = expired

        # Fill in realized labels for past decisions whose trades have since
        # closed or aged (best-effort; never let the learning journal break a run).
        # Runs every cycle, including closed-market ones, so labels stay fresh.
        # Catch the journal up with any paper fills that predate live recording,
        # then grade closed trades so the entry model / calibration see history.
        try:
            created = backfill_from_paper_trades(db)
            labeled = sync_labels(db)
            if (created or labeled) and not dry_run:
                db.commit()
            if created:
                summary["backfilled"] = created
            summary["labeled"] = labeled
        except Exception as e:  # noqa: BLE001
            logger.warning("label sync failed: %s", e)

        if not market_open:
            logger.info("market closed; reconciling only, no orders this run")
            summary["skipped"] = [{"reason": "market closed"}]
            return summary

        # Learned exit discipline: derive the take-profit to enforce this run from
        # the realized record (guardrailed, falls back to the static default).
        # Computed before the managers so every directional book uses the same
        # threshold. Never let it break the run.
        try:
            learned_exit = compute_learned_take_profit(db, settings)
        except Exception as e:  # noqa: BLE001
            logger.warning("exit-learning compute failed: %s", e)
            learned_exit = None
        tp_pct = effective_take_profit(settings, learned_exit)
        if learned_exit and learned_exit.applicable:
            summary["take_profit_pct"] = tp_pct

        summary["closed"] += _manage_exits(db, client, settings, dry_run)
        summary["closed"] += _manage_wave_exits(db, client, settings, dry_run, tp_pct)
        summary["closed"] += _manage_drift_exits(db, client, settings, dry_run, tp_pct)
        summary["closed"] += _manage_reddit_exits(db, client, settings, dry_run, tp_pct)
        summary["closed"] += _manage_earnings_equity_exits(
            db, client, settings, dry_run, tp_pct
        )
        summary["closed"] += _manage_reversal_exits(db, client, settings, dry_run)

        # Calibration feedback: recalibrate each strategy's model win-probability
        # by its realized track record before the EV gate sees it (opt-in, and a
        # no-op empty map when disabled). Never let it break the run.
        try:
            calib = compute_calibration(db, settings)
        except Exception as e:  # noqa: BLE001
            logger.warning("calibration compute failed: %s", e)
            calib = {}
        if calib:
            summary["calibration"] = {s: e.multiplier for s, e in calib.items()}

        # Joint entry model: fit on the graded journal, then score candidates
        # in front of the EV / conviction gates. No-op stub when the sample is
        # too thin or AUC is a coin flip - never let a fit error break the run.
        try:
            entry_model = fit_entry_model(db, settings)
        except Exception as e:  # noqa: BLE001
            logger.warning("entry-model fit failed: %s", e)
            entry_model = None
        if entry_model is not None:
            summary["entry_model"] = {
                "applicable": entry_model.applicable,
                "n": entry_model.n,
                "cv_auc": entry_model.cv_auc,
                "reason": entry_model.reason,
            }

        # Each book scans independently - a bad underlying in one strategy must
        # not prevent the others from opening trades the same cycle.
        scan_results: list[tuple[int, list]] = []
        for label, fn in (
            ("earnings", lambda: _scan_entries(db, client, equity, settings, dry_run, calib, entry_model)),
            ("waves", lambda: _scan_wave_entries(db, client, equity, settings, dry_run, calib, entry_model)),
            ("drift", lambda: _scan_drift_entries(db, client, equity, settings, dry_run, calib, entry_model)),
            # Reddit sentiment book retired - do not scan for new entries.
            # Earnings-equity runs after the options scan so it can size a twin
            # to the spread that just opened (or stand alone otherwise).
            (
                "earnings_equity",
                lambda: _scan_earnings_equity_entries(
                    db, client, equity, settings, dry_run, entry_model, calib
                ),
            ),
            (
                "reversal",
                lambda: _scan_reversal_entries(db, client, equity, settings, dry_run),
            ),
        ):
            try:
                scan_results.append(fn())
            except AlpacaError as e:
                logger.error("%s scan aborted: %s", label, e)
                summary["errors"].append(f"{label}: {e}")
                scan_results.append((0, []))
        summary["opened"] = sum(n for n, _ in scan_results)
        summary["skipped"] = [s for _, skips in scan_results for s in skips]
        try:
            from app.services.paper.reversal import read_watch

            watch = read_watch()
            if watch:
                summary["reversal_watch"] = watch
        except Exception as e:  # noqa: BLE001
            logger.warning("reversal watch attach failed: %s", e)
    except AlpacaError as e:
        logger.error("Alpaca error during paper run: %s", e)
        summary["status"] = "error"
        summary["errors"].append(str(e))
    finally:
        # ALWAYS attempt trade alerts here. A late scan failure used to skip this
        # and silently swallow fills/closes that already landed earlier in the run.
        if notify_on:
            try:
                telegram = _notify_trades(db, pre_status)
                summary["telegram"] = telegram
                if telegram.get("attempted") and not telegram.get("ok"):
                    summary["errors"].append("telegram trade alert failed")
                    if summary.get("status") == "ok":
                        summary["status"] = "error"
            except Exception as e:  # noqa: BLE001 - never let a notify break the run
                logger.warning("trade notification failed: %s", e)
                summary["errors"].append(f"telegram notify exception: {e}")
                if summary.get("status") == "ok":
                    summary["status"] = "error"
        client.close()
    return summary


# --- reconcile ---------------------------------------------------------------


def _exit_is_urgent(reason: str | None) -> bool:
    """An exit we want filled *now*, even if it means crossing a wide option
    book: a manual/force flatten, a bad-fill flatten, or any stop. Planned
    exits (post-earnings harvest, hold-window, take-profit) stay patient at mid
    so we don't dump a spread into a thin bid for a few cents."""
    r = (reason or "").lower()
    return r == "manual close" or r.startswith("flatten") or "stop" in r


def _close_client_order_id(signal_id: str) -> str:
    """Unique per close *attempt*. A close limit can lapse (canceled/expired) and
    the position gets re-armed to retry; a fixed id (e.g. ``<sig>-x``) makes
    Alpaca reject every retry with ``client_order_id must be unique``, stranding
    the position open forever. A fresh suffix per attempt avoids that -- the DB
    tracks the returned Alpaca order id, so we never need to reproduce this."""
    return f"{signal_id}-x-{uuid.uuid4().hex[:8]}"


def _reconcile(db: Session, client: AlpacaClient, dry_run: bool) -> int:
    """Promote pending->open and closing->closed based on Alpaca order status."""
    count = 0
    pending = db.scalars(
        select(PaperTrade).where(PaperTrade.status.in_(("pending", "closing")))
    ).all()
    for t in pending:
        order_id = t.entry_order_id if t.status == "pending" else t.exit_order_id
        if not order_id:
            continue
        try:
            order = client.get_order(order_id)
        except AlpacaError:
            continue
        state = (order.get("status") or "").lower()
        fill = _to_float(order.get("filled_avg_price"))
        if t.status == "pending":
            if state == "filled":
                t.status = "open"
                t.opened_at = datetime.utcnow()
                if fill:
                    t.entry_credit = abs(fill)
                    if _is_equity(t):
                        # Anchor move-based exits to the real fill, not the
                        # pre-fill spot estimate (often a stale daily close).
                        t.spot_entry = round(abs(fill), 2)
                    _recompute_max_risk(t)
                    _enforce_fill_economics(t)
                count += 1
            elif state in ("canceled", "expired", "rejected"):
                t.status = "canceled"
                t.note = f"entry {state}"
                count += 1
        elif t.status == "closing":
            if state == "filled":
                t.status = "closed"
                t.closed_at = datetime.utcnow()
                if fill is not None:
                    t.exit_debit = abs(fill)
                _finalize_pnl(t)
                count += 1
            elif state in ("canceled", "expired", "rejected"):
                # The close (a limit at our target credit) didn't fill and the
                # day order lapsed. Re-arm to open so the next manage-exits pass
                # re-attempts - never leave a position stuck mid-close.
                t.status = "open"
                t.exit_order_id = None
                count += 1
    if not dry_run:
        db.commit()
    return count


# --- exits -------------------------------------------------------------------


def _spot_on_or_before(db: Session, ticker: str, on: date) -> float | None:
    """Underlying close on ``on``, or the most recent bar at or before that date."""
    bar = db.scalars(
        select(PriceBar)
        .where(PriceBar.ticker == ticker, PriceBar.date <= on)
        .order_by(PriceBar.date.desc())
    ).first()
    if bar is None or bar.close is None:
        return None
    return float(bar.close)


def _expiry_exit_value(
    strategy: str | None, legs: list[dict], spot: float | None
) -> float:
    """Per-share exit mark used when an option expires.

    Debit strategies (waves/drift/reddit) store close *proceeds* in
    ``exit_debit``; credit strategies store *cost to close*. Missing spot or
    strikes → treat as expired worthless (0), which unblocks the row rather
    than leaving it open forever.
    """
    intrinsic = _spread_intrinsic(legs, spot)
    if intrinsic is None:
        return 0.0
    if (strategy or "earnings") in DEBIT_STRATEGIES:
        return max(0.0, intrinsic)
    return max(0.0, -intrinsic)


def _settle_expired_options(
    db: Session, client: AlpacaClient, dry_run: bool
) -> int:
    """Journal-settle option trades whose expiration has already passed.

    After expiry Alpaca stops returning usable option quotes, so every
    quote-gated exit manager ``continue``s forever and the row stays ``open``.
    There is nothing left to close at the broker - settle at intrinsic against
    the underlying close on/before expiration and mark the trade closed.
    """
    today = date.today()
    trades = db.scalars(
        select(PaperTrade).where(
            PaperTrade.status.in_(("open", "closing")),
            PaperTrade.expiration.is_not(None),
            PaperTrade.expiration < today,
        )
    ).all()
    settled = 0
    for t in trades:
        if _is_equity(t):
            continue
        try:
            legs = json.loads(t.legs or "[]")
        except json.JSONDecodeError:
            legs = []
        if not legs:
            logger.warning(
                "expired %s (%s) has no legs; closing at 0", t.signal_id, t.ticker
            )
        spot = None
        if t.expiration is not None:
            spot = _spot_on_or_before(db, t.ticker, t.expiration)
        if spot is None:
            # Last resort: live underlying (worse than the expiry close, but
            # unblocks rows for tickers we never stored bars for).
            try:
                spot = client.stock_price(t.ticker)
            except AlpacaError:
                spot = None
        exit_value = _expiry_exit_value(t.strategy, legs, spot)
        if dry_run:
            logger.info(
                "[dry-run] would settle expired %s %s at %.2f (spot=%s)",
                t.signal_id,
                t.ticker,
                exit_value,
                spot,
            )
            continue
        if t.exit_order_id:
            # Resting close can't fill on a delisted contract; drop it.
            client.cancel_order(t.exit_order_id)
            t.exit_order_id = None
        t.exit_debit = exit_value
        t.status = "closed"
        t.closed_at = datetime.utcnow()
        t.note = "expired (settled at intrinsic)"
        if spot is not None:
            t.spot_at_exit = round(spot, 2)
            if t.spot_entry:
                t.realized_move_pct = round(spot / t.spot_entry - 1, 4)
            if legs:
                t.breached_short = _breached_short(legs, spot)
        _finalize_pnl(t)
        settled += 1
        logger.info(
            "settled expired %s %s at %.2f (spot=%s, pnl=%s)",
            t.signal_id,
            t.ticker,
            exit_value,
            spot,
            t.realized_pnl,
        )
    if not dry_run and settled:
        db.commit()
    return settled


def _manage_exits(db: Session, client: AlpacaClient, settings, dry_run: bool) -> int:
    """Close open positions when one of three things is true:
      - the earnings print has passed (planned harvest of the IV crush), or
      - the unrealized loss hits the hard stop (a fraction of max risk), or
      - we're near expiry and the loss hits the tighter late-stop.
    The stops are only as timely as the cron cadence (each run is one check)."""
    today = date.today()
    closed = 0
    open_trades = db.scalars(
        select(PaperTrade).where(PaperTrade.status == "open")
    ).all()
    for t in open_trades:
        if _is_equity(t):
            continue  # equity twins are closed by the Reddit manager, not here
        legs = json.loads(t.legs or "[]")
        symbols = [l["symbol"] for l in legs]
        quotes = client.option_quotes(symbols)
        if any((quotes.get(s, {}).get("mid") or 0) <= 0 for s in symbols):
            # Can't price the close right now; try again next run.
            continue
        # Net cost to close = current value of the short legs minus the longs.
        exit_net = round(
            sum(quotes[l["symbol"]]["mid"] for l in legs if l["side"] == "sell")
            - sum(quotes[l["symbol"]]["mid"] for l in legs if l["side"] == "buy"),
            2,
        )

        reason = _exit_reason(t, exit_net, today, settings)
        if reason is None:
            continue

        close_legs = [
            {
                "symbol": l["symbol"],
                "ratio_qty": "1",
                "side": "buy" if l["side"] == "sell" else "sell",
                "position_intent": "buy_to_close"
                if l["side"] == "sell"
                else "sell_to_close",
            }
            for l in legs
        ]
        if dry_run:
            logger.info(
                "[dry-run] would close %s (%s) at net %.2f", t.signal_id, reason, exit_net
            )
            continue
        try:
            order = _submit_spread_close(
                client, close_legs, t.contracts or 1, t.signal_id,
                is_credit=False, mid=exit_net, urgent=_exit_is_urgent(reason),
                settings=settings, quotes=quotes,
            )
        except AlpacaError as e:
            logger.error("Close failed for %s: %s", t.signal_id, e)
            continue
        t.exit_order_id = order.get("id")
        t.exit_debit = exit_net
        t.status = "closing"
        t.note = reason
        _record_outcome(db, t, legs)  # realized move + breach labels
        _finalize_pnl(t)  # provisional, refined on fill
        closed += 1
    if not dry_run:
        db.commit()
    return closed


def _underlying_take_profit(
    t: PaperTrade, spot_now: float | None, settings, tp_pct: float
) -> str | None:
    """Global take-profit on the direction-adjusted underlying move, applied to the
    directional books so we harvest a move instead of round-tripping it. Binds
    before each book's looser gain target because ``tp_pct`` is the tighter one.
    Returns a close reason or None."""
    if not settings.paper_take_profit_enabled or not spot_now:
        return None
    entry = t.spot_entry or t.entry_credit
    if not entry or entry <= 0:
        return None
    move = spot_now / entry - 1.0
    if t.direction == "bullish":
        fav = move
    elif t.direction == "bearish":
        fav = -move
    else:
        return None
    if fav >= tp_pct:
        return f"take-profit (+{fav:.1%} underlying)"
    return None


def _exit_reason(t: PaperTrade, exit_net: float, today: date, settings) -> str | None:
    """Decide whether (and why) to close an open trade now."""
    # Operational override: flatten specific signal ids on request (e.g. a bad
    # fill) through the normal close path so the DB stays consistent. This is a
    # manual escape hatch and applies to every strategy, so it runs before the
    # earnings-only guard below.
    if t.signal_id in settings.paper_force_close_id_set:
        return "manual close"
    # A fill that breached the fair-trade plan (flagged post-fill) is flattened
    # on the next pass, for every strategy, before the earnings-only guard below.
    if (t.note or "").startswith(_BAD_FILL_PREFIX):
        return "flatten: bad entry fill"
    # This is the *earnings* (sell-vol) manager only. Drift, waves and reddit
    # trades each have their own exit manager (_manage_drift_exits, etc.) with
    # strategy-appropriate hold windows, take-profits and stops. Without this
    # guard the "post-earnings" harvest below would instantly flatten every
    # drift trade - a drift entry is by definition placed *after* the print, so
    # earnings_date < today is always true - closing it on the first cron cycle
    # before its own manager ever runs.
    if (t.strategy or "earnings") != "earnings":
        return None
    # Planned exit: the print has passed - close to capture the IV crush. We
    # wait until strictly after the earnings date so we don't close ahead of an
    # after-market report on the day itself.
    if t.earnings_date and t.earnings_date < today:
        return "post-earnings"

    # Loss-based stops (opt-in). Measure the unrealized loss against capital at risk.
    if settings.paper_stops_enabled and t.entry_credit is not None and t.max_risk and t.contracts:
        unrealized = (t.entry_credit - exit_net) * 100 * t.contracts
        loss_frac = -unrealized / t.max_risk  # > 0 means we're losing
        if loss_frac >= settings.paper_stop_loss_frac:
            return f"stop-loss ({loss_frac:.0%} of risk)"
        if t.expiration is not None:
            dte = (t.expiration - today).days
            if dte <= settings.paper_late_dte and loss_frac >= settings.paper_late_stop_frac:
                return f"late stop ({loss_frac:.0%} of risk, {dte}DTE)"
    return None


def _finalize_pnl(t: PaperTrade) -> None:
    if t.entry_credit is None or t.exit_debit is None or not t.contracts:
        return
    if _is_equity(t):
        # Plain stock: entry_credit/exit_debit hold price per share, contracts
        # holds share count (no 100x option multiplier). Long profits when the
        # price rises; a short profits when it falls.
        if t.structure == EQUITY_LONG:
            t.realized_pnl = round((t.exit_debit - t.entry_credit) * t.contracts, 2)
        else:
            t.realized_pnl = round((t.entry_credit - t.exit_debit) * t.contracts, 2)
        t.outcome = "win" if t.realized_pnl > 0 else "loss"
        return
    if (t.strategy or "earnings") in ("waves", "drift", "reddit"):
        # We paid a debit (long option or debit spread): profit = proceeds on
        # close - cost paid at entry. entry_credit holds the debit, exit_debit
        # the close proceeds.
        t.realized_pnl = round((t.exit_debit - t.entry_credit) * 100 * t.contracts, 2)
    else:
        # Credit structure: profit = credit collected - cost to close.
        t.realized_pnl = round((t.entry_credit - t.exit_debit) * 100 * t.contracts, 2)
    t.outcome = "win" if t.realized_pnl > 0 else "loss"


def _record_outcome(db: Session, t: PaperTrade, legs: list[dict]) -> None:
    """Capture the realized labels for later model calibration: the underlying's
    move from entry to exit, and whether it breached a short strike (the clean
    'was the sell-vol thesis right' signal, independent of fill quality)."""
    bar = db.scalars(
        select(PriceBar)
        .where(PriceBar.ticker == t.ticker)
        .order_by(PriceBar.date.desc())
    ).first()
    spot_exit = bar.close if bar else None
    if spot_exit:
        t.spot_at_exit = round(spot_exit, 2)
        if t.spot_entry:
            t.realized_move_pct = round(spot_exit / t.spot_entry - 1, 4)
        t.breached_short = _breached_short(legs, spot_exit)


def _breached_short(legs: list[dict], spot: float) -> bool:
    for leg in legs:
        if leg.get("side") != "sell":
            continue
        strike = leg.get("strike")
        if strike is None:
            continue
        if leg.get("type") == "call" and spot > strike:
            return True
        if leg.get("type") == "put" and spot < strike:
            return True
    return False


# --- entries -----------------------------------------------------------------


def _score_setup(
    db: Session,
    ticker: str,
    feats: dict,
    strategy: str,
    model,
    calib: dict | None,
    settings,
) -> tuple[dict, float | None, str | None]:
    """Attach size/liquidity, score with the entry model, annotate feats.

    Returns ``(feats, gate_win_prob, skip_reason)``. ``skip_reason`` is set when
    the model vetoes; ``gate_win_prob`` is what the EV gate should consume
    (model p when live, calibrated heuristic otherwise).
    """
    feats = attach_context_features(db, ticker, feats, as_of=date.today())
    heuristic = feats.get("win_prob")
    gate_p, skip, model_p = resolve_entry_probability(
        heuristic, feats, strategy, model, calib, settings,
    )
    if model_p is not None:
        feats["model_win_prob"] = model_p
    return feats, gate_p, skip


def _scan_entries(
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool,
    calib: dict | None = None,
    model=None,
) -> tuple[int, list]:
    today = date.today()
    window_end = today + timedelta(days=settings.paper_entry_window_days)
    regime = regime_snapshot(settings)

    # Cap is for the earnings *options* book only - equity twins have their own
    # (higher) limit and must not crowd options out of these slots.
    open_n = len(
        db.scalars(
            select(PaperTrade).where(
                PaperTrade.strategy == "earnings",
                PaperTrade.structure.not_in(EQUITY_STRUCTURES),
                PaperTrade.status.in_(OPEN_STATES),
            )
        ).all()
    )

    events = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.date >= today, EarningsEvent.date <= window_end)
        .order_by(EarningsEvent.date.asc())
    ).all()

    opened = 0
    skipped: list[dict] = []
    seen: set[str] = set()
    for ev in events:
        ticker = ev.ticker
        if ticker in seen:
            continue
        seen.add(ticker)
        try:
            opened_one, skip = _try_earnings_entry(
                db, client, equity, settings, dry_run, calib, model,
                ev=ev, ticker=ticker, open_n=open_n, opened=opened, regime=regime,
            )
        except AlpacaError as e:
            # One bad underlying (e.g. unmapped share-class ticker) must not
            # abort the rest of earnings season.
            logger.error("Alpaca error on %s; continuing scan: %s", ticker, e)
            reason = f"alpaca error: {e}"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="earnings", ticker=ticker, decision="skipped",
                earnings_date=ev.date, skip_reason=reason[:500], regime=regime,
            )
            continue
        if skip:
            skipped.append(skip)
        opened += opened_one

    if not dry_run:
        db.commit()
    return opened, skipped


def _try_earnings_entry(
    db: Session,
    client: AlpacaClient,
    equity: float,
    settings,
    dry_run: bool,
    calib: dict | None,
    model=None,
    *,
    ev: EarningsEvent,
    ticker: str,
    open_n: int,
    opened: int,
    regime: dict,
) -> tuple[int, dict | None]:
    """Attempt one earnings sell-vol entry. Returns (opened_delta, skip_row)."""
    if open_n + opened >= settings.paper_max_open:
        return 0, {"ticker": ticker, "reason": "max open positions reached"}

    # Already have an options trade for this ticker+event? Equity twins for
    # the same print don't count - they have their own one-per-event guard.
    existing = db.scalars(
        select(PaperTrade).where(
            PaperTrade.ticker == ticker,
            PaperTrade.earnings_date == ev.date,
            PaperTrade.strategy == "earnings",
            PaperTrade.structure.not_in(EQUITY_STRUCTURES),
        )
    ).first()
    if existing:
        return 0, None

    detail = company_detail(db, ticker)
    pb = (detail or {}).get("playbook")
    if not pb:
        return 0, {"ticker": ticker, "reason": "no playbook"}
    im = (detail or {}).get("implied_move") or {}
    if pb["vol_stance"] != "sell" or pb["structure"] not in SELLING_STRUCTURES:
        reason = f"not a sell-vol setup ({pb['structure']})"
        record_decision(
            db, strategy="earnings", ticker=ticker, decision="skipped",
            earnings_date=ev.date, skip_reason=reason, regime=regime,
            features=earnings_features(pb, im, equity=equity),
        )
        return 0, {"ticker": ticker, "reason": reason}

    # Size by the playbook's conviction: risk more when the signals agree.
    # The budget also caps the spread width (wings pull in to fit it).
    risk_frac = settings.paper_risk_fraction(pb["conviction"])
    budget = equity * risk_frac

    spec, reason = build_trade_spec(
        client, ticker, pb, ev.date,
        risk_budget=budget,
        min_credit_ratio=settings.paper_min_credit_width_ratio,
    )
    if spec is None:
        record_decision(
            db, strategy="earnings", ticker=ticker, decision="skipped",
            earnings_date=ev.date, skip_reason=reason, regime=regime,
            features=earnings_features(pb, im, risk_frac=risk_frac, equity=equity),
        )
        return 0, {"ticker": ticker, "reason": reason}
    if spec.net_credit < settings.paper_min_credit:
        reason = f"credit too thin ({spec.net_credit})"
        record_decision(
            db, strategy="earnings", ticker=ticker, decision="skipped",
            earnings_date=ev.date, skip_reason=reason, regime=regime,
            features=earnings_features(pb, im, spec=spec, risk_frac=risk_frac, equity=equity),
        )
        return 0, {"ticker": ticker, "reason": reason}

    contracts = int(budget // spec.max_risk_per_contract)
    contracts = min(contracts, settings.paper_max_contracts)
    if contracts < 1:
        reason = (
            f"spread too wide for {pb['conviction']} budget "
            f"({risk_frac:.1%} = ${budget:.0f}; risk ${spec.max_risk_per_contract:.0f}/ct)"
        )
        record_decision(
            db, strategy="earnings", ticker=ticker, decision="skipped",
            earnings_date=ev.date, skip_reason=reason, regime=regime,
            features=earnings_features(pb, im, spec=spec, risk_frac=risk_frac, equity=equity),
        )
        return 0, {"ticker": ticker, "reason": reason}

    trade = _record_trade(
        db, ticker, ev, pb, spec, contracts,
        expected_move_pct=im.get("expected_move_pct"),
        spot_entry=im.get("underlying_price") or pb.get("spot"),
        equity=equity,
    )
    feats = earnings_features(
        pb, im, spec=spec, contracts=contracts, risk_frac=risk_frac, equity=equity
    )
    feats, win_prob, model_skip = _score_setup(
        db, ticker, feats, "earnings", model, calib, settings,
    )
    if model_skip:
        trade.status = "canceled"
        trade.note = f"skipped: {model_skip}"
        record_decision(
            db, strategy="earnings", ticker=ticker, decision="skipped",
            earnings_date=ev.date, skip_reason=model_skip, regime=regime,
            features=feats,
        )
        return 0, {"ticker": ticker, "reason": model_skip}

    if dry_run:
        logger.info(
            "[dry-run] %s %s [%s %.1f%%] x%d @ credit %.2f (risk $%.0f)",
            ticker, pb["structure"], pb["conviction"], risk_frac * 100,
            contracts, spec.net_credit, spec.max_risk_per_contract * contracts,
        )
        trade.note = "dry-run (not submitted)"
        record_decision(
            db, strategy="earnings", ticker=ticker, decision="opened",
            earnings_date=ev.date, signal_id=trade.signal_id, regime=regime,
            features=feats,
        )
        return 1, None

    order_legs = [
        {
            "symbol": l.symbol,
            "ratio_qty": "1",
            "side": l.side,
            "position_intent": l.position_intent,
        }
        for l in spec.legs
    ]
    # Sell-vol win probability: the entry model (when live) jointly weights
    # size / implied vol / history; otherwise the strike-level seller edge,
    # recalibrated by the strategy's track record.
    limit, reason = _gate_entry(
        client, order_legs, is_credit=True, mid=spec.net_credit,
        width=spec.width, win_prob=win_prob, settings=settings,
    )
    if limit is None:
        trade.status = "canceled"
        trade.note = f"skipped: {reason}"
        record_decision(
            db, strategy="earnings", ticker=ticker, decision="skipped",
            earnings_date=ev.date, skip_reason=reason, regime=regime,
            features=feats,
        )
        return 0, {"ticker": ticker, "reason": reason}
    try:
        order = client.submit_mleg(
            legs=order_legs,
            qty=contracts,
            limit_price=limit,
            client_order_id=trade.signal_id,
        )
    except AlpacaError as e:
        logger.error("Order failed for %s: %s", ticker, e)
        trade.status = "canceled"
        trade.note = f"submit error: {e}"[:500]
        record_decision(
            db, strategy="earnings", ticker=ticker, decision="skipped",
            earnings_date=ev.date, skip_reason=f"submit error: {e}", regime=regime,
            features=feats,
        )
        return 0, {"ticker": ticker, "reason": f"submit error: {e}"}
    trade.entry_order_id = order.get("id")
    _apply_entry_fill(trade, order)
    record_decision(
        db, strategy="earnings", ticker=ticker, decision="opened",
        earnings_date=ev.date, signal_id=trade.signal_id, regime=regime,
        features=feats,
    )
    return 1, None


def _record_trade(
    db: Session,
    ticker: str,
    ev: EarningsEvent,
    pb: dict,
    spec: TradeSpec,
    contracts: int,
    expected_move_pct: float | None = None,
    spot_entry: float | None = None,
    equity: float | None = None,
) -> PaperTrade:
    signal_id = _next_signal_id(db)
    thesis = {
        "headline": pb.get("headline"),
        "bias_reasons": pb.get("bias_reasons"),
        "vol_reasons": pb.get("vol_reasons"),
        "conviction_basis": pb.get("conviction_basis"),
        "timing": pb.get("timing"),
        "spot": pb.get("spot"),
        "expected_range": [pb.get("expected_range_low"), pb.get("expected_range_high")],
    }
    legs_json = json.dumps(
        [
            {
                "symbol": l.symbol,
                "type": l.option_type,
                "side": l.side,
                "strike": l.strike,
                "mid": l.mid,
            }
            for l in spec.legs
        ]
    )
    trade = PaperTrade(
        signal_id=signal_id,
        ticker=ticker,
        earnings_date=ev.date,
        structure=pb["structure"],
        direction=pb["direction"],
        vol_stance=pb["vol_stance"],
        conviction=pb["conviction"],
        thesis=json.dumps(thesis)[:2048],
        status="pending",
        legs=legs_json[:2048],
        contracts=contracts,
        expiration=spec.expiration,
        width=spec.width,
        entry_credit=spec.net_credit,
        modeled_credit=spec.net_credit,
        max_risk=round(spec.max_risk_per_contract * contracts, 2),
        expected_move_pct=expected_move_pct,
        spot_entry=round(spot_entry, 2) if spot_entry else None,
        equity_at_entry=round(equity, 2) if equity else None,
    )
    db.add(trade)
    db.flush()
    return trade


def _next_signal_id(db: Session) -> str:
    stamp = date.today().strftime("%Y%m%d")
    prefix = f"EF-{stamp}-"
    n = len(
        db.scalars(
            select(PaperTrade).where(PaperTrade.signal_id.like(f"{prefix}%"))
        ).all()
    )
    return f"{prefix}{n + 1:03d}"


def _to_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _spread_intrinsic(legs: list[dict], spot: float | None) -> float | None:
    """Intrinsic value (per share) of the held leg package at ``spot``: the sum
    of each leg's intrinsic value, signed +buy / -sell. For a long debit spread
    this is >= 0 and is the floor price the position is worth right now (a
    market can't rationally pay less to take it off you). Returns None if we
    can't price it (missing spot/strike), so callers fall back to no floor."""
    if not spot:
        return None
    total = 0.0
    for l in legs:
        strike = l.get("strike")
        if strike is None:
            return None
        if l.get("type") == "call":
            iv = max(spot - strike, 0.0)
        elif l.get("type") == "put":
            iv = max(strike - spot, 0.0)
        else:
            return None
        total += iv if l.get("side") == "buy" else -iv
    return round(total, 2)


def _marketable_net(
    client: AlpacaClient,
    legs: list[dict],
    is_credit: bool,
    mid: float,
    settings,
    quotes: dict | None = None,
    aggressive: bool = True,
    exit_cross: bool = False,
    min_credit: float | None = None,
    max_debit: float | None = None,
) -> float | None:
    """Signed net limit price for a leg set, or ``None`` if the market's too wide
    to trade (entries only).

    SIGN - Alpaca multi-leg ``limit_price`` is signed: a positive value is a net
    *debit* (the most we'll pay), a negative value is a net *credit* (the least
    we'll accept to receive). A net-credit order sent as a *positive* number is
    read as a debit ceiling - i.e. "pay up to X to close" - which makes it
    marketable and dumps the spread into the touch (that's what closed a $6-wide
    spread for $0.35). So every credit order MUST be negative. We compute a
    positive magnitude below and sign it at the end.

    ``aggressive`` (entries): price at the *cross* - take the ask on legs we buy
    and hit the bid on legs we sell, plus a small buffer - so it fills. But if
    crossing the market gives up more than ``paper_max_cross_slippage_frac`` of
    the combo's mid value, the market is too wide/illiquid to trade without the
    round-trip slippage swamping the edge, so we return ``None`` and skip it
    (this is what bled AMD/MU: $8+-wide legs mean crossing costs more than the
    spread is worth).

    ``min_credit`` (credit orders): a hard floor on the credit we'll accept. On
    a credit *exit* (selling a debit spread we own) pass the spread's intrinsic
    value here so a stale/wide book can never fill us below intrinsic - the bug
    that closed an in-the-money 85/90 spread for $0.70. ``max_debit`` is the
    symmetric ceiling for debit exits (never pay more than the spread is worth).

    not ``aggressive`` (exits): price at the **mid** nudged only a buffer toward
    the touch, then clamped by the intrinsic floor/ceiling above. We already
    hold the position, so we never cross to a thin bid and give the spread away;
    if it doesn't fill (e.g. the book won't meet intrinsic) we just retry next
    run, and a defined-risk spread settles at intrinsic by expiry anyway.
    """
    syms = [l["symbol"] for l in legs]
    q = quotes if quotes is not None else client.option_quotes(syms)
    buf = settings.paper_fill_buffer

    def _mag(price: float) -> float:
        # An urgent exit (exit_cross) crosses to the touch to guarantee a fill;
        # don't clamp it back to intrinsic or it may rest unfilled.
        if is_credit and min_credit is not None and not exit_cross:
            price = max(price, min_credit)
        return round(max(0.01, price), 2)

    def _signed(mag: float) -> float:
        # + = net debit (we pay), - = net credit (we receive). See SIGN above.
        return -mag if is_credit else mag

    if not aggressive:
        # Exit: sell a hair below mid (credit) / pay a hair above mid (debit).
        if is_credit:
            price = mid - buf
            # Never sell the spread for less than it's intrinsically worth.
            if min_credit is not None:
                price = max(price, min_credit)
        else:
            price = mid + buf
            # Never pay more than the spread can possibly be worth.
            if max_debit is not None:
                price = min(price, max_debit)
        return _signed(round(max(0.01, price), 2))

    def take(sym: str, want: str) -> float:
        qq = q.get(sym, {})
        v = qq.get(want) or 0.0
        return v if v > 0 else (qq.get("mid") or 0.0)

    # Both sides cross the same way: pay the ask on buys, receive the bid on sells.
    buy_ask = sum(take(l["symbol"], "ask") for l in legs if l["side"] == "buy")
    sell_bid = sum(take(l["symbol"], "bid") for l in legs if l["side"] == "sell")
    if buy_ask <= 0 and sell_bid <= 0:
        return _signed(_mag(mid))

    if not settings.paper_fill_cross:
        return _signed(_mag(mid))

    if is_credit:
        # We sell the package; accept the bid side (minus a buffer) to fill.
        cross = (sell_bid - buy_ask) - buf
    else:
        # We buy the package; pay the ask side (plus a buffer) to fill.
        cross = (buy_ask - sell_bid) + buf

    # Liquidity guard: refuse to open when crossing gives up too much of the
    # spread's mid value - a wide market bleeds far more on the round trip than
    # the trade can make. Skipped for urgent exits (exit_cross): we already hold
    # the position and want out now, so we pay the touch regardless of width.
    if (
        mid > 0
        and not exit_cross
        and abs(cross - mid) > settings.paper_max_cross_slippage_frac * mid
    ):
        logger.info(
            "skip entry: market too wide (mid %.2f vs cross %.2f, slip %.0f%% > %.0f%%)",
            mid, cross, abs(cross - mid) / mid * 100,
            settings.paper_max_cross_slippage_frac * 100,
        )
        return None

    return _signed(_mag(cross))


def _walk_mleg_to_fill(
    client: AlpacaClient,
    legs: list[dict],
    qty: int,
    signal_id: str,
    start: float,
    end: float,
    settings,
) -> dict:
    """Close a spread by walking the net limit from ``start`` (patient, ~mid)
    toward ``end`` (the marketable cross), conceding ``paper_walk_step`` per
    dwell until it fills or the per-order budget elapses -- then drop a final
    order at ``end`` and let reconcile finish it. Prices are signed nets
    (negative = credit, positive = debit); we always step from start toward end.
    Returns the order to record as the exit (the filled one, or the final)."""
    step = max(0.01, settings.paper_walk_step)
    interval = max(0.0, settings.paper_walk_interval_seconds)
    deadline = time.monotonic() + max(0.0, settings.paper_walk_max_seconds)
    up = end >= start
    price = round(start, 2)

    def _submit(px: float) -> dict:
        return client.submit_mleg(
            legs=legs, qty=qty, limit_price=px,
            client_order_id=_close_client_order_id(signal_id),
        )

    while True:
        order = _submit(price)
        oid = order.get("id")
        if interval:
            time.sleep(interval)
        try:
            probe = client.get_order(oid) if oid else {}
        except AlpacaError:
            probe = {}
        if (probe.get("status") or "").lower() == "filled":
            return probe
        if oid:
            client.cancel_order(oid)
        reached = price >= end if up else price <= end
        if reached or time.monotonic() >= deadline:
            return _submit(round(end, 2))
        price = round(price + step, 2) if up else round(price - step, 2)
        if (up and price > end) or (not up and price < end):
            price = round(end, 2)


def _submit_spread_close(
    client: AlpacaClient,
    legs: list[dict],
    qty: int,
    signal_id: str,
    *,
    is_credit: bool,
    mid: float,
    urgent: bool,
    settings,
    quotes: dict | None = None,
    min_credit: float | None = None,
    max_debit: float | None = None,
) -> dict:
    """Submit the closing order for an option spread. Non-urgent (planned
    harvest / take-profit): one patient limit at ~mid. Urgent (manual close /
    stop): walk the limit from mid toward the marketable cross so we concede
    only as much as the book demands to fill."""
    patient = _marketable_net(
        client, legs, is_credit=is_credit, mid=mid, settings=settings,
        quotes=quotes, aggressive=False, min_credit=min_credit, max_debit=max_debit,
    )
    if not (urgent and settings.paper_walk_limit_enabled):
        return client.submit_mleg(
            legs=legs, qty=qty, limit_price=patient,
            client_order_id=_close_client_order_id(signal_id),
        )
    cross = _marketable_net(
        client, legs, is_credit=is_credit, mid=mid, settings=settings,
        quotes=quotes, aggressive=True, exit_cross=True,
    )
    if cross is None:
        cross = patient
    return _walk_mleg_to_fill(
        client, legs, qty, signal_id, start=patient, end=cross, settings=settings,
    )


def _gate_entry(
    client: AlpacaClient,
    order_legs: list[dict],
    *,
    is_credit: bool,
    mid: float,
    width: float,
    win_prob: float | None,
    settings,
) -> tuple[float | None, str | None]:
    """Price an entry at the marketable cross and run the fair-trade economics
    gate on that *executable* price (never the modeled mid). Shared by all four
    strategies. Returns ``(limit, reason)``: when ``limit`` is None the trade must
    be skipped and ``reason`` says why -- the market's too wide to price, the
    contracts are illiquid, or the price fails the reward:risk / expected-value /
    fair-price gate. We price on the true cross and *reject* rich trades here
    rather than silently capping the limit, so we never submit an order we can't
    fill at a fair price (the user's chosen behavior: skip, don't chase)."""
    quotes = client.option_quotes([l["symbol"] for l in order_legs])
    min_credit = settings.paper_min_credit_width_ratio * width if is_credit else None
    limit = _marketable_net(
        client, order_legs, is_credit=is_credit, mid=mid, settings=settings,
        quotes=quotes, min_credit=min_credit,
    )
    if limit is None:
        return None, "market too wide (illiquid)"
    ok, reason, metrics = evaluate_entry(
        is_credit=is_credit, width=width, price=abs(limit), win_prob=win_prob,
        legs=order_legs, quotes=quotes, settings=settings,
    )
    if not ok:
        logger.info(
            "skip entry: %s | limit=%.2f rr=%s ev=%s maxP=%s maxL=%s",
            reason, abs(limit), metrics.reward_risk, metrics.expected_value,
            metrics.max_profit, metrics.max_loss,
        )
        return None, reason
    return limit, None


def _recompute_max_risk(trade: PaperTrade) -> None:
    """Re-derive max_risk from the *actual* booked entry price.

    At record time max_risk is modeled off the mid credit, but the real fill
    almost always differs. Recomputing here keeps the stored max loss - and the
    max-profit:max-loss ratio the UI derives from it - consistent with the
    credit/debit we actually booked (otherwise the card shows max profit from the
    fill but max loss from the stale model)."""
    if _is_equity(trade):
        # Equity risk is the notional we set at entry (there's no defined-risk
        # width); leave it as recorded.
        return
    risk = defined_risk_max_loss(
        trade.strategy, trade.width, trade.entry_credit, trade.contracts
    )
    if risk is not None:
        trade.max_risk = risk


def _enforce_fill_economics(trade: PaperTrade) -> None:
    """Re-check a freshly-booked entry against the fair-trade plan at its *actual*
    fill price. Alpaca paper can fill worse than the limit we sent, so a fill that
    blows past the fair-price band or the reward:risk floor is a structurally
    losing position -- flag it (via the note sentinel) so the next manage-exits
    pass flattens it rather than holding a doomed trade. Options spreads only;
    equity twins have no defined width to evaluate."""
    if _is_equity(trade) or trade.width is None:
        return
    is_credit = (trade.strategy or "earnings") not in DEBIT_STRATEGIES
    ok, reason = fill_within_plan(
        is_credit, trade.width, trade.entry_credit, get_settings()
    )
    if not ok:
        trade.note = f"{_BAD_FILL_PREFIX} {reason}"[:500]
        logger.warning(
            "bad entry fill on %s: %s (fill %.2f on %.0f-wide) -> flag to flatten",
            trade.signal_id, reason, trade.entry_credit or 0.0, trade.width,
        )


def _apply_entry_fill(trade: PaperTrade, order: dict) -> bool:
    """If the just-submitted entry already filled (marketable orders usually do),
    promote it to open immediately so it's tracked without waiting for the next
    reconcile. Only filled orders ever become tracked positions."""
    state = (order.get("status") or "").lower()
    if state == "filled":
        trade.status = "open"
        trade.opened_at = datetime.utcnow()
        fill = _to_float(order.get("filled_avg_price"))
        if fill:
            trade.entry_credit = abs(fill)
            if _is_equity(trade):
                # Anchor move-based exits to the real fill, not the pre-fill
                # spot estimate (often a stale daily close).
                trade.spot_entry = round(abs(fill), 2)
            _recompute_max_risk(trade)
            _enforce_fill_economics(trade)
        return True
    return False


# --- earnings equity book (options A/B twin) ---------------------------------


def _earnings_equity_shares(notional: float | None, spot: float | None) -> int:
    """Whole shares a given dollar notional buys at ``spot`` (0 if unpriceable).
    Same convention as the Reddit twin: floor, no fractional shares."""
    if not spot or spot <= 0 or not notional or notional <= 0:
        return 0
    return int(notional // spot)


def earnings_equity_trailing_halt(db: Session, settings) -> str | None:
    """Block new earnings-stock entries after a 0-for-N closed streak.

    The book stays enabled (it is the control group). Open rows still manage.
    Same retirement shape as waves: the live sample has to actually go 0-for-N
    on this sleeve, not because option debits failed.
    """
    if not getattr(settings, "paper_earnings_equity_halt_enabled", True):
        return None
    window = int(getattr(settings, "paper_earnings_equity_halt_window", 12) or 0)
    if window < 1:
        return None
    rows = db.scalars(
        select(PaperTrade)
        .where(
            PaperTrade.strategy == "earnings",
            PaperTrade.structure.in_(EQUITY_STRUCTURES),
            PaperTrade.status == "closed",
            PaperTrade.realized_pnl.is_not(None),
        )
        .order_by(PaperTrade.closed_at.desc(), PaperTrade.id.desc())
        .limit(window)
    ).all()
    if len(rows) < window:
        return None
    if all((t.realized_pnl or 0) <= 0 for t in rows):
        return f"earnings-equity halt (0-for-{window} closed)"
    return None


def _scan_earnings_equity_entries(
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool,
    model=None, calib: dict | None = None,
) -> tuple[int, list]:
    """Directional equity book that shadows the earnings options play, so we can
    compare whether the shares beat the options on the same signal.

    Fires for any bullish/bearish earnings name in the window (neutral / iron
    condor names get no equity leg -- shares are inherently directional). Two
    sizings:
      - twin: when the options spread for this event opened cleanly this cycle,
        risk the SAME dollars the spread risks (its max loss).
      - standalone: when the options trade was gated (illiquid / too thin) or the
        name is directional but not a sell-vol setup, still take the shares, sized
        to the conviction budget the options would have used.
    """
    if not settings.paper_earnings_equity_enabled:
        return 0, []
    halt = earnings_equity_trailing_halt(db, settings)
    if halt:
        logger.info("earnings-equity: %s - no new entries", halt)
        return 0, [{"reason": halt}]
    today = date.today()
    window_end = today + timedelta(days=settings.paper_entry_window_days)
    regime = regime_snapshot(settings)

    open_positions = db.scalars(
        select(PaperTrade).where(
            PaperTrade.strategy == "earnings",
            PaperTrade.structure.in_(EQUITY_STRUCTURES),
            PaperTrade.status.in_(OPEN_STATES),
        )
    ).all()
    open_n = len(open_positions)
    # Seed the per-sector tally from what's already on the book so the cap holds
    # across cron runs, not just within a single scan.
    sector_counts: dict[str, int] = {}
    if settings.paper_earnings_equity_max_per_sector > 0 and open_positions:
        sectors = {
            c.ticker: (c.sector or "unknown")
            for c in db.scalars(
                select(Company).where(
                    Company.ticker.in_({t.ticker for t in open_positions})
                )
            ).all()
        }
        for t in open_positions:
            sec = sectors.get(t.ticker, "unknown")
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

    events = db.scalars(
        select(EarningsEvent)
        .where(EarningsEvent.date >= today, EarningsEvent.date <= window_end)
        .order_by(EarningsEvent.date.asc())
    ).all()

    opened = 0
    skipped: list[dict] = []
    seen: set[str] = set()
    for ev in events:
        ticker = ev.ticker
        if ticker in seen:
            continue
        seen.add(ticker)

        if open_n + opened >= settings.paper_earnings_equity_max_open:
            skipped.append(
                {"ticker": ticker, "reason": "max open earnings-equity positions"}
            )
            continue

        # One equity position per (ticker, earnings_date).
        existing = db.scalars(
            select(PaperTrade).where(
                PaperTrade.ticker == ticker,
                PaperTrade.earnings_date == ev.date,
                PaperTrade.strategy == "earnings",
                PaperTrade.structure.in_(EQUITY_STRUCTURES),
            )
        ).first()
        if existing:
            continue

        detail = company_detail(db, ticker)
        pb = (detail or {}).get("playbook")
        if not pb:
            skipped.append({"ticker": ticker, "reason": "no playbook"})
            continue
        direction = pb.get("direction")
        if direction not in ("bullish", "bearish"):
            # Neutral names (iron condors) get no equity leg.
            reason = f"not directional ({direction})"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="earnings_equity", ticker=ticker, decision="skipped",
                earnings_date=ev.date, skip_reason=reason, regime=regime,
                features=earnings_features(pb, equity=equity),
            )
            continue
        conviction = pb.get("conviction")
        if conviction != "high":
            # Only the strongest directional reads earn an outright share bet;
            # everything else is noise (or belongs to the waves sympathy book).
            reason = f"conviction not high ({conviction})"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="earnings_equity", ticker=ticker, decision="skipped",
                earnings_date=ev.date, skip_reason=reason, regime=regime,
                features=earnings_features(pb, equity=equity),
            )
            continue

        # Per-sector cap: take only a couple of names from any one sector so a
        # single sector's earnings week can't flood the book with one correlated
        # bet; the waves strategy rides the rest of the sector sympathy.
        cap_per_sector = settings.paper_earnings_equity_max_per_sector
        if cap_per_sector > 0:
            company = db.get(Company, ticker.upper())
            sector = (company.sector if company else None) or "unknown"
            if sector_counts.get(sector, 0) >= cap_per_sector:
                skipped.append(
                    {"ticker": ticker, "reason": f"sector cap reached ({sector})"}
                )
                continue
        else:
            sector = None

        im = (detail or {}).get("implied_move") or {}
        spot = im.get("underlying_price") or pb.get("spot") or client.stock_price(ticker)
        if not spot or spot <= 0:
            skipped.append({"ticker": ticker, "reason": "no spot price"})
            continue

        # Twin sizing when a real options spread for this event is on the book
        # (opened cleanly, not flagged a bad fill); otherwise the conviction
        # budget the options scan would have risked.
        opt = db.scalars(
            select(PaperTrade).where(
                PaperTrade.ticker == ticker,
                PaperTrade.earnings_date == ev.date,
                PaperTrade.strategy == "earnings",
                PaperTrade.structure.not_in(EQUITY_STRUCTURES),
                PaperTrade.status.in_(OPEN_STATES),
            )
        ).first()
        twin_of = None
        if (
            opt is not None
            and opt.status == "open"
            and opt.max_risk
            and not (opt.note or "").startswith(_BAD_FILL_PREFIX)
        ):
            notional = opt.max_risk
            twin_of = opt.signal_id
        else:
            risk_frac = settings.paper_risk_fraction(pb["conviction"])
            notional = equity * risk_frac

        shares = _earnings_equity_shares(notional, spot)
        if shares < 1:
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": f"notional ${notional:.0f} < 1 share @ ${spot:.2f}",
                }
            )
            continue

        trade = _record_earnings_equity_trade(
            db, ticker, ev, pb, spot, shares, notional, equity, twin_of,
            expected_move_pct=im.get("expected_move_pct"),
        )
        feats = earnings_features(pb, im, equity=equity)
        feats.update({
            "structure": trade.structure,
            "contracts": shares,
            "max_risk": round(notional, 2),
            "spot": round(spot, 2),
            "modeled_price": round(spot, 2),
        })
        feats, _gate_p, model_skip = _score_setup(
            db, ticker, feats, "earnings_equity", model, calib, settings,
        )
        if model_skip:
            trade.status = "canceled"
            trade.note = f"skipped: {model_skip}"
            skipped.append({"ticker": ticker, "reason": model_skip})
            record_decision(
                db, strategy="earnings_equity", ticker=ticker, decision="skipped",
                earnings_date=ev.date, skip_reason=model_skip, regime=regime,
                features=feats,
            )
            continue
        side = "buy" if direction == "bullish" else "sell"
        if dry_run:
            logger.info(
                "[dry-run] EARNINGS-EQ %s %s %d shares @ ~%.2f (%s, %s, risk $%.0f)",
                ticker, side, shares, spot, "twin" if twin_of else "standalone",
                pb["conviction"], notional,
            )
            trade.note = "dry-run (not submitted)"
            record_decision(
                db, strategy="earnings_equity", ticker=ticker, decision="opened",
                earnings_date=ev.date, signal_id=trade.signal_id, regime=regime,
                features=feats,
            )
            opened += 1
            if sector:
                sector_counts[sector] = sector_counts.get(sector, 0) + 1
            continue

        try:
            order = client.submit_stock_order(
                symbol=ticker, qty=shares, side=side, client_order_id=trade.signal_id,
            )
        except AlpacaError as e:
            logger.error("Earnings equity failed for %s: %s", ticker, e)
            trade.status = "canceled"
            trade.note = f"submit error: {e}"[:500]
            skipped.append({"ticker": ticker, "reason": f"submit error: {e}"})
            record_decision(
                db, strategy="earnings_equity", ticker=ticker, decision="skipped",
                earnings_date=ev.date, skip_reason=f"submit error: {e}", regime=regime,
                features=feats,
            )
            continue
        trade.entry_order_id = order.get("id")
        _apply_entry_fill(trade, order)
        record_decision(
            db, strategy="earnings_equity", ticker=ticker, decision="opened",
            earnings_date=ev.date, signal_id=trade.signal_id, regime=regime,
            features=feats,
        )
        opened += 1
        if sector:
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

    if not dry_run:
        db.commit()
    return opened, skipped


def _record_earnings_equity_trade(
    db: Session,
    ticker: str,
    ev: EarningsEvent,
    pb: dict,
    spot: float,
    shares: int,
    notional: float,
    equity: float | None,
    twin_of: str | None,
    expected_move_pct: float | None = None,
) -> PaperTrade:
    signal_id = _next_earnings_equity_signal_id(db)
    bullish = pb.get("direction") == "bullish"
    structure = EQUITY_LONG if bullish else EQUITY_SHORT
    thesis = {
        "instrument": "equity",
        "headline": pb.get("headline"),
        "bias_reasons": pb.get("bias_reasons"),
        "conviction_basis": pb.get("conviction_basis"),
        "sizing": "twin" if twin_of else "standalone",
        "twin_of": twin_of,
    }
    trade = PaperTrade(
        signal_id=signal_id,
        strategy="earnings",
        ticker=ticker,
        earnings_date=ev.date,
        structure=structure,
        direction=pb["direction"],
        vol_stance=pb.get("vol_stance") or "neutral",
        conviction=pb["conviction"],
        thesis=json.dumps(thesis)[:2048],
        status="pending",
        legs=None,
        contracts=shares,
        expiration=None,
        width=None,
        entry_credit=round(spot, 2),      # price per share (provisional; fill overrides)
        modeled_credit=round(spot, 2),
        max_risk=round(notional, 2),
        expected_move_pct=expected_move_pct,
        spot_entry=round(spot, 2),
        equity_at_entry=round(equity, 2) if equity else None,
    )
    db.add(trade)
    db.flush()
    return trade


def _next_earnings_equity_signal_id(db: Session) -> str:
    stamp = date.today().strftime("%Y%m%d")
    prefix = f"EE-{stamp}-"
    n = len(
        db.scalars(
            select(PaperTrade).where(PaperTrade.signal_id.like(f"{prefix}%"))
        ).all()
    )
    return f"{prefix}{n + 1:03d}"


def _manage_earnings_equity_exits(
    db: Session, client: AlpacaClient, settings, dry_run: bool, tp_pct: float
) -> int:
    """Close open earnings-equity positions: the planned post-earnings harvest
    (mirrors the options IV-crush close so the A/B shares a lifecycle), a %-move
    take-profit/stop on the underlying (the pre/at-print guardrail), and the
    force-close / bad-fill escape hatches."""
    today = date.today()
    closed = 0
    trades = db.scalars(
        select(PaperTrade).where(
            PaperTrade.strategy == "earnings",
            PaperTrade.structure.in_(EQUITY_STRUCTURES),
            PaperTrade.status == "open",
        )
    ).all()
    for t in trades:
        spot_now = client.stock_price(t.ticker)
        if not spot_now:
            continue
        reason = _earnings_equity_exit_reason(t, spot_now, today, settings, tp_pct)
        if reason is None:
            continue
        if dry_run:
            logger.info(
                "[dry-run] would close earnings-eq %s (%s) at %.2f",
                t.signal_id, reason, spot_now,
            )
            continue
        # Close = the opposite side (sell a long, buy back a short).
        side = "sell" if t.structure == EQUITY_LONG else "buy"
        try:
            order = client.submit_stock_order(
                symbol=t.ticker, qty=t.contracts or 1, side=side,
                client_order_id=_close_client_order_id(t.signal_id),
            )
        except AlpacaError as e:
            logger.error("Earnings equity close failed for %s: %s", t.signal_id, e)
            continue
        t.exit_order_id = order.get("id")
        t.exit_debit = round(spot_now, 2)  # price per share on close (provisional)
        t.status = "closing"
        t.note = reason
        t.spot_at_exit = round(spot_now, 2)
        entry_px = t.entry_credit or t.spot_entry
        if entry_px:
            t.realized_move_pct = round(spot_now / entry_px - 1, 4)
        _finalize_pnl(t)
        closed += 1
    if not dry_run:
        db.commit()
    return closed


def _earnings_equity_exit_reason(
    t: PaperTrade, spot_now: float, today: date, settings, tp_pct: float
) -> str | None:
    # Operational escape hatches first (shared with the options manager).
    if t.signal_id in settings.paper_force_close_id_set:
        return "manual close"
    if (t.note or "").startswith(_BAD_FILL_PREFIX):
        return "flatten: bad entry fill"
    # Earnings stock uses its own 10%/7% band. The global learned clip (default
    # 3%, band 1.5–8%) was fit on retired debit rides and would bank a print
    # move this sleeve is supposed to hold.
    # Underlying-move take-profit / stop (guardrail before and through the print).
    # Anchor to the real fill (entry_credit); spot_entry may be a stale pre-fill
    # estimate for positions opened before this reference was corrected.
    entry_px = t.entry_credit or t.spot_entry
    if entry_px:
        move = spot_now / entry_px - 1.0  # signed move since entry
        tp = settings.paper_earnings_equity_take_profit_pct
        sl = settings.paper_earnings_equity_stop_pct
        if t.structure == EQUITY_LONG:
            if move >= tp:
                return f"take-profit ({move:+.1%})"
            if move <= -sl:
                return f"stop ({move:+.1%})"
        else:  # short: profits when the stock falls
            if move <= -tp:
                return f"take-profit ({move:+.1%})"
            if move >= sl:
                return f"stop ({move:+.1%})"
    # Planned harvest: the print has passed. Mirror the options manager and wait
    # until strictly after the earnings date (avoid closing ahead of an after-
    # market report on the day itself).
    if t.earnings_date and t.earnings_date < today:
        return "post-earnings"
    return None


def _scan_reversal_entries(
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool
) -> tuple[int, list]:
    """Long the week's worst S&P 500 names for a fixed 5-session hold.

    Non-overlapping: no new entries while any reversal row is pending/open/closing.
    Does not go through the earnings entry model or fair-trade options gate.
    """
    if not getattr(settings, "paper_reversal_enabled", False):
        return 0, []
    skipped: list[dict] = []
    open_rows = db.scalars(
        select(PaperTrade).where(
            PaperTrade.strategy == REVERSAL_STRATEGY,
            PaperTrade.status.in_(OPEN_STATES),
        )
    ).all()
    holding = bool(open_rows)
    try:
        picks, earn_skip, as_of = rank_live(db, settings)
    except Exception as e:  # noqa: BLE001
        logger.warning("reversal rank failed: %s", e)
        skipped.append({"reason": f"rank failed: {e}"})
        return 0, skipped
    write_watch(
        picks,
        earn_skip,
        as_of=as_of,
        holding=holding,
        note="cohort open" if holding else None,
    )
    if holding:
        skipped.append({"reason": "reversal cohort still open (non-overlapping)"})
        return 0, skipped
    if not picks:
        skipped.append({"reason": "no 5-day-loser candidates after filters"})
        return 0, skipped

    regime = regime_snapshot(settings)
    occupied = {
        t.ticker
        for t in db.scalars(
            select(PaperTrade).where(PaperTrade.status.in_(OPEN_STATES))
        ).all()
    }
    max_open = int(getattr(settings, "paper_reversal_max_open", 5))
    risk_frac = float(getattr(settings, "paper_reversal_risk_frac", 0.02))
    opened = 0
    opened_ids: list[str] = []
    for cand in picks:
        if opened >= max_open:
            break
        if cand.ticker in occupied:
            skipped.append({"ticker": cand.ticker, "reason": "already in another book"})
            continue
        spot = client.stock_price(cand.ticker) or cand.close
        if not spot or spot <= 0:
            skipped.append({"ticker": cand.ticker, "reason": "no spot price"})
            continue
        notional = equity * risk_frac
        shares = _earnings_equity_shares(notional, spot)
        if shares < 1:
            skipped.append(
                {
                    "ticker": cand.ticker,
                    "reason": f"notional ${notional:.0f} < 1 share @ ${spot:.2f}",
                }
            )
            continue
        trade = _record_reversal_trade(db, cand, spot, shares, notional, equity)
        feats = {
            "direction": "bullish",
            "structure": EQUITY_LONG,
            "conviction": "medium",
            "spot": round(spot, 2),
            "contracts": shares,
            "max_risk": round(notional, 2),
            "modeled_price": round(spot, 2),
            "ret_5": round(cand.ret_5, 4),
            "dollar_vol": round(cand.dollar_vol, 0),
            "as_of": cand.as_of.isoformat(),
        }
        if dry_run:
            logger.info(
                "[dry-run] REVERSAL BUY %s %d sh @ ~%.2f (5d %+0.1f%%, risk $%.0f)",
                cand.ticker, shares, spot, cand.ret_5 * 100, notional,
            )
            trade.note = "dry-run (not submitted)"
            record_decision(
                db,
                strategy=REVERSAL_STRATEGY,
                ticker=cand.ticker,
                decision="opened",
                signal_id=trade.signal_id,
                regime=regime,
                features=feats,
            )
            opened += 1
            opened_ids.append(trade.signal_id)
            continue
        try:
            order = client.submit_stock_order(
                symbol=cand.ticker,
                qty=shares,
                side="buy",
                client_order_id=trade.signal_id,
            )
        except AlpacaError as e:
            logger.error("Reversal entry failed for %s: %s", cand.ticker, e)
            trade.status = "canceled"
            trade.note = f"submit error: {e}"[:500]
            skipped.append({"ticker": cand.ticker, "reason": f"submit error: {e}"})
            record_decision(
                db,
                strategy=REVERSAL_STRATEGY,
                ticker=cand.ticker,
                decision="skipped",
                skip_reason=f"submit error: {e}",
                regime=regime,
                features=feats,
            )
            continue
        trade.entry_order_id = order.get("id")
        _apply_entry_fill(trade, order)
        record_decision(
            db,
            strategy=REVERSAL_STRATEGY,
            ticker=cand.ticker,
            decision="opened",
            signal_id=trade.signal_id,
            regime=regime,
            features=feats,
        )
        opened += 1
        opened_ids.append(trade.signal_id)
        occupied.add(cand.ticker)
    write_watch(
        picks,
        earn_skip,
        as_of=as_of,
        holding=bool(opened_ids) or holding,
        opened=opened_ids,
    )
    if not dry_run:
        db.commit()
    return opened, skipped


def _record_reversal_trade(
    db: Session,
    cand,
    spot: float,
    shares: int,
    notional: float,
    equity: float | None,
) -> PaperTrade:
    signal_id = _next_reversal_signal_id(db)
    thesis = {
        "instrument": "equity",
        "headline": (
            f"5-day loser · {cand.ret_5:+.1%} over 5 sessions through "
            f"{cand.as_of.isoformat()}, hold 5 sessions or +10%"
        ),
        "ret_5": round(cand.ret_5, 4),
        "as_of": cand.as_of.isoformat(),
        "dollar_vol": round(cand.dollar_vol, 0),
        "lookback_days": 5,
        "hold_days": 5,
    }
    trade = PaperTrade(
        signal_id=signal_id,
        strategy=REVERSAL_STRATEGY,
        ticker=cand.ticker,
        earnings_date=None,
        structure=EQUITY_LONG,
        direction="bullish",
        vol_stance="neutral",
        conviction="medium",
        thesis=json.dumps(thesis)[:2048],
        status="pending",
        legs=None,
        contracts=shares,
        expiration=None,
        width=None,
        entry_credit=round(spot, 2),
        modeled_credit=round(spot, 2),
        max_risk=round(notional, 2),
        expected_move_pct=round(cand.ret_5, 4),
        spot_entry=round(spot, 2),
        equity_at_entry=round(equity, 2) if equity else None,
    )
    db.add(trade)
    db.flush()
    return trade


def _next_reversal_signal_id(db: Session) -> str:
    stamp = date.today().strftime("%Y%m%d")
    prefix = f"RV-{stamp}-"
    n = len(
        db.scalars(
            select(PaperTrade).where(PaperTrade.signal_id.like(f"{prefix}%"))
        ).all()
    )
    return f"{prefix}{n + 1:03d}"


def _manage_reversal_exits(
    db: Session, client: AlpacaClient, settings, dry_run: bool
) -> int:
    """Close reversal longs on +10% take-profit, the 5-session hold, or force-close."""
    today = date.today()
    closed = 0
    trades = db.scalars(
        select(PaperTrade).where(
            PaperTrade.strategy == REVERSAL_STRATEGY,
            PaperTrade.status == "open",
        )
    ).all()
    earn_hits: set[str] = set()
    if trades:
        try:
            earn_hits = tickers_in_earn_buffer(
                db,
                {t.ticker for t in trades},
                today,
                int(getattr(settings, "paper_reversal_earn_buffer_days", 5)),
            )
        except Exception as e:  # noqa: BLE001 - never skip TP/hold because the calendar failed
            logger.warning("reversal earn-window flatten check failed: %s", e)
    for t in trades:
        spot_now = client.stock_price(t.ticker)
        if not spot_now:
            continue
        reason = reversal_exit_reason(
            t, today, settings, spot_now,
            in_earn_window=t.ticker in earn_hits,
        )
        if reason is None:
            continue
        if dry_run:
            logger.info(
                "[dry-run] would close reversal %s (%s) at %.2f",
                t.signal_id, reason, spot_now,
            )
            continue
        try:
            order = client.submit_stock_order(
                symbol=t.ticker,
                qty=t.contracts or 1,
                side="sell",
                client_order_id=_close_client_order_id(t.signal_id),
            )
        except AlpacaError as e:
            logger.error("Reversal close failed for %s: %s", t.signal_id, e)
            continue
        t.exit_order_id = order.get("id")
        t.exit_debit = round(spot_now, 2)
        t.status = "closing"
        t.note = reason
        t.spot_at_exit = round(spot_now, 2)
        entry_px = t.entry_credit or t.spot_entry
        if entry_px:
            t.realized_move_pct = round(spot_now / entry_px - 1, 4)
        _finalize_pnl(t)
        closed += 1
    if not dry_run:
        db.commit()
    return closed


# --- waves strategy ----------------------------------------------------------


def _parse_iso(value) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _manage_wave_exits(
    db: Session, client: AlpacaClient, settings, dry_run: bool, tp_pct: float
) -> int:
    """Close open wave trades on the fixed short hold, the underlying-move
    bracket, or (as a safety) the day before the target's own print."""
    today = date.today()
    closed = 0
    trades = db.scalars(
        select(PaperTrade).where(
            PaperTrade.strategy == "waves", PaperTrade.status == "open"
        )
    ).all()
    for t in trades:
        legs = json.loads(t.legs or "[]")
        if len(legs) < 2:
            continue
        symbols = [l["symbol"] for l in legs]
        spot_now = client.stock_price(t.ticker)
        reason = _wave_exit_reason(t, spot_now, today, settings, tp_pct)
        if reason is None:
            continue
        quotes = client.option_quotes(symbols)
        if any((quotes.get(s, {}).get("mid") or 0) <= 0 for s in symbols):
            continue  # can't price the close right now; retry next run
        # Value of the long debit spread = long leg mid - short leg mid.
        exit_value = round(
            sum(quotes[l["symbol"]]["mid"] for l in legs if l["side"] == "buy")
            - sum(quotes[l["symbol"]]["mid"] for l in legs if l["side"] == "sell"),
            2,
        )
        # Close = sell the long leg, buy back the short leg.
        close_legs = [
            {
                "symbol": l["symbol"],
                "ratio_qty": "1",
                "side": "buy" if l["side"] == "sell" else "sell",
                "position_intent": "buy_to_close"
                if l["side"] == "sell"
                else "sell_to_close",
            }
            for l in legs
        ]
        if dry_run:
            logger.info(
                "[dry-run] would close wave %s (%s) at %.2f", t.signal_id, reason, exit_value
            )
            continue
        try:
            order = _submit_spread_close(
                client, close_legs, t.contracts or 1, t.signal_id,
                is_credit=True, mid=exit_value, urgent=_exit_is_urgent(reason),
                settings=settings, quotes=quotes,
                min_credit=_spread_intrinsic(legs, spot_now),
            )
        except AlpacaError as e:
            logger.error("Wave close failed for %s: %s", t.signal_id, e)
            continue
        t.exit_order_id = order.get("id")
        t.exit_debit = exit_value  # proceeds per share on close
        t.status = "closing"
        t.note = reason
        if spot_now:
            t.spot_at_exit = round(spot_now, 2)
            if t.spot_entry:
                t.realized_move_pct = round(spot_now / t.spot_entry - 1, 4)
        _finalize_pnl(t)
        closed += 1
    if not dry_run:
        db.commit()
    return closed


def _wave_exit_reason(
    t: PaperTrade, spot_now: float | None, today: date, settings, tp_pct: float
) -> str | None:
    # Global learned take-profit first (tighter than the book's own gain band).
    tp = _underlying_take_profit(t, spot_now, settings, tp_pct)
    if tp is not None:
        return tp
    # Fixed short hold: the sympathy pop is a few-day move - take it and leave.
    if t.opened_at and (today - t.opened_at.date()).days >= settings.paper_wave_hold_days:
        return "hold window elapsed"
    # Safety: never ride a directional sympathy trade into the target's OWN print.
    if t.earnings_date and (t.earnings_date - today).days <= 1:
        return "pre-earnings exit"
    if spot_now and t.spot_entry:
        move = spot_now / t.spot_entry - 1.0
        favorable = move if t.direction == "bullish" else -move
        if favorable >= settings.paper_wave_gain_pct:
            return f"take-profit (+{favorable:.1%} underlying)"
        if favorable <= -settings.paper_wave_loss_pct:
            return f"stop-loss ({favorable:.1%} underlying)"
    return None


def _scan_wave_entries(
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool,
    calib: dict | None = None,
    model=None,
) -> tuple[int, list]:
    if not settings.paper_waves_enabled:
        logger.info("waves scan: disabled (paper_waves_enabled=False)")
        return 0, []
    today = date.today()
    regime = regime_snapshot(settings)
    try:
        signals = current_sympathy_waves(
            db,
            trigger_max_age_days=settings.paper_wave_trigger_max_age_days,
            min_trigger_move=settings.paper_wave_min_trigger_move,
            hold_days=settings.paper_wave_hist_hold_days,
        )
    except Exception as e:  # noqa: BLE001 - never let a signal error break the run
        logger.warning("waves signal build failed: %s", e)
        return 0, []

    open_n = len(
        db.scalars(
            select(PaperTrade).where(
                PaperTrade.strategy == "waves",
                PaperTrade.status.in_(OPEN_STATES),
            )
        ).all()
    )

    opened = 0
    skipped: list[dict] = []
    seen: set[str] = set()
    for sig in signals:
        target = sig.get("target")
        if not target or target in seen:
            continue
        seen.add(target)

        if open_n + opened >= settings.paper_wave_max_open:
            skipped.append({"ticker": target, "reason": "max open wave positions"})
            continue

        stats = sig.get("stats") or {}
        wr, n = stats.get("win_rate"), stats.get("sample_size")
        sig_date = _parse_iso(sig.get("target_report_date"))
        if wr is None or wr < settings.paper_wave_min_winrate:
            reason = f"win rate too low ({wr})"
            skipped.append({"ticker": target, "reason": reason})
            record_decision(
                db, strategy="waves", ticker=target, decision="skipped",
                earnings_date=sig_date, skip_reason=reason, regime=regime,
                features=wave_features(sig, conviction=wave_conviction(sig), equity=equity),
            )
            continue
        if n is None or n < settings.paper_wave_min_samples:
            reason = f"too few samples ({n})"
            skipped.append({"ticker": target, "reason": reason})
            record_decision(
                db, strategy="waves", ticker=target, decision="skipped",
                earnings_date=sig_date, skip_reason=reason, regime=regime,
                features=wave_features(sig, conviction=wave_conviction(sig), equity=equity),
            )
            continue

        # The catalyst is the peer's print, not the target's - so the target's
        # own earnings date no longer gates entry. But we won't hold a directional
        # trade INTO the target's own report, so skip if it lands inside the hold.
        tgt_date = _parse_iso(sig.get("target_report_date"))
        if tgt_date is not None:
            days_to_print = (tgt_date - today).days
            horizon = settings.paper_wave_hold_days + settings.paper_wave_avoid_earnings_within_days
            if 0 <= days_to_print <= horizon:
                skipped.append(
                    {"ticker": target, "reason": f"own print inside the hold ({days_to_print}d)"}
                )
                continue

        # One attempt per ticker: an already-closed wave still blocks re-entry
        # for a cooldown so we don't buy back the same name the day after a dump
        # (APTV Aug 20 close / Aug 21 reopen).
        cooldown = datetime.utcnow() - timedelta(days=settings.paper_wave_hold_days + 7)
        existing = db.scalars(
            select(PaperTrade).where(
                PaperTrade.ticker == target,
                PaperTrade.strategy == "waves",
                PaperTrade.status.in_(OPEN_STATES + ("closed",)),
            )
        ).first()
        if existing and (
            existing.status in OPEN_STATES
            or (existing.opened_at and existing.opened_at >= cooldown)
        ):
            logger.info(
                "waves scan: %s already has a %s wave trade; skipping",
                target, existing.status,
            )
            continue

        budget = equity * settings.paper_wave_risk_frac
        conv = wave_conviction(sig)
        spec, reason = build_wave_spec(
            client, sig, risk_budget=budget,
            min_dte=settings.paper_wave_min_dte,
            max_dte=settings.paper_wave_max_dte,
        )
        if spec is None:
            skipped.append({"ticker": target, "reason": reason})
            record_decision(
                db, strategy="waves", ticker=target, decision="skipped",
                earnings_date=tgt_date, skip_reason=reason, regime=regime,
                features=wave_features(
                    sig, conviction=conv, risk_frac=settings.paper_wave_risk_frac,
                    equity=equity,
                ),
            )
            continue

        per_contract = spec.net_debit * 100
        contracts = int(budget // per_contract) if per_contract > 0 else 0
        contracts = min(contracts, settings.paper_max_contracts)
        if contracts < 1:
            reason = f"debit too rich (${per_contract:.0f}/ct vs ${budget:.0f})"
            skipped.append({"ticker": target, "reason": reason})
            record_decision(
                db, strategy="waves", ticker=target, decision="skipped",
                earnings_date=tgt_date, skip_reason=reason, regime=regime,
                features=wave_features(
                    sig, conviction=conv, spec=spec,
                    risk_frac=settings.paper_wave_risk_frac, equity=equity,
                ),
            )
            continue

        trade = _record_wave_trade(db, sig, spec, tgt_date, contracts, equity)
        feats = wave_features(
            sig, conviction=conv, spec=spec, contracts=contracts,
            risk_frac=settings.paper_wave_risk_frac, equity=equity,
        )
        feats, win_prob, model_skip = _score_setup(
            db, target, feats, "waves", model, calib, settings,
        )
        if model_skip:
            trade.status = "canceled"
            trade.note = f"skipped: {model_skip}"
            skipped.append({"ticker": target, "reason": model_skip})
            record_decision(
                db, strategy="waves", ticker=target, decision="skipped",
                earnings_date=tgt_date, skip_reason=model_skip, regime=regime,
                features=feats,
            )
            continue
        if dry_run:
            logger.info(
                "[dry-run] WAVE %s %s spread x%d @ debit %.2f (trigger %s)",
                target, spec.option_type, contracts, spec.net_debit, sig.get("trigger"),
            )
            trade.note = "dry-run (not submitted)"
            record_decision(
                db, strategy="waves", ticker=target, decision="opened",
                earnings_date=tgt_date, signal_id=trade.signal_id, regime=regime,
                features=feats,
            )
            opened += 1
            continue

        order_legs = [
            {
                "symbol": l.symbol,
                "ratio_qty": "1",
                "side": l.side,
                "position_intent": l.position_intent,
            }
            for l in spec.legs
        ]
        # wr is the historical sympathy win rate gated above. The entry model
        # jointly reweights it with size / implied vol when live; otherwise the
        # calibrated historical rate feeds the EV gate.
        limit, reason = _gate_entry(
            client, order_legs, is_credit=False, mid=spec.net_debit,
            width=spec.width, win_prob=win_prob, settings=settings,
        )
        if limit is None:
            trade.status = "canceled"
            trade.note = f"skipped: {reason}"
            skipped.append({"ticker": target, "reason": reason})
            record_decision(
                db, strategy="waves", ticker=target, decision="skipped",
                earnings_date=tgt_date, skip_reason=reason, regime=regime,
                features=feats,
            )
            continue
        try:
            order = client.submit_mleg(
                legs=order_legs,
                qty=contracts,
                limit_price=limit,
                client_order_id=trade.signal_id,
            )
        except AlpacaError as e:
            logger.error("Wave order failed for %s: %s", target, e)
            trade.status = "canceled"
            trade.note = f"submit error: {e}"[:500]
            skipped.append({"ticker": target, "reason": f"submit error: {e}"})
            record_decision(
                db, strategy="waves", ticker=target, decision="skipped",
                earnings_date=tgt_date, skip_reason=f"submit error: {e}", regime=regime,
                features=feats,
            )
            continue
        trade.entry_order_id = order.get("id")
        _apply_entry_fill(trade, order)
        record_decision(
            db, strategy="waves", ticker=target, decision="opened",
            earnings_date=tgt_date, signal_id=trade.signal_id, regime=regime,
            features=feats,
        )
        opened += 1

    if not dry_run:
        db.commit()
    return opened, skipped


def _record_wave_trade(
    db: Session,
    sig: dict,
    spec: WaveSpec,
    tgt_date: date | None,
    contracts: int,
    equity: float | None,
) -> PaperTrade:
    signal_id = _next_wave_signal_id(db)
    direction = sig.get("direction") or (
        "bullish" if spec.option_type == "call" else "bearish"
    )
    stats = sig.get("stats") or {}
    thesis = {
        "trigger": sig.get("trigger"),
        "trigger_move_pct": sig.get("trigger_move_pct"),
        "expected_runup_pct": sig.get("expected_runup_pct"),
        "win_rate": stats.get("win_rate"),
        "samples": stats.get("sample_size"),
        "target_report_date": sig.get("target_report_date"),
    }
    legs_json = json.dumps(
        [
            {
                "symbol": l.symbol,
                "type": l.option_type,
                "side": l.side,
                "strike": l.strike,
                "mid": l.mid,
            }
            for l in spec.legs
        ]
    )
    long = spec.option_type == "call"
    trade = PaperTrade(
        signal_id=signal_id,
        strategy="waves",
        ticker=sig["target"],
        earnings_date=tgt_date,
        structure="Bull call spread" if long else "Bear put spread",
        direction=direction,
        vol_stance="buy",
        conviction=wave_conviction(sig),
        thesis=json.dumps(thesis)[:2048],
        status="pending",
        legs=legs_json[:2048],
        contracts=contracts,
        expiration=spec.expiration,
        width=spec.width,
        entry_credit=spec.net_debit,  # debit paid (max loss) per share
        modeled_credit=spec.net_debit,
        max_risk=round(spec.net_debit * 100 * contracts, 2),
        spot_entry=spec.spot,
        equity_at_entry=round(equity, 2) if equity else None,
    )
    db.add(trade)
    db.flush()
    return trade


def _next_wave_signal_id(db: Session) -> str:
    stamp = date.today().strftime("%Y%m%d")
    prefix = f"WV-{stamp}-"
    n = len(
        db.scalars(
            select(PaperTrade).where(PaperTrade.signal_id.like(f"{prefix}%"))
        ).all()
    )
    return f"{prefix}{n + 1:03d}"


# --- drift (PEAD) strategy ---------------------------------------------------


def _manage_drift_exits(
    db: Session, client: AlpacaClient, settings, dry_run: bool, tp_pct: float
) -> int:
    """Close open drift debit spreads on a time horizon (the drift window has
    elapsed), a take-profit (spread near its max width), or a broken-thesis stop
    (underlying gave back the post-earnings move)."""
    today = date.today()
    closed = 0
    trades = db.scalars(
        select(PaperTrade).where(
            PaperTrade.strategy == "drift", PaperTrade.status == "open"
        )
    ).all()
    for t in trades:
        legs = json.loads(t.legs or "[]")
        if len(legs) < 2:
            continue
        symbols = [l["symbol"] for l in legs]
        quotes = client.option_quotes(symbols)
        if any((quotes.get(s, {}).get("mid") or 0) <= 0 for s in symbols):
            continue  # can't price the close right now; retry next run
        # Value of our long debit spread = long leg mid - short leg mid.
        exit_value = round(
            sum(quotes[l["symbol"]]["mid"] for l in legs if l["side"] == "buy")
            - sum(quotes[l["symbol"]]["mid"] for l in legs if l["side"] == "sell"),
            2,
        )
        spot_now = client.stock_price(t.ticker)
        reason = _drift_exit_reason(t, spot_now, exit_value, today, settings, tp_pct)
        if reason is None:
            continue

        # Close = sell the long leg, buy back the short leg.
        close_legs = [
            {
                "symbol": l["symbol"],
                "ratio_qty": "1",
                "side": "buy" if l["side"] == "sell" else "sell",
                "position_intent": "buy_to_close"
                if l["side"] == "sell"
                else "sell_to_close",
            }
            for l in legs
        ]
        if dry_run:
            logger.info(
                "[dry-run] would close drift %s (%s) at %.2f", t.signal_id, reason, exit_value
            )
            continue
        try:
            order = _submit_spread_close(
                client, close_legs, t.contracts or 1, t.signal_id,
                is_credit=True, mid=exit_value, urgent=_exit_is_urgent(reason),
                settings=settings, quotes=quotes,
                min_credit=_spread_intrinsic(legs, spot_now),
            )
        except AlpacaError as e:
            logger.error("Drift close failed for %s: %s", t.signal_id, e)
            continue
        t.exit_order_id = order.get("id")
        t.exit_debit = exit_value  # proceeds per share on close
        t.status = "closing"
        t.note = reason
        if spot_now:
            t.spot_at_exit = round(spot_now, 2)
            if t.spot_entry:
                t.realized_move_pct = round(spot_now / t.spot_entry - 1, 4)
        _finalize_pnl(t)
        closed += 1
    if not dry_run:
        db.commit()
    return closed


def _drift_exit_reason(
    t: PaperTrade, spot_now: float | None, exit_value: float, today: date,
    settings, tp_pct: float,
) -> str | None:
    # Global learned take-profit on the underlying move - drift otherwise has no
    # upside exit but the time/width ones, which let winners round-trip.
    tp = _underlying_take_profit(t, spot_now, settings, tp_pct)
    if tp is not None:
        return tp
    # Time exit: the drift window the edge is measured over has elapsed.
    if t.earnings_date and (today - t.earnings_date).days >= settings.paper_drift_hold_days:
        return "drift window elapsed"
    # Take-profit: the spread is worth most of its max width.
    if t.width and exit_value >= settings.paper_drift_take_profit * t.width:
        return f"take-profit ({exit_value / t.width:.0%} of width)"
    # Stop: underlying gave back the post-earnings move (broken thesis). Two
    # guards stop this from whipsawing a fresh entry to a loss (what churned
    # JEF/WOR): (1) don't stop on the entry day - give the thesis a session, and
    # (2) require the price to be a buffer *beyond* the pivot, not just grazing
    # it, so intraday noise around the level doesn't trigger.
    if t.opened_at and t.opened_at.date() >= today:
        return None
    try:
        stop = (json.loads(t.thesis or "{}") or {}).get("stop_level")
    except json.JSONDecodeError:
        stop = None
    if stop and spot_now:
        long = t.direction == "bullish"
        buf = settings.paper_drift_stop_buffer
        if long and spot_now < stop * (1 - buf):
            return "stop (gave back the move)"
        if not long and spot_now > stop * (1 + buf):
            return "stop (gave back the move)"
    return None


def _scan_drift_entries(
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool,
    calib: dict | None = None,
    model=None,
) -> tuple[int, list]:
    if not settings.paper_drift_enabled:
        logger.info("drift scan: disabled (paper_drift_enabled=False)")
        return 0, []
    regime = regime_snapshot(settings)
    try:
        from app.services.drift import drift_setups

        setups, _has_more = drift_setups(db)
    except Exception as e:  # noqa: BLE001 - never let a signal error break the run
        logger.warning("drift signal build failed: %s", e)
        return 0, []
    logger.info(
        "drift scan: %d setup(s): %s",
        len(setups),
        ", ".join(f"{s.get('ticker')}({s.get('direction')})" for s in setups) or "none",
    )

    open_n = len(
        db.scalars(
            select(PaperTrade).where(
                PaperTrade.strategy == "drift",
                PaperTrade.status.in_(OPEN_STATES),
            )
        ).all()
    )

    opened = 0
    skipped: list[dict] = []
    seen: set[str] = set()
    for setup in setups:
        ticker = setup.get("ticker")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)

        setup_date = _parse_iso(setup.get("report_date"))
        if open_n + opened >= settings.paper_drift_max_open:
            skipped.append({"ticker": ticker, "reason": "max open drift positions"})
            continue
        if (setup.get("plan") or {}).get("entry_quality") == "late":
            reason = "late entry (drift window mostly gone)"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="drift", ticker=ticker, decision="skipped",
                earnings_date=setup_date, skip_reason=reason, regime=regime,
                features=drift_features(
                    setup, conviction=drift_conviction(setup),
                    risk_frac=settings.paper_drift_risk_frac, equity=equity,
                ),
            )
            continue
        if (setup.get("score") or 0) < settings.paper_drift_min_score:
            reason = f"score below floor ({setup.get('score')})"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="drift", ticker=ticker, decision="skipped",
                earnings_date=setup_date, skip_reason=reason, regime=regime,
                features=drift_features(
                    setup, conviction=drift_conviction(setup),
                    risk_frac=settings.paper_drift_risk_frac, equity=equity,
                ),
            )
            continue

        report_date = _parse_iso(setup.get("report_date"))
        if report_date is None:
            continue
        # Only a real position (active or already closed) should block a retry.
        # A failed/canceled submission must NOT permanently lock the ticker out.
        existing = db.scalars(
            select(PaperTrade).where(
                PaperTrade.ticker == ticker,
                PaperTrade.earnings_date == report_date,
                PaperTrade.strategy == "drift",
                PaperTrade.status.in_(OPEN_STATES + ("closed",)),
            )
        ).first()
        if existing:
            logger.info(
                "drift scan: %s already has a %s drift trade; skipping",
                ticker, existing.status,
            )
            continue

        budget = equity * settings.paper_drift_risk_frac
        conv = drift_conviction(setup)
        spec, reason = build_drift_spec(client, setup, risk_budget=budget)
        if spec is None:
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="drift", ticker=ticker, decision="skipped",
                earnings_date=report_date, skip_reason=reason, regime=regime,
                features=drift_features(
                    setup, conviction=conv,
                    risk_frac=settings.paper_drift_risk_frac, equity=equity,
                ),
            )
            continue

        per_contract = spec.net_debit * 100
        contracts = int(budget // per_contract) if per_contract > 0 else 0
        contracts = min(contracts, settings.paper_max_contracts)
        if contracts < 1:
            reason = f"debit too rich (${per_contract:.0f}/ct vs ${budget:.0f})"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="drift", ticker=ticker, decision="skipped",
                earnings_date=report_date, skip_reason=reason, regime=regime,
                features=drift_features(
                    setup, conviction=conv, spec=spec,
                    risk_frac=settings.paper_drift_risk_frac, equity=equity,
                ),
            )
            continue

        trade = _record_drift_trade(db, setup, spec, report_date, contracts, equity)
        feats = drift_features(
            setup, conviction=conv, spec=spec, contracts=contracts,
            risk_frac=settings.paper_drift_risk_frac, equity=equity,
        )
        feats, win_prob, model_skip = _score_setup(
            db, ticker, feats, "drift", model, calib, settings,
        )
        if model_skip:
            trade.status = "canceled"
            trade.note = f"skipped: {model_skip}"
            skipped.append({"ticker": ticker, "reason": model_skip})
            record_decision(
                db, strategy="drift", ticker=ticker, decision="skipped",
                earnings_date=report_date, skip_reason=model_skip, regime=regime,
                features=feats,
            )
            continue
        if dry_run:
            logger.info(
                "[dry-run] DRIFT %s %s spread x%d @ debit %.2f (edge %s)",
                ticker, spec.legs[0].option_type, contracts, spec.net_debit,
                (setup.get("history") or {}).get("avg_drift_5d_pct"),
            )
            trade.note = "dry-run (not submitted)"
            record_decision(
                db, strategy="drift", ticker=ticker, decision="opened",
                earnings_date=report_date, signal_id=trade.signal_id, regime=regime,
                features=feats,
            )
            opened += 1
            continue

        order_legs = [
            {
                "symbol": l.symbol,
                "ratio_qty": "1",
                "side": l.side,
                "position_intent": l.position_intent,
            }
            for l in spec.legs
        ]
        limit, reason = _gate_entry(
            client, order_legs, is_credit=False, mid=spec.net_debit,
            width=spec.width, win_prob=win_prob, settings=settings,
        )
        if limit is None:
            trade.status = "canceled"
            trade.note = f"skipped: {reason}"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="drift", ticker=ticker, decision="skipped",
                earnings_date=report_date, skip_reason=reason, regime=regime,
                features=feats,
            )
            continue
        try:
            order = client.submit_mleg(
                legs=order_legs,
                qty=contracts,
                limit_price=limit,
                client_order_id=trade.signal_id,
            )
        except AlpacaError as e:
            logger.error("Drift order failed for %s: %s", ticker, e)
            trade.status = "canceled"
            trade.note = f"submit error: {e}"[:500]
            skipped.append({"ticker": ticker, "reason": f"submit error: {e}"})
            record_decision(
                db, strategy="drift", ticker=ticker, decision="skipped",
                earnings_date=report_date, skip_reason=f"submit error: {e}", regime=regime,
                features=feats,
            )
            continue
        trade.entry_order_id = order.get("id")
        _apply_entry_fill(trade, order)
        record_decision(
            db, strategy="drift", ticker=ticker, decision="opened",
            earnings_date=report_date, signal_id=trade.signal_id, regime=regime,
            features=feats,
        )
        opened += 1

    if not dry_run:
        db.commit()
    return opened, skipped


def _record_drift_trade(
    db: Session,
    setup: dict,
    spec: DriftSpec,
    report_date: date,
    contracts: int,
    equity: float | None,
) -> PaperTrade:
    signal_id = _next_drift_signal_id(db)
    long = setup.get("direction") == "long"
    history = setup.get("history") or {}
    thesis = {
        "report_date": setup.get("report_date"),
        "surprise_pct": setup.get("surprise_pct"),
        "move_pct": setup.get("move_pct"),
        "edge_5d": history.get("avg_drift_5d_pct"),
        "win_rate": history.get("win_rate_5d"),
        "samples": history.get("sample_size"),
        "stop_level": spec.stop_level,
        "why": (setup.get("why") or [])[:3],
    }
    legs_json = json.dumps(
        [
            {
                "symbol": l.symbol,
                "type": l.option_type,
                "side": l.side,
                "strike": l.strike,
                "mid": l.mid,
            }
            for l in spec.legs
        ]
    )
    trade = PaperTrade(
        signal_id=signal_id,
        strategy="drift",
        ticker=setup["ticker"],
        earnings_date=report_date,
        structure="Bull call spread" if long else "Bear put spread",
        direction="bullish" if long else "bearish",
        vol_stance="buy",
        conviction=drift_conviction(setup),
        thesis=json.dumps(thesis)[:2048],
        status="pending",
        legs=legs_json[:2048],
        contracts=contracts,
        expiration=spec.expiration,
        width=spec.width,
        entry_credit=spec.net_debit,  # debit paid (max loss) per share
        modeled_credit=spec.net_debit,
        max_risk=round(spec.net_debit * 100 * contracts, 2),
        spot_entry=spec.spot,
        equity_at_entry=round(equity, 2) if equity else None,
    )
    db.add(trade)
    db.flush()
    return trade


def _next_drift_signal_id(db: Session) -> str:
    stamp = date.today().strftime("%Y%m%d")
    prefix = f"DR-{stamp}-"
    n = len(
        db.scalars(
            select(PaperTrade).where(PaperTrade.signal_id.like(f"{prefix}%"))
        ).all()
    )
    return f"{prefix}{n + 1:03d}"


# --- reddit (social sentiment) strategy --------------------------------------

_CONVICTION_RANK = {"low": 0, "medium": 1, "high": 2}
_PUMP_RANK = {"low": 0, "medium": 1, "high": 2}
# Reddit has no per-name historical win rate, so we proxy the win probability
# off conviction for the expected-value gate. Deliberately modest -- a directional
# debit bet on hype is roughly a coin flip even when conviction is high -- so the
# EV gate only clears a Reddit spread when the debit leaves plenty of upside.
_REDDIT_WIN_PROB = {"high": 0.55, "medium": 0.50, "low": 0.45}


def _manage_reddit_exits(
    db: Session, client: AlpacaClient, settings, dry_run: bool, tp_pct: float
) -> int:
    """Close open Reddit debit spreads on a tight time horizon (attention fades),
    a take-profit (spread near its max width), a stop (gave back the debit), or a
    sentiment reversal/collapse (the chatter that justified the trade is gone)."""
    today = date.today()
    closed = 0
    trades = db.scalars(
        select(PaperTrade).where(
            PaperTrade.strategy == "reddit", PaperTrade.status == "open"
        )
    ).all()
    for t in trades:
        if _is_equity(t):
            if _manage_one_equity_exit(db, client, t, settings, dry_run, tp_pct):
                closed += 1
            continue
        legs = json.loads(t.legs or "[]")
        if len(legs) < 2:
            continue
        symbols = [l["symbol"] for l in legs]
        quotes = client.option_quotes(symbols)
        if any((quotes.get(s, {}).get("mid") or 0) <= 0 for s in symbols):
            continue  # can't price the close right now; retry next run
        # Value of our long debit spread = long leg mid - short leg mid.
        exit_value = round(
            sum(quotes[l["symbol"]]["mid"] for l in legs if l["side"] == "buy")
            - sum(quotes[l["symbol"]]["mid"] for l in legs if l["side"] == "sell"),
            2,
        )
        spot_now = client.stock_price(t.ticker)
        reason = _reddit_exit_reason(db, t, spot_now, exit_value, today, settings, tp_pct)
        if reason is None:
            continue

        # Close = sell the long leg, buy back the short leg.
        close_legs = [
            {
                "symbol": l["symbol"],
                "ratio_qty": "1",
                "side": "buy" if l["side"] == "sell" else "sell",
                "position_intent": "buy_to_close"
                if l["side"] == "sell"
                else "sell_to_close",
            }
            for l in legs
        ]
        if dry_run:
            logger.info(
                "[dry-run] would close reddit %s (%s) at %.2f",
                t.signal_id, reason, exit_value,
            )
            continue
        try:
            order = _submit_spread_close(
                client, close_legs, t.contracts or 1, t.signal_id,
                is_credit=True, mid=exit_value, urgent=_exit_is_urgent(reason),
                settings=settings, quotes=quotes,
                min_credit=_spread_intrinsic(legs, spot_now),
            )
        except AlpacaError as e:
            logger.error("Reddit close failed for %s: %s", t.signal_id, e)
            continue
        t.exit_order_id = order.get("id")
        t.exit_debit = exit_value  # proceeds per share on close
        t.status = "closing"
        t.note = reason
        if spot_now:
            t.spot_at_exit = round(spot_now, 2)
            if t.spot_entry:
                t.realized_move_pct = round(spot_now / t.spot_entry - 1, 4)
        _finalize_pnl(t)
        closed += 1
    if not dry_run:
        db.commit()
    return closed


def _reddit_exit_reason(
    db: Session, t: PaperTrade, spot_now: float | None, exit_value: float,
    today: date, settings, tp_pct: float,
) -> str | None:
    # Book retired: flatten any leftover open reddit positions on the next run.
    if not settings.paper_reddit_enabled:
        return "strategy retired"

    # Global learned take-profit on the underlying move binds first.
    tp = _underlying_take_profit(t, spot_now, settings, tp_pct)
    if tp is not None:
        return tp
    # Time exit: this is a momentum day-trade - we ride the Reddit wave for only
    # a few hours and never hold overnight. Measured in hours since the fill (the
    # cron's ~30-min cadence is the exit granularity).
    if t.opened_at:
        held_hours = (datetime.utcnow() - t.opened_at).total_seconds() / 3600.0
        if held_hours >= settings.paper_reddit_hold_hours:
            return "hold window elapsed"
    # Take-profit: the spread is worth most of its max width.
    if t.width and exit_value >= settings.paper_reddit_take_profit * t.width:
        return f"take-profit ({exit_value / t.width:.0%} of width)"
    # Stop: the spread has given back a chunk of the debit we paid.
    if t.entry_credit and exit_value <= (1 - settings.paper_reddit_stop_frac) * t.entry_credit:
        return f"stop ({exit_value / t.entry_credit:.0%} of debit left)"
    # Sentiment reversal/collapse: don't whipsaw on the entry day - give the
    # thesis a session - then bail if the freshest signal flipped against us,
    # went quiet (noise), or fell below the velocity floor.
    if t.opened_at and t.opened_at.date() >= today:
        return None
    sig = latest_reddit_signal(db, t.ticker)
    if sig is not None and sig.scan_date >= t.opened_at.date():
        want = "bullish" if t.direction == "bullish" else "bearish"
        if sig.is_noise or sig.direction != want:
            return "sentiment reversed/collapsed"
        if (sig.mention_velocity or 0) < settings.reddit_min_velocity:
            return "chatter died (velocity below floor)"
    return None


def _reddit_equity_exit_reason(
    t: PaperTrade, spot_now: float, settings, tp_pct: float
) -> str | None:
    """Same intraday clock as the options twin, but the take-profit / stop are
    measured on the underlying's move (there's no spread to value)."""
    if not settings.paper_reddit_enabled:
        return "strategy retired"
    # Global learned take-profit binds before the book's own (already-tight) band.
    tp_reason = _underlying_take_profit(t, spot_now, settings, tp_pct)
    if tp_reason is not None:
        return tp_reason
    if t.opened_at:
        held_hours = (datetime.utcnow() - t.opened_at).total_seconds() / 3600.0
        if held_hours >= settings.paper_reddit_hold_hours:
            return "hold window elapsed"
    entry_px = t.entry_credit or t.spot_entry
    if not entry_px:
        return None
    move = spot_now / entry_px - 1.0  # signed underlying move since entry
    tp = settings.paper_reddit_equity_take_profit_pct
    sl = settings.paper_reddit_equity_stop_pct
    if t.structure == EQUITY_LONG:
        if move >= tp:
            return f"take-profit ({move:+.1%})"
        if move <= -sl:
            return f"stop ({move:+.1%})"
    else:  # short: profits when the stock falls
        if move <= -tp:
            return f"take-profit ({move:+.1%})"
        if move >= sl:
            return f"stop ({move:+.1%})"
    return None


def _manage_one_equity_exit(
    db: Session, client: AlpacaClient, t: PaperTrade, settings, dry_run: bool,
    tp_pct: float,
) -> bool:
    """Close a Reddit equity twin (market order) on time or a %-move TP/SL."""
    spot_now = client.stock_price(t.ticker)
    if not spot_now:
        return False
    reason = _reddit_equity_exit_reason(t, spot_now, settings, tp_pct)
    if reason is None:
        return False
    if dry_run:
        logger.info("[dry-run] would close equity %s (%s) at %.2f", t.signal_id, reason, spot_now)
        return False
    # Close = the opposite side (sell a long, buy back a short).
    side = "sell" if t.structure == EQUITY_LONG else "buy"
    try:
        order = client.submit_stock_order(
            symbol=t.ticker, qty=t.contracts or 1, side=side,
            client_order_id=_close_client_order_id(t.signal_id),
        )
    except AlpacaError as e:
        logger.error("Equity close failed for %s: %s", t.signal_id, e)
        return False
    t.exit_order_id = order.get("id")
    t.exit_debit = round(spot_now, 2)  # price per share on close (provisional)
    t.status = "closing"
    t.note = reason
    t.spot_at_exit = round(spot_now, 2)
    entry_px = t.entry_credit or t.spot_entry
    if entry_px:
        t.realized_move_pct = round(spot_now / entry_px - 1, 4)
    _finalize_pnl(t)
    return True


def _scan_reddit_entries(
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool,
    calib: dict | None = None,
) -> tuple[int, list]:
    if not settings.paper_reddit_enabled:
        logger.info("reddit scan: disabled (paper_reddit_enabled=False)")
        return 0, []
    regime = regime_snapshot(settings)
    try:
        # persist=False on dry runs: current_reddit_signals commits when it
        # journals, which would otherwise prematurely persist the other
        # strategies' preview trades flushed earlier in this same run.
        signals = current_reddit_signals(db, persist=not dry_run)
    except Exception as e:  # noqa: BLE001 - never let a signal error break the run
        logger.warning("reddit signal build failed: %s", e)
        return 0, []
    logger.info(
        "reddit scan: %d signal(s): %s",
        len(signals),
        ", ".join(
            f"{s.get('ticker')}({s.get('direction')},{s.get('conviction')})"
            for s in signals
        ) or "none",
    )

    open_n = len(
        db.scalars(
            select(PaperTrade).where(
                PaperTrade.strategy == "reddit",
                PaperTrade.status.in_(OPEN_STATES),
                PaperTrade.structure.not_in(EQUITY_STRUCTURES),
            )
        ).all()
    )

    # How many *new* Reddit option entries we've already opened today, to enforce
    # the per-day cap (equity twins don't count - they ride an option entry).
    start_today = datetime.combine(datetime.utcnow().date(), datetime.min.time())
    new_today = len(
        db.scalars(
            select(PaperTrade).where(
                PaperTrade.strategy == "reddit",
                PaperTrade.structure.not_in(EQUITY_STRUCTURES),
                PaperTrade.created_at >= start_today,
            )
        ).all()
    )
    cooldown_cutoff = datetime.utcnow() - timedelta(
        days=settings.paper_reddit_reentry_cooldown_days
    )

    min_conv = _CONVICTION_RANK.get(settings.reddit_min_conviction, 1)
    max_pump = _PUMP_RANK.get(settings.reddit_max_pump_risk, 1)

    opened = 0
    skipped: list[dict] = []
    seen: set[str] = set()
    for sig in signals:
        ticker = sig.get("ticker")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)

        if open_n + opened >= settings.paper_reddit_max_open:
            skipped.append({"ticker": ticker, "reason": "max open reddit positions"})
            continue
        if new_today + opened >= settings.paper_reddit_max_new_per_day:
            skipped.append(
                {"ticker": ticker, "reason": "daily new-entry cap reached"}
            )
            continue
        def _reddit_skip_feats() -> dict:
            return reddit_features(
                sig, conviction=reddit_conviction(sig),
                win_prob=_REDDIT_WIN_PROB.get(sig.get("conviction"), 0.45),
                equity=equity,
            )

        if sig.get("is_noise"):
            reason = "noise (no clear lean)"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="reddit", ticker=ticker, decision="skipped",
                skip_reason=reason, regime=regime, features=_reddit_skip_feats(),
            )
            continue
        if sig.get("direction") not in ("bullish", "bearish"):
            reason = "no directional lean"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="reddit", ticker=ticker, decision="skipped",
                skip_reason=reason, regime=regime, features=_reddit_skip_feats(),
            )
            continue
        if _CONVICTION_RANK.get(sig.get("conviction"), 0) < min_conv:
            reason = f"conviction too low ({sig.get('conviction')})"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="reddit", ticker=ticker, decision="skipped",
                skip_reason=reason, regime=regime, features=_reddit_skip_feats(),
            )
            continue
        # Anti-pump guard: refuse anything at/above the pump-risk ceiling so we're
        # never late-stage exit liquidity.
        if _PUMP_RANK.get(sig.get("pump_risk"), 0) > max_pump:
            reason = f"pump risk too high ({sig.get('pump_risk')})"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="reddit", ticker=ticker, decision="skipped",
                skip_reason=reason, regime=regime, features=_reddit_skip_feats(),
            )
            continue

        # One open trade per ticker at a time.
        existing = db.scalars(
            select(PaperTrade).where(
                PaperTrade.ticker == ticker,
                PaperTrade.strategy == "reddit",
                PaperTrade.status.in_(OPEN_STATES),
                PaperTrade.structure.not_in(EQUITY_STRUCTURES),
            )
        ).first()
        if existing:
            continue
        # Re-entry cooldown: don't chase the same name day after day - require a
        # gap since its last entry (win or lose) before we trade it again.
        recent = db.scalars(
            select(PaperTrade).where(
                PaperTrade.ticker == ticker,
                PaperTrade.strategy == "reddit",
                PaperTrade.structure.not_in(EQUITY_STRUCTURES),
                PaperTrade.created_at >= cooldown_cutoff,
            )
        ).first()
        if recent:
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": (
                        f"cooldown (traded within "
                        f"{settings.paper_reddit_reentry_cooldown_days}d)"
                    ),
                }
            )
            continue

        conv = reddit_conviction(sig)
        risk_frac = settings.paper_reddit_risk_fraction(conv)
        win_prob = _REDDIT_WIN_PROB.get(sig.get("conviction"), 0.45)
        budget = equity * risk_frac
        spec, reason = build_reddit_spec(client, sig, risk_budget=budget)
        if spec is None:
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="reddit", ticker=ticker, decision="skipped",
                skip_reason=reason, regime=regime,
                features=reddit_features(
                    sig, conviction=conv, win_prob=win_prob,
                    risk_frac=risk_frac, equity=equity,
                ),
            )
            continue

        per_contract = spec.net_debit * 100
        contracts = int(budget // per_contract) if per_contract > 0 else 0
        contracts = min(contracts, settings.paper_max_contracts)
        if contracts < 1:
            reason = f"debit too rich (${per_contract:.0f}/ct vs ${budget:.0f})"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="reddit", ticker=ticker, decision="skipped",
                skip_reason=reason, regime=regime,
                features=reddit_features(
                    sig, conviction=conv, win_prob=win_prob, spec=spec,
                    risk_frac=risk_frac, equity=equity,
                ),
            )
            continue

        trade = _record_reddit_trade(db, sig, spec, contracts, equity)
        feats = reddit_features(
            sig, conviction=conv, win_prob=win_prob, spec=spec,
            contracts=contracts, risk_frac=risk_frac, equity=equity,
        )
        if dry_run:
            logger.info(
                "[dry-run] REDDIT %s %s spread x%d @ debit %.2f (%s, %.1fx, %s)",
                ticker, spec.option_type, contracts, spec.net_debit,
                sig.get("conviction"), sig.get("mention_velocity") or 0,
                sig.get("scored_by"),
            )
            trade.note = "dry-run (not submitted)"
            record_decision(
                db, strategy="reddit", ticker=ticker, decision="opened",
                signal_id=trade.signal_id, regime=regime, features=feats,
            )
            opened += 1
            continue

        order_legs = [
            {
                "symbol": l.symbol,
                "ratio_qty": "1",
                "side": l.side,
                "position_intent": l.position_intent,
            }
            for l in spec.legs
        ]
        gate_win_prob = adjust_win_prob(win_prob, "reddit", calib, settings)
        limit, reason = _gate_entry(
            client, order_legs, is_credit=False, mid=spec.net_debit,
            width=spec.width, win_prob=gate_win_prob, settings=settings,
        )
        if limit is None:
            trade.status = "canceled"
            trade.note = f"skipped: {reason}"
            skipped.append({"ticker": ticker, "reason": reason})
            record_decision(
                db, strategy="reddit", ticker=ticker, decision="skipped",
                skip_reason=reason, regime=regime, features=feats,
            )
            continue
        try:
            order = client.submit_mleg(
                legs=order_legs,
                qty=contracts,
                limit_price=limit,
                client_order_id=trade.signal_id,
            )
        except AlpacaError as e:
            logger.error("Reddit order failed for %s: %s", ticker, e)
            trade.status = "canceled"
            trade.note = f"submit error: {e}"[:500]
            skipped.append({"ticker": ticker, "reason": f"submit error: {e}"})
            record_decision(
                db, strategy="reddit", ticker=ticker, decision="skipped",
                skip_reason=f"submit error: {e}", regime=regime, features=feats,
            )
            continue
        trade.entry_order_id = order.get("id")
        _apply_entry_fill(trade, order)
        record_decision(
            db, strategy="reddit", ticker=ticker, decision="opened",
            signal_id=trade.signal_id, regime=regime, features=feats,
        )
        opened += 1
        _open_reddit_equity_twin(db, client, sig, trade, settings)

    if not dry_run:
        db.commit()
    return opened, skipped


def _open_reddit_equity_twin(
    db: Session, client: AlpacaClient, sig: dict, option_trade: PaperTrade, settings
) -> None:
    """Alongside the options spread, open a stock position on the same name and
    direction (short for bearish), sized to the same dollar risk as the spread -
    an A/B twin to see whether the shares beat the options on the same signal."""
    if not settings.paper_reddit_equity_twin_enabled:
        return
    # Only mirror an option leg that actually opened cleanly and passed the
    # fair-trade gate -- never a leg that failed to fill or was flagged a bad
    # fill (about to be flattened). The twin's dollar risk is matched to that
    # gated option leg, so its sizing inherits the same discipline.
    if option_trade.status != "open" or (option_trade.note or "").startswith(
        _BAD_FILL_PREFIX
    ):
        return
    notional = option_trade.max_risk or 0.0
    spot = option_trade.spot_entry or client.stock_price(option_trade.ticker)
    if not spot or spot <= 0 or notional <= 0:
        return
    shares = int(notional // spot)
    if shares < 1:
        return

    bullish = option_trade.direction == "bullish"
    side = "buy" if bullish else "sell"
    structure = EQUITY_LONG if bullish else EQUITY_SHORT
    signal_id = f"{option_trade.signal_id}-EQ"

    thesis = {
        "instrument": "equity",
        "twin_of": option_trade.signal_id,
        "subreddits": sig.get("subreddits"),
        "mention_velocity": sig.get("mention_velocity"),
        "mention_count": sig.get("mention_count"),
    }
    eq = PaperTrade(
        signal_id=signal_id,
        strategy="reddit",
        ticker=option_trade.ticker,
        earnings_date=None,
        structure=structure,
        direction=option_trade.direction,
        vol_stance="buy",
        conviction=option_trade.conviction,
        thesis=json.dumps(thesis)[:2048],
        status="pending",
        legs=None,
        contracts=shares,
        expiration=None,
        width=None,
        entry_credit=round(spot, 2),      # price per share (provisional; fill overrides)
        modeled_credit=round(spot, 2),
        max_risk=round(notional, 2),
        spot_entry=round(spot, 2),
        equity_at_entry=option_trade.equity_at_entry,
    )
    db.add(eq)
    db.flush()
    try:
        order = client.submit_stock_order(
            symbol=option_trade.ticker, qty=shares, side=side, client_order_id=signal_id,
        )
    except AlpacaError as e:
        logger.error("Reddit equity twin failed for %s: %s", option_trade.ticker, e)
        eq.status = "canceled"
        eq.note = f"submit error: {e}"[:500]
        return
    eq.entry_order_id = order.get("id")
    _apply_entry_fill(eq, order)
    logger.info(
        "REDDIT equity twin %s: %s %d %s @ ~%.2f (risk-matched to %s)",
        signal_id, side, shares, option_trade.ticker, spot, option_trade.signal_id,
    )


def _record_reddit_trade(
    db: Session,
    sig: dict,
    spec: RedditSpec,
    contracts: int,
    equity: float | None,
) -> PaperTrade:
    signal_id = _next_reddit_signal_id(db)
    bullish = sig.get("direction") == "bullish"
    thesis = {
        "sentiment": sig.get("sentiment"),
        "mention_count": sig.get("mention_count"),
        "mention_velocity": sig.get("mention_velocity"),
        "pump_risk": sig.get("pump_risk"),
        "subreddits": sig.get("subreddits"),
        "scored_by": sig.get("scored_by"),
        "rationale": sig.get("rationale"),
        "samples": (sig.get("samples") or [])[:3],
    }
    legs_json = json.dumps(
        [
            {
                "symbol": l.symbol,
                "type": l.option_type,
                "side": l.side,
                "strike": l.strike,
                "mid": l.mid,
            }
            for l in spec.legs
        ]
    )
    trade = PaperTrade(
        signal_id=signal_id,
        strategy="reddit",
        ticker=sig["ticker"],
        earnings_date=None,  # social signal, not earnings-driven
        structure="Bull call spread" if bullish else "Bear put spread",
        direction="bullish" if bullish else "bearish",
        vol_stance="buy",
        conviction=reddit_conviction(sig),
        thesis=json.dumps(thesis)[:2048],
        status="pending",
        legs=legs_json[:2048],
        contracts=contracts,
        expiration=spec.expiration,
        width=spec.width,
        entry_credit=spec.net_debit,  # debit paid (max loss) per share
        modeled_credit=spec.net_debit,
        max_risk=round(spec.net_debit * 100 * contracts, 2),
        spot_entry=spec.spot,
        equity_at_entry=round(equity, 2) if equity else None,
    )
    db.add(trade)
    db.flush()
    return trade


def _next_reddit_signal_id(db: Session) -> str:
    stamp = date.today().strftime("%Y%m%d")
    prefix = f"RS-{stamp}-"
    n = len(
        db.scalars(
            select(PaperTrade).where(PaperTrade.signal_id.like(f"{prefix}%"))
        ).all()
    )
    return f"{prefix}{n + 1:03d}"


# --- trade notifications -----------------------------------------------------


def _notify_trades(db: Session, pre_status: dict[str, str]) -> dict:
    """Send a Telegram alert for trades that actually FILLED this run.

    We alert on the fill, not the order: an entry that's still a resting limit
    ("pending") or a close that's been submitted but hasn't filled ("closing")
    is not reported. Comparing each trade's status against the pre-run snapshot:
      - opened = reached "open" from a not-yet-filled state (new/"pending"),
        excluding a "closing"->"open" re-arm (a lapsed close, not a new entry).
      - closed = reached "closed" (the close order filled).

    Returns ``{attempted, ok, opened, closed}`` so the health layer can fail
    loud when Telegram drops a real fill/close alert.
    """
    # Expire cached ORM state - sync_labels may have committed mid-run, and we
    # need the statuses mutated by reconcile/exits, not a stale identity map.
    db.expire_all()
    rows = db.scalars(
        select(PaperTrade).where(PaperTrade.status.in_(("open", "closed")))
    ).all()
    opened = [
        t for t in rows
        if t.status == "open" and pre_status.get(t.signal_id) in (None, "pending")
    ]
    closed = [
        t for t in rows
        if t.status == "closed" and pre_status.get(t.signal_id) != "closed"
    ]

    if not opened and not closed:
        return {"attempted": False, "ok": True, "opened": 0, "closed": 0}
    ok = send_telegram(_format_trade_alert(opened, closed))
    logger.info(
        "telegram alert %s: %d opened, %d closed",
        "sent" if ok else "FAILED",
        len(opened),
        len(closed),
    )
    return {
        "attempted": True,
        "ok": ok,
        "opened": len(opened),
        "closed": len(closed),
    }


def _format_trade_alert(
    opened: list[PaperTrade], closed: list[PaperTrade]
) -> str:
    lines = [f"EarningsFollower: {len(opened)} opened, {len(closed)} closed"]
    if opened:
        lines.append("")
        lines.append("OPENED")
        lines.extend(_open_alert_line(t) for t in opened)
    if closed:
        lines.append("")
        lines.append("CLOSED")
        lines.extend(_close_alert_line(t) for t in closed)
    return "\n".join(lines)


def _open_alert_line(t: PaperTrade) -> str:
    strat = t.strategy or "earnings"
    conv = t.conviction or "?"
    if _is_equity(t):
        side = "Long" if t.structure == EQUITY_LONG else "Short"
        px = t.entry_credit or t.spot_entry or 0.0
        return f"- {t.ticker}: {side} {t.contracts} sh @ ${px:.2f} ({strat} equity, {conv})"
    # Options: sell-vol earnings collects a credit; the debit strategies pay one.
    kind = "credit" if strat == "earnings" else "debit"
    return (
        f"- {t.ticker}: {t.structure} x{t.contracts}, "
        f"{kind} ${t.entry_credit or 0.0:.2f} ({strat}, {conv})"
    )


def _close_alert_line(t: PaperTrade) -> str:
    pnl = t.realized_pnl
    if pnl is None:
        pnl_txt = "P&L pending"
    else:
        pnl_txt = f"{'+' if pnl >= 0 else '-'}${abs(pnl):.2f}"
    return f"- {t.ticker}: {t.structure} {pnl_txt} ({t.note or 'closed'})"
