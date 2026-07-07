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
from app.services.paper.risk import defined_risk_max_loss
from app.services.paper.drift_trader import DriftSpec, build_drift_spec, drift_conviction
from app.services.paper.reddit_trader import (
    RedditSpec,
    build_reddit_spec,
    reddit_conviction,
)
from app.services.paper.waves_trader import WaveSpec, build_wave_spec, wave_conviction
from app.services.reddit_sentiment import current_reddit_signals, latest_reddit_signal
from app.services.waves import current_sympathy_waves

logger = logging.getLogger(__name__)

SELLING_STRUCTURES = {
    "Bear call (call credit) spread",
    "Bull put (put credit) spread",
    "Iron condor",
}

OPEN_STATES = ("pending", "open", "closing")

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
        summary["closed"] += _manage_reddit_exits(db, client, settings, dry_run)
        opened, skipped = _scan_entries(db, client, equity, settings, dry_run)
        w_opened, w_skipped = _scan_wave_entries(db, client, equity, settings, dry_run)
        d_opened, d_skipped = _scan_drift_entries(db, client, equity, settings, dry_run)
        r_opened, r_skipped = _scan_reddit_entries(db, client, equity, settings, dry_run)
        summary["opened"] = opened + w_opened + d_opened + r_opened
        summary["skipped"] = skipped + w_skipped + d_skipped + r_skipped
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
                    _recompute_max_risk(t)
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
                # re-attempts — never leave a position stuck mid-close.
                t.status = "open"
                t.exit_order_id = None
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
        limit = _marketable_net(
            client, close_legs, is_credit=False, mid=exit_net, settings=settings,
            quotes=quotes, aggressive=False,
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
    # Operational override: flatten specific signal ids on request (e.g. a bad
    # fill) through the normal close path so the DB stays consistent.
    if t.signal_id in settings.paper_force_close_id_set:
        return "manual close"
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

        spec, reason = build_trade_spec(
            client, ticker, pb, ev.date,
            risk_budget=budget,
            min_credit_ratio=settings.paper_min_credit_width_ratio,
        )
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
            client, order_legs, is_credit=True, mid=spec.net_credit, settings=settings,
            min_credit=settings.paper_min_credit_width_ratio * spec.width,
        )
        if limit is None:
            trade.status = "canceled"
            trade.note = "skipped: market too wide to trade"
            skipped.append({"ticker": ticker, "reason": "market too wide (illiquid)"})
            continue
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
    aggressive: bool = True,
    min_credit: float | None = None,
) -> float | None:
    """Signed net limit price for a leg set, or ``None`` if the market's too wide
    to trade (entries only).

    SIGN — Alpaca multi-leg ``limit_price`` is signed: a positive value is a net
    *debit* (the most we'll pay), a negative value is a net *credit* (the least
    we'll accept to receive). A net-credit order sent as a *positive* number is
    read as a debit ceiling — i.e. "pay up to X to close" — which makes it
    marketable and dumps the spread into the touch (that's what closed a $6-wide
    spread for $0.35). So every credit order MUST be negative. We compute a
    positive magnitude below and sign it at the end.

    ``aggressive`` (entries): price at the *cross* — take the ask on legs we buy
    and hit the bid on legs we sell, plus a small buffer — so it fills. But if
    crossing the market gives up more than ``paper_max_cross_slippage_frac`` of
    the combo's mid value, the market is too wide/illiquid to trade without the
    round-trip slippage swamping the edge, so we return ``None`` and skip it
    (this is what bled AMD/MU: $8+-wide legs mean crossing costs more than the
    spread is worth).

    ``min_credit`` (credit entries only): a hard floor on the credit we'll accept.

    not ``aggressive`` (exits): price at the **mid** nudged only a buffer toward
    the touch. We already hold the position, so we never cross to a thin bid and
    give the spread away; if it doesn't fill we just retry next run.
    """
    syms = [l["symbol"] for l in legs]
    q = quotes if quotes is not None else client.option_quotes(syms)
    buf = settings.paper_fill_buffer

    def _mag(price: float) -> float:
        if is_credit and min_credit is not None:
            price = max(price, min_credit)
        return round(max(0.01, price), 2)

    def _signed(mag: float) -> float:
        # + = net debit (we pay), - = net credit (we receive). See SIGN above.
        return -mag if is_credit else mag

    if not aggressive:
        # Exit: sell a hair below mid (credit) / pay a hair above mid (debit).
        price = (mid - buf) if is_credit else (mid + buf)
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
    # spread's mid value — a wide market bleeds far more on the round trip than
    # the trade can make.
    if mid > 0 and abs(cross - mid) > settings.paper_max_cross_slippage_frac * mid:
        logger.info(
            "skip entry: market too wide (mid %.2f vs cross %.2f, slip %.0f%% > %.0f%%)",
            mid, cross, abs(cross - mid) / mid * 100,
            settings.paper_max_cross_slippage_frac * 100,
        )
        return None

    return _signed(_mag(cross))


def _recompute_max_risk(trade: PaperTrade) -> None:
    """Re-derive max_risk from the *actual* booked entry price.

    At record time max_risk is modeled off the mid credit, but the real fill
    almost always differs. Recomputing here keeps the stored max loss — and the
    max-profit:max-loss ratio the UI derives from it — consistent with the
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
            _recompute_max_risk(trade)
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
        reason = _wave_exit_reason(t, spot_now, today, settings)
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
        limit = _marketable_net(
            client, close_legs, is_credit=True, mid=exit_value, settings=settings,
            quotes=quotes, aggressive=False,
        )
        try:
            order = client.submit_mleg(
                legs=close_legs,
                qty=t.contracts or 1,
                limit_price=limit,
                client_order_id=f"{t.signal_id}-x",
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


def _wave_exit_reason(t: PaperTrade, spot_now: float | None, today: date, settings) -> str | None:
    # Fixed short hold: the sympathy pop is a few-day move — take it and leave.
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
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool
) -> tuple[int, list]:
    if not settings.paper_waves_enabled:
        return 0, []
    today = date.today()
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
        if wr is None or wr < settings.paper_wave_min_winrate:
            skipped.append({"ticker": target, "reason": f"win rate too low ({wr})"})
            continue
        if n is None or n < settings.paper_wave_min_samples:
            skipped.append({"ticker": target, "reason": f"too few samples ({n})"})
            continue

        # The catalyst is the peer's print, not the target's — so the target's
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

        # One open wave trade per ticker at a time (re-entry allowed once closed).
        existing = db.scalars(
            select(PaperTrade).where(
                PaperTrade.ticker == target,
                PaperTrade.strategy == "waves",
                PaperTrade.status.in_(OPEN_STATES),
            )
        ).first()
        if existing:
            continue

        budget = equity * settings.paper_wave_risk_frac
        spec, reason = build_wave_spec(
            client, sig, risk_budget=budget,
            min_dte=settings.paper_wave_min_dte,
            max_dte=settings.paper_wave_max_dte,
        )
        if spec is None:
            skipped.append({"ticker": target, "reason": reason})
            continue

        per_contract = spec.net_debit * 100
        contracts = int(budget // per_contract) if per_contract > 0 else 0
        contracts = min(contracts, settings.paper_max_contracts)
        if contracts < 1:
            skipped.append(
                {
                    "ticker": target,
                    "reason": f"debit too rich (${per_contract:.0f}/ct vs ${budget:.0f})",
                }
            )
            continue

        trade = _record_wave_trade(db, sig, spec, tgt_date, contracts, equity)
        if dry_run:
            logger.info(
                "[dry-run] WAVE %s %s spread x%d @ debit %.2f (trigger %s)",
                target, spec.option_type, contracts, spec.net_debit, sig.get("trigger"),
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
        if limit is None:
            trade.status = "canceled"
            trade.note = "skipped: market too wide to trade"
            skipped.append({"ticker": target, "reason": "market too wide (illiquid)"})
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
            client, close_legs, is_credit=True, mid=exit_value, settings=settings,
            quotes=quotes, aggressive=False,
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
    # Stop: underlying gave back the post-earnings move (broken thesis). Two
    # guards stop this from whipsawing a fresh entry to a loss (what churned
    # JEF/WOR): (1) don't stop on the entry day — give the thesis a session, and
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
        if limit is None:
            trade.status = "canceled"
            trade.note = "skipped: market too wide to trade"
            skipped.append({"ticker": ticker, "reason": "market too wide (illiquid)"})
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


# --- reddit (social sentiment) strategy --------------------------------------

_CONVICTION_RANK = {"low": 0, "medium": 1, "high": 2}
_PUMP_RANK = {"low": 0, "medium": 1, "high": 2}


def _manage_reddit_exits(
    db: Session, client: AlpacaClient, settings, dry_run: bool
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
            if _manage_one_equity_exit(db, client, t, settings, dry_run):
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
        reason = _reddit_exit_reason(db, t, exit_value, today, settings)
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
        limit = _marketable_net(
            client, close_legs, is_credit=True, mid=exit_value, settings=settings,
            quotes=quotes, aggressive=False,
        )
        try:
            order = client.submit_mleg(
                legs=close_legs,
                qty=t.contracts or 1,
                limit_price=limit,
                client_order_id=f"{t.signal_id}-x",
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
    db: Session, t: PaperTrade, exit_value: float, today: date, settings
) -> str | None:
    # Time exit: this is a momentum day-trade — we ride the Reddit wave for only
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
    # Sentiment reversal/collapse: don't whipsaw on the entry day — give the
    # thesis a session — then bail if the freshest signal flipped against us,
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


def _reddit_equity_exit_reason(t: PaperTrade, spot_now: float, settings) -> str | None:
    """Same intraday clock as the options twin, but the take-profit / stop are
    measured on the underlying's move (there's no spread to value)."""
    if t.opened_at:
        held_hours = (datetime.utcnow() - t.opened_at).total_seconds() / 3600.0
        if held_hours >= settings.paper_reddit_hold_hours:
            return "hold window elapsed"
    if not t.spot_entry:
        return None
    move = spot_now / t.spot_entry - 1.0  # signed underlying move since entry
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
    db: Session, client: AlpacaClient, t: PaperTrade, settings, dry_run: bool
) -> bool:
    """Close a Reddit equity twin (market order) on time or a %-move TP/SL."""
    spot_now = client.stock_price(t.ticker)
    if not spot_now:
        return False
    reason = _reddit_equity_exit_reason(t, spot_now, settings)
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
            client_order_id=f"{t.signal_id}-x",
        )
    except AlpacaError as e:
        logger.error("Equity close failed for %s: %s", t.signal_id, e)
        return False
    t.exit_order_id = order.get("id")
    t.exit_debit = round(spot_now, 2)  # price per share on close (provisional)
    t.status = "closing"
    t.note = reason
    t.spot_at_exit = round(spot_now, 2)
    if t.spot_entry:
        t.realized_move_pct = round(spot_now / t.spot_entry - 1, 4)
    _finalize_pnl(t)
    return True


def _scan_reddit_entries(
    db: Session, client: AlpacaClient, equity: float, settings, dry_run: bool
) -> tuple[int, list]:
    if not settings.paper_reddit_enabled:
        logger.info("reddit scan: disabled (paper_reddit_enabled=False)")
        return 0, []
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
        if sig.get("is_noise"):
            skipped.append({"ticker": ticker, "reason": "noise (no clear lean)"})
            continue
        if sig.get("direction") not in ("bullish", "bearish"):
            skipped.append({"ticker": ticker, "reason": "no directional lean"})
            continue
        if _CONVICTION_RANK.get(sig.get("conviction"), 0) < min_conv:
            skipped.append(
                {"ticker": ticker, "reason": f"conviction too low ({sig.get('conviction')})"}
            )
            continue
        # Anti-pump guard: refuse anything at/above the pump-risk ceiling so we're
        # never late-stage exit liquidity.
        if _PUMP_RANK.get(sig.get("pump_risk"), 0) > max_pump:
            skipped.append(
                {"ticker": ticker, "reason": f"pump risk too high ({sig.get('pump_risk')})"}
            )
            continue

        # One open trade per ticker at a time (re-entry allowed after it closes).
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

        risk_frac = settings.paper_reddit_risk_fraction(reddit_conviction(sig))
        budget = equity * risk_frac
        spec, reason = build_reddit_spec(client, sig, risk_budget=budget)
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

        trade = _record_reddit_trade(db, sig, spec, contracts, equity)
        if dry_run:
            logger.info(
                "[dry-run] REDDIT %s %s spread x%d @ debit %.2f (%s, %.1fx, %s)",
                ticker, spec.option_type, contracts, spec.net_debit,
                sig.get("conviction"), sig.get("mention_velocity") or 0,
                sig.get("scored_by"),
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
        if limit is None:
            trade.status = "canceled"
            trade.note = "skipped: market too wide to trade"
            skipped.append({"ticker": ticker, "reason": "market too wide (illiquid)"})
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
            continue
        trade.entry_order_id = order.get("id")
        _apply_entry_fill(trade, order)
        opened += 1
        _open_reddit_equity_twin(db, client, sig, trade, settings)

    if not dry_run:
        db.commit()
    return opened, skipped


def _open_reddit_equity_twin(
    db: Session, client: AlpacaClient, sig: dict, option_trade: PaperTrade, settings
) -> None:
    """Alongside the options spread, open a stock position on the same name and
    direction (short for bearish), sized to the same dollar risk as the spread —
    an A/B twin to see whether the shares beat the options on the same signal."""
    if not settings.paper_reddit_equity_twin_enabled:
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
