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
from app.db.models import EarningsEvent, PaperTrade
from app.services.dashboard import company_detail
from app.services.paper.contracts import TradeSpec, build_trade_spec

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

        summary["reconciled"] = _reconcile(db, client, dry_run)
        summary["closed"] = _manage_exits(db, client, dry_run)
        opened, skipped = _scan_entries(db, client, equity, settings, dry_run)
        summary["opened"] = opened
        summary["skipped"] = skipped
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


def _manage_exits(db: Session, client: AlpacaClient, dry_run: bool) -> int:
    """Close open positions once their earnings event has passed."""
    today = date.today()
    closed = 0
    open_trades = db.scalars(
        select(PaperTrade).where(PaperTrade.status == "open")
    ).all()
    for t in open_trades:
        if t.earnings_date and t.earnings_date >= today:
            continue  # event hasn't happened yet
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
            logger.info("[dry-run] would close %s at net %.2f", t.signal_id, exit_net)
            continue
        try:
            order = client.submit_mleg(
                legs=close_legs,
                qty=t.contracts or 1,
                limit_price=max(0.01, exit_net),
                client_order_id=f"{t.signal_id}-x",
            )
        except AlpacaError as e:
            logger.error("Close failed for %s: %s", t.signal_id, e)
            continue
        t.exit_order_id = order.get("id")
        t.exit_debit = exit_net
        t.status = "closing"
        _finalize_pnl(t)  # provisional, refined on fill
        closed += 1
    if not dry_run:
        db.commit()
    return closed


def _finalize_pnl(t: PaperTrade) -> None:
    if t.entry_credit is None or t.exit_debit is None or not t.contracts:
        return
    t.realized_pnl = round((t.entry_credit - t.exit_debit) * 100 * t.contracts, 2)


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

        spec, reason = build_trade_spec(client, ticker, pb, ev.date)
        if spec is None:
            skipped.append({"ticker": ticker, "reason": reason})
            continue
        if spec.net_credit < settings.paper_min_credit:
            skipped.append({"ticker": ticker, "reason": f"credit too thin ({spec.net_credit})"})
            continue

        # Size by the playbook's conviction: risk more when the signals agree.
        risk_frac = settings.paper_risk_fraction(pb["conviction"])
        budget = equity * risk_frac
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

        trade = _record_trade(db, ticker, ev, pb, spec, contracts)

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
        try:
            order = client.submit_mleg(
                legs=order_legs,
                qty=contracts,
                limit_price=max(0.01, spec.net_credit),
                client_order_id=trade.signal_id,
            )
        except AlpacaError as e:
            logger.error("Order failed for %s: %s", ticker, e)
            trade.status = "canceled"
            trade.note = f"submit error: {e}"[:500]
            skipped.append({"ticker": ticker, "reason": f"submit error: {e}"})
            continue
        trade.entry_order_id = order.get("id")
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
) -> PaperTrade:
    signal_id = _next_signal_id(db)
    thesis = {
        "headline": pb.get("headline"),
        "bias_reasons": pb.get("bias_reasons"),
        "vol_reasons": pb.get("vol_reasons"),
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
        max_risk=round(spec.max_risk_per_contract * contracts, 2),
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
