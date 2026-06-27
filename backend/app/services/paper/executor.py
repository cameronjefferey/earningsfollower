"""The paper earnings trader.

Daily flow:
  1. reconcile  - update pending/closing trades from Alpaca order status
  2. manage     - close open positions whose earnings print has passed (capture
                  the post-earnings IV crush the sell-premium thesis relies on)
  3. scan       - find tickers reporting within the entry window, run the
                  playbook, and open premium-selling trades sized to ~risk budget

Everything is journaled to the `paper_trades` table with a unique signal id.
Set dry_run=True to preview without submitting any orders.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.alpaca import AlpacaClient, AlpacaError
from app.config import get_settings
from app.db.models import EarningsEvent, PaperTrade, PriceBar
from app.services.dashboard import company_detail
from app.services.paper.contracts import TradeSpec, build_trade_spec
from app.services.paper.drift_trader import DriftSpec, build_drift_spec, drift_conviction
from app.services.paper.waves_trader import WaveSpec, build_wave_spec, wave_conviction
from app.services.waves import current_waves

logger = logging.getLogger(__name__)

SELLING_STRUCTURES = {
    "Bear call (call credit) spread",
    "Bull put (put credit) spread",
    "Iron condor",
}

OPEN_STATES = ("pending", "open", "closing")


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
    try:
        equity = client.equity()
        summary["equity"] = equity

        # Only place orders when the market is open — options can't fill
        # overnight or pre/post-open, which is what left whole batches expiring.
        # dry-runs ignore this (they never submit). Reconcile always runs so
        # fills from the prior session still get picked up.
        market_open = True
        if settings.paper_market_hours_only and not dry_run:
            market_open = client.is_market_open()
        summary["market_open"] = market_open

        summary["reconciled"] = _reconcile(db, client, dry_run)
        if not market_open:
            logger.info("market closed; reconciling only, no orders this run")
            summary["skipped"] = [{"reason": "market closed"}]
            return summary

        summary["closed"] = _manage_exits(db, client, settings, dry_run)
        summary["closed"] += _manage_wave_exits(db, client, settings, dry_run)
        summary["closed"] += _manage_drift_exits(db, client, settings, dry_run)
        opened, skipped = _scan_entries(db, client, equity, settings, dry_run)
        w_opened, w_skipped = _scan_wave_entries(db, client, equity, settings, dry_run)
        d_opened, d_skipped = _scan_drift_entries(db, client, equity, settings, dry_run)
        summary["opened"] = opened + w_opened + d_opened
        summary["skipped"] = skipped + w_skipped + d_skipped
    except AlpacaError as e:
        logger.error("Alpaca error during paper run: %s", e)
        summary["status"] = "error"
        summary["errors"].append(str(e))
    finally:
        client.close()
    return summary


# --- reconcile ---------------------------------------------------------------


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
    if not dry_run:
        db.commit()
    return count


# --- exits -------------------------------------------------------------------


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
        limit = _marketable_net(
            client, close_legs, is_credit=False, mid=exit_net, settings=settings, quotes=quotes
        )
        try:
            order = client.submit_mleg(
                legs=close_legs,
                qty=t.contracts or 1,
                limit_price=limit,
                client_order_id=f"{t.signal_id}-x",
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


def _exit_reason(t: PaperTrade, exit_net: float, today: date, settings) -> str | None:
    """Decide whether (and why) to close an open trade now."""
    # Planned exit: the print has passed — close to capture the IV crush. We
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
    if (t.strategy or "earnings") in ("waves", "drift"):
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


def _scan_entries(
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool
) -> tuple[int, list]:
    today = date.today()
    window_end = today + timedelta(days=settings.paper_entry_window_days)

    open_n = len(
        db.scalars(
            select(PaperTrade).where(PaperTrade.status.in_(OPEN_STATES))
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

        if open_n + opened >= settings.paper_max_open:
            skipped.append({"ticker": ticker, "reason": "max open positions reached"})
            continue

        # Already have a trade for this ticker+event?
        existing = db.scalars(
            select(PaperTrade).where(
                PaperTrade.ticker == ticker,
                PaperTrade.earnings_date == ev.date,
            )
        ).first()
        if existing:
            continue

        detail = company_detail(db, ticker)
        pb = (detail or {}).get("playbook")
        if not pb:
            skipped.append({"ticker": ticker, "reason": "no playbook"})
            continue
        if pb["vol_stance"] != "sell" or pb["structure"] not in SELLING_STRUCTURES:
            skipped.append(
                {"ticker": ticker, "reason": f"not a sell-vol setup ({pb['structure']})"}
            )
            continue

        # Size by the playbook's conviction: risk more when the signals agree.
        # The budget also caps the spread width (wings pull in to fit it).
        risk_frac = settings.paper_risk_fraction(pb["conviction"])
        budget = equity * risk_frac

        spec, reason = build_trade_spec(client, ticker, pb, ev.date, risk_budget=budget)
        if spec is None:
            skipped.append({"ticker": ticker, "reason": reason})
            continue
        if spec.net_credit < settings.paper_min_credit:
            skipped.append({"ticker": ticker, "reason": f"credit too thin ({spec.net_credit})"})
            continue

        contracts = int(budget // spec.max_risk_per_contract)
        contracts = min(contracts, settings.paper_max_contracts)
        if contracts < 1:
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": (
                        f"spread too wide for {pb['conviction']} budget "
                        f"({risk_frac:.1%} = ${budget:.0f}; risk ${spec.max_risk_per_contract:.0f}/ct)"
                    ),
                }
            )
            continue

        im = (detail or {}).get("implied_move") or {}
        trade = _record_trade(
            db, ticker, ev, pb, spec, contracts,
            expected_move_pct=im.get("expected_move_pct"),
            spot_entry=im.get("underlying_price") or pb.get("spot"),
            equity=equity,
        )

        if dry_run:
            logger.info(
                "[dry-run] %s %s [%s %.1f%%] x%d @ credit %.2f (risk $%.0f)",
                ticker, pb["structure"], pb["conviction"], risk_frac * 100,
                contracts, spec.net_credit, spec.max_risk_per_contract * contracts,
            )
            trade.note = "dry-run (not submitted)"
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
        limit = _marketable_net(
            client, order_legs, is_credit=True, mid=spec.net_credit, settings=settings
        )
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
            skipped.append({"ticker": ticker, "reason": f"submit error: {e}"})
            continue
        trade.entry_order_id = order.get("id")
        _apply_entry_fill(trade, order)
        opened += 1

    if not dry_run:
        db.commit()
    return opened, skipped


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


def _marketable_net(
    client: AlpacaClient,
    legs: list[dict],
    is_credit: bool,
    mid: float,
    settings,
    quotes: dict | None = None,
) -> float:
    """Marketable net limit price (positive) for a leg set.

    A limit resting at the mid rarely fills; nudge it toward the touch so the
    order executes. Debits (we pay) move UP toward the net ask; credits (we
    collect) move DOWN toward the net bid. The move is capped by
    ``paper_fill_slippage_*`` so a wide/stale quote can't blow up the price.
    Falls back to the mid if any leg lacks a two-sided quote.
    """
    syms = [l["symbol"] for l in legs]
    q = quotes if quotes is not None else client.option_quotes(syms)
    if any(
        (q.get(s, {}).get("bid") or 0) <= 0 or (q.get(s, {}).get("ask") or 0) <= 0
        for s in syms
    ):
        return round(max(0.01, mid), 2)
    buy_ask = sum(q[l["symbol"]]["ask"] for l in legs if l["side"] == "buy")
    buy_bid = sum(q[l["symbol"]]["bid"] for l in legs if l["side"] == "buy")
    sell_ask = sum(q[l["symbol"]]["ask"] for l in legs if l["side"] == "sell")
    sell_bid = sum(q[l["symbol"]]["bid"] for l in legs if l["side"] == "sell")
    frac = settings.paper_fill_slippage_frac
    cap = settings.paper_fill_slippage_cap
    if is_credit:
        touch = sell_bid - buy_ask  # worst (most marketable) credit we'd accept
        give = min(cap, frac * max(0.0, mid - touch))
        price = mid - give
    else:
        touch = buy_ask - sell_bid  # worst (most marketable) debit we'd pay
        give = min(cap, frac * max(0.0, touch - mid))
        price = mid + give
    return round(max(0.01, price), 2)


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
        return True
    return False


# --- waves strategy ----------------------------------------------------------


def _parse_iso(value) -> date | None:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _manage_wave_exits(
    db: Session, client: AlpacaClient, settings, dry_run: bool
) -> int:
    """Close open wave trades on the underlying-move bracket or the day before
    the target's own earnings (ride the build-up, not the print)."""
    today = date.today()
    closed = 0
    trades = db.scalars(
        select(PaperTrade).where(
            PaperTrade.strategy == "waves", PaperTrade.status == "open"
        )
    ).all()
    for t in trades:
        legs = json.loads(t.legs or "[]")
        if not legs:
            continue
        sym = legs[0]["symbol"]
        spot_now = client.stock_price(t.ticker)
        reason = _wave_exit_reason(t, spot_now, today, settings)
        if reason is None:
            continue
        q = client.option_quotes([sym])
        mid = float(q.get(sym, {}).get("mid") or 0.0)
        if mid <= 0:
            continue  # can't price the close right now; retry next run
        if dry_run:
            logger.info(
                "[dry-run] would close wave %s (%s) at %.2f", t.signal_id, reason, mid
            )
            continue
        limit = _marketable_net(
            client,
            [{"symbol": sym, "side": "sell"}],
            is_credit=True,
            mid=mid,
            settings=settings,
            quotes=q,
        )
        try:
            order = client.submit_option_order(
                symbol=sym,
                qty=t.contracts or 1,
                side="sell",
                position_intent="sell_to_close",
                limit_price=limit,
                client_order_id=f"{t.signal_id}-x",
            )
        except AlpacaError as e:
            logger.error("Wave close failed for %s: %s", t.signal_id, e)
            continue
        t.exit_order_id = order.get("id")
        t.exit_debit = round(mid, 2)  # proceeds per share on close
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


def _wave_exit_reason(t: PaperTrade, spot_now: float | None, today: date, settings) -> str | None:
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
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool
) -> tuple[int, list]:
    if not settings.paper_waves_enabled:
        return 0, []
    today = date.today()
    try:
        signals = current_waves(db)
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
        if wr is None or wr < settings.paper_wave_min_winrate:
            skipped.append({"ticker": target, "reason": f"win rate too low ({wr})"})
            continue
        if n is None or n < settings.paper_wave_min_samples:
            skipped.append({"ticker": target, "reason": f"too few samples ({n})"})
            continue

        tgt_date = _parse_iso(sig.get("target_report_date"))
        if tgt_date is None:
            continue
        runway = (tgt_date - today).days
        if runway < settings.paper_wave_min_runway_days:
            skipped.append({"ticker": target, "reason": f"too close to print ({runway}d)"})
            continue

        existing = db.scalars(
            select(PaperTrade).where(
                PaperTrade.ticker == target,
                PaperTrade.earnings_date == tgt_date,
                PaperTrade.strategy == "waves",
            )
        ).first()
        if existing:
            continue

        spec, reason = build_wave_spec(client, sig, tgt_date)
        if spec is None:
            skipped.append({"ticker": target, "reason": reason})
            continue

        budget = equity * settings.paper_wave_risk_frac
        per_contract = spec.premium * 100
        contracts = int(budget // per_contract) if per_contract > 0 else 0
        contracts = min(contracts, settings.paper_max_contracts)
        if contracts < 1:
            skipped.append(
                {
                    "ticker": target,
                    "reason": f"premium too rich (${per_contract:.0f}/ct vs ${budget:.0f})",
                }
            )
            continue

        trade = _record_wave_trade(db, sig, spec, tgt_date, contracts, equity)
        if dry_run:
            logger.info(
                "[dry-run] WAVE %s long %s x%d @ %.2f (trigger %s)",
                target, spec.option_type, contracts, spec.premium, sig.get("trigger"),
            )
            trade.note = "dry-run (not submitted)"
            opened += 1
            continue

        limit = _marketable_net(
            client,
            [{"symbol": spec.symbol, "side": "buy"}],
            is_credit=False,
            mid=spec.premium,
            settings=settings,
        )
        try:
            order = client.submit_option_order(
                symbol=spec.symbol,
                qty=contracts,
                side="buy",
                position_intent="buy_to_open",
                limit_price=limit,
                client_order_id=trade.signal_id,
            )
        except AlpacaError as e:
            logger.error("Wave order failed for %s: %s", target, e)
            trade.status = "canceled"
            trade.note = f"submit error: {e}"[:500]
            skipped.append({"ticker": target, "reason": f"submit error: {e}"})
            continue
        trade.entry_order_id = order.get("id")
        _apply_entry_fill(trade, order)
        opened += 1

    if not dry_run:
        db.commit()
    return opened, skipped


def _record_wave_trade(
    db: Session,
    sig: dict,
    spec: WaveSpec,
    tgt_date: date,
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
                "symbol": spec.symbol,
                "type": spec.option_type,
                "side": "buy",
                "strike": spec.strike,
                "mid": spec.premium,
            }
        ]
    )
    trade = PaperTrade(
        signal_id=signal_id,
        strategy="waves",
        ticker=sig["target"],
        earnings_date=tgt_date,
        structure=f"Long {spec.option_type}",
        direction=direction,
        vol_stance="buy",
        conviction=wave_conviction(sig),
        thesis=json.dumps(thesis)[:2048],
        status="pending",
        legs=legs_json[:2048],
        contracts=contracts,
        expiration=spec.expiration,
        entry_credit=spec.premium,  # premium paid (debit) per share
        modeled_credit=spec.premium,
        max_risk=round(spec.premium * 100 * contracts, 2),
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
    db: Session, client: AlpacaClient, settings, dry_run: bool
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
        reason = _drift_exit_reason(t, spot_now, exit_value, today, settings)
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
        limit = _marketable_net(
            client, close_legs, is_credit=True, mid=exit_value, settings=settings, quotes=quotes
        )
        try:
            order = client.submit_mleg(
                legs=close_legs,
                qty=t.contracts or 1,
                limit_price=limit,
                client_order_id=f"{t.signal_id}-x",
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
    t: PaperTrade, spot_now: float | None, exit_value: float, today: date, settings
) -> str | None:
    # Time exit: the drift window the edge is measured over has elapsed.
    if t.earnings_date and (today - t.earnings_date).days >= settings.paper_drift_hold_days:
        return "drift window elapsed"
    # Take-profit: the spread is worth most of its max width.
    if t.width and exit_value >= settings.paper_drift_take_profit * t.width:
        return f"take-profit ({exit_value / t.width:.0%} of width)"
    # Stop: underlying gave back the post-earnings move (broken thesis).
    try:
        stop = (json.loads(t.thesis or "{}") or {}).get("stop_level")
    except json.JSONDecodeError:
        stop = None
    if stop and spot_now:
        long = t.direction == "bullish"
        if long and spot_now < stop:
            return "stop (gave back the move)"
        if not long and spot_now > stop:
            return "stop (gave back the move)"
    return None


def _scan_drift_entries(
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool
) -> tuple[int, list]:
    if not settings.paper_drift_enabled:
        logger.info("drift scan: disabled (paper_drift_enabled=False)")
        return 0, []
    try:
        from app.services.drift import drift_setups

        setups = drift_setups(db)
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

        if open_n + opened >= settings.paper_drift_max_open:
            skipped.append({"ticker": ticker, "reason": "max open drift positions"})
            continue
        if (setup.get("plan") or {}).get("entry_quality") == "late":
            skipped.append({"ticker": ticker, "reason": "late entry (drift window mostly gone)"})
            continue
        if (setup.get("score") or 0) < settings.paper_drift_min_score:
            skipped.append({"ticker": ticker, "reason": f"score below floor ({setup.get('score')})"})
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
        spec, reason = build_drift_spec(client, setup, risk_budget=budget)
        if spec is None:
            skipped.append({"ticker": ticker, "reason": reason})
            continue

        per_contract = spec.net_debit * 100
        contracts = int(budget // per_contract) if per_contract > 0 else 0
        contracts = min(contracts, settings.paper_max_contracts)
        if contracts < 1:
            skipped.append(
                {
                    "ticker": ticker,
                    "reason": f"debit too rich (${per_contract:.0f}/ct vs ${budget:.0f})",
                }
            )
            continue

        trade = _record_drift_trade(db, setup, spec, report_date, contracts, equity)
        if dry_run:
            logger.info(
                "[dry-run] DRIFT %s %s spread x%d @ debit %.2f (edge %s)",
                ticker, spec.legs[0].option_type, contracts, spec.net_debit,
                (setup.get("history") or {}).get("avg_drift_5d_pct"),
            )
            trade.note = "dry-run (not submitted)"
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
        limit = _marketable_net(
            client, order_legs, is_credit=False, mid=spec.net_debit, settings=settings
        )
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
            continue
        trade.entry_order_id = order.get("id")
        _apply_entry_fill(trade, order)
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
