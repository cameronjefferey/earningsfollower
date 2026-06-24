"""Read-side: assemble the paper-trading scorecard for the API/UI."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.alpaca import AlpacaClient
from app.db.models import PaperTrade, PriceBar

logger = logging.getLogger(__name__)

OPEN_STATES = ("pending", "open", "closing")


def _thesis_headline(t: PaperTrade) -> str | None:
    try:
        data = json.loads(t.thesis or "{}") or {}
    except json.JSONDecodeError:
        return None
    if (t.strategy or "earnings") == "waves":
        trig = data.get("trigger")
        if not trig:
            return None
        rr = data.get("expected_runup_pct")
        drift = f"{rr * 100:+.1f}% drift" if isinstance(rr, (int, float)) else "sympathy drift"
        return f"Rides {trig} · {drift} into its print"
    return data.get("headline")


def _trade_dict(t: PaperTrade) -> dict:
    return {
        "signal_id": t.signal_id,
        "strategy": t.strategy or "earnings",
        "ticker": t.ticker,
        "structure": t.structure,
        "direction": t.direction,
        "conviction": t.conviction,
        "status": t.status,
        "contracts": t.contracts,
        "earnings_date": t.earnings_date.isoformat() if t.earnings_date else None,
        "expiration": t.expiration.isoformat() if t.expiration else None,
        "width": t.width,
        "entry_credit": t.entry_credit,
        "modeled_credit": t.modeled_credit,
        "exit_debit": t.exit_debit,
        "max_risk": t.max_risk,
        "realized_pnl": t.realized_pnl,
        "expected_move_pct": t.expected_move_pct,
        "spot_entry": t.spot_entry,
        "spot_now": None,  # filled in for open trades from the latest price bar
        "spot_at_exit": t.spot_at_exit,
        "realized_move_pct": t.realized_move_pct,
        "breached_short": t.breached_short,
        "outcome": t.outcome,
        "legs": json.loads(t.legs or "[]"),
        "thesis": _thesis_headline(t),
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "note": t.note,
    }


def scorecard(db: Session, include_account: bool = True) -> dict:
    trades = db.scalars(select(PaperTrade).order_by(PaperTrade.id.desc())).all()

    open_trades = [_trade_dict(t) for t in trades if t.status in OPEN_STATES]
    # Mark each open position with the current underlying price (latest daily
    # close) so the UI can show where the stock sits in the profit zone now.
    for d in open_trades:
        bar = db.scalars(
            select(PriceBar)
            .where(PriceBar.ticker == d["ticker"])
            .order_by(PriceBar.date.desc())
        ).first()
        if bar and bar.close is not None:
            d["spot_now"] = round(bar.close, 2)

    closed = [t for t in trades if t.status == "closed"]
    closed_dicts = [_trade_dict(t) for t in closed]

    pnls = [t.realized_pnl for t in closed if t.realized_pnl is not None]
    wins = [p for p in pnls if p > 0]
    total_pnl = round(sum(pnls), 2) if pnls else 0.0

    def _bucket(key: str) -> dict:
        out: dict[str, dict] = {}
        for t in closed:
            if t.realized_pnl is None:
                continue
            k = getattr(t, key) or "—"
            b = out.setdefault(k, {"n": 0, "pnl": 0.0, "wins": 0})
            b["n"] += 1
            b["pnl"] = round(b["pnl"] + t.realized_pnl, 2)
            if t.realized_pnl > 0:
                b["wins"] += 1
        return out

    stats = {
        "open_count": len(open_trades),
        "closed_count": len(closed),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(pnls), 3) if pnls else None,
        "total_pnl": total_pnl,
        "avg_pnl": round(total_pnl / len(pnls), 2) if pnls else None,
        "open_risk": round(
            sum(t.max_risk or 0 for t in trades if t.status in OPEN_STATES), 2
        ),
        "by_structure": _bucket("structure"),
        "by_direction": _bucket("direction"),
        "by_conviction": _bucket("conviction"),
    }

    account = None
    if include_account:
        try:
            client = AlpacaClient()
            if client.enabled:
                acct = client.account()
                account = {
                    "equity": _f(acct.get("equity")),
                    "cash": _f(acct.get("cash")),
                    "buying_power": _f(acct.get("buying_power")),
                    "status": acct.get("status"),
                }
            client.close()
        except Exception as e:  # noqa: BLE001 - never let account fetch break the page
            logger.warning("Could not fetch Alpaca account: %s", e)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "account": account,
        "stats": stats,
        "open": open_trades,
        "closed": closed_dicts,
    }


def _f(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
