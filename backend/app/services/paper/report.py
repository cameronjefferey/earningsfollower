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

# Only orders that actually filled count as tracked positions. A "pending"
# trade is a submitted-but-unfilled order; if it never fills it's canceled and
# never shows here. So the scorecard's "open" = filled & live (open/closing).
DISPLAY_OPEN = ("open", "closing")


def _thesis_data(t: PaperTrade) -> dict:
    try:
        return json.loads(t.thesis or "{}") or {}
    except json.JSONDecodeError:
        return {}


def _thesis_subreddits(t: PaperTrade) -> list[str]:
    """Which subreddits the chatter behind a reddit trade came from (empty for
    other strategies), so we can track which communities actually pay off."""
    if (t.strategy or "") != "reddit":
        return []
    subs = _thesis_data(t).get("subreddits") or []
    return [str(s) for s in subs if s]


def _thesis_headline(t: PaperTrade) -> str | None:
    data = _thesis_data(t)
    if not data:
        return None
    strategy = t.strategy or "earnings"
    if strategy == "waves":
        trig = data.get("trigger")
        if not trig:
            return None
        rr = data.get("expected_runup_pct")
        drift = f"{rr * 100:+.1f}% drift" if isinstance(rr, (int, float)) else "sympathy drift"
        return f"Rides {trig} · {drift} into its print"
    if strategy == "drift":
        edge = data.get("edge_5d")
        wr = data.get("win_rate")
        dir_word = "higher" if t.direction == "bullish" else "lower"
        edge_txt = f"{abs(edge) * 100:.1f}% avg drift" if isinstance(edge, (int, float)) else "post-earnings drift"
        wr_txt = f", {wr * 100:.0f}% of the time" if isinstance(wr, (int, float)) else ""
        return f"Post-earnings drift {dir_word} · {edge_txt}{wr_txt}"
    if strategy == "reddit":
        vel = data.get("mention_velocity")
        mentions = data.get("mention_count")
        dir_word = "bullish" if t.direction == "bullish" else "bearish"
        vel_txt = f"{vel:.0f}x" if isinstance(vel, (int, float)) else "spiking"
        cnt_txt = f"{mentions} mentions" if isinstance(mentions, int) else "Reddit chatter"
        return f"Reddit {dir_word} · {cnt_txt} at {vel_txt} baseline"
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
        "subreddits": _thesis_subreddits(t),
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "note": t.note,
    }


def scorecard(db: Session, include_account: bool = True) -> dict:
    trades = db.scalars(select(PaperTrade).order_by(PaperTrade.id.desc())).all()

    open_trades = [_trade_dict(t) for t in trades if t.status in DISPLAY_OPEN]

    # One Alpaca client for both live prices and the account fetch.
    client = None
    try:
        c = AlpacaClient()
        if c.enabled:
            client = c
    except Exception as e:  # noqa: BLE001 - never let client init break the page
        logger.warning("Could not init Alpaca client: %s", e)

    # Mark each open position with the *live* underlying price so the payoff
    # chart updates on every page load. Fall back to the latest daily close when
    # the live quote isn't available (market data hiccup / no subscription).
    for d in open_trades:
        px = None
        if client is not None:
            try:
                px = client.stock_price(d["ticker"])
            except Exception:  # noqa: BLE001 - fall back to the daily bar
                px = None
        if px is None:
            bar = db.scalars(
                select(PriceBar)
                .where(PriceBar.ticker == d["ticker"])
                .order_by(PriceBar.date.desc())
            ).first()
            if bar and bar.close is not None:
                px = bar.close
        if px is not None:
            d["spot_now"] = round(px, 2)

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
            k = getattr(t, key) or "-"
            b = out.setdefault(k, {"n": 0, "pnl": 0.0, "wins": 0})
            b["n"] += 1
            b["pnl"] = round(b["pnl"] + t.realized_pnl, 2)
            if t.realized_pnl > 0:
                b["wins"] += 1
        return out

    def _reddit_instrument_bucket() -> dict:
        """Split closed Reddit trades into equity vs options so we can see which
        instrument actually captured the momentum on the same signals."""
        out: dict[str, dict] = {}
        for t in closed:
            if (t.strategy or "") != "reddit" or t.realized_pnl is None:
                continue
            k = "equity" if (t.structure or "") in ("Long shares", "Short shares") else "options"
            b = out.setdefault(k, {"n": 0, "pnl": 0.0, "wins": 0})
            b["n"] += 1
            b["pnl"] = round(b["pnl"] + t.realized_pnl, 2)
            if t.realized_pnl > 0:
                b["wins"] += 1
        return out

    def _earnings_instrument_bucket() -> dict:
        """Split closed earnings trades into equity vs options so we can see
        which instrument won on the same directional earnings signals."""
        out: dict[str, dict] = {}
        for t in closed:
            if (t.strategy or "earnings") != "earnings" or t.realized_pnl is None:
                continue
            k = "equity" if (t.structure or "") in ("Long shares", "Short shares") else "options"
            b = out.setdefault(k, {"n": 0, "pnl": 0.0, "wins": 0})
            b["n"] += 1
            b["pnl"] = round(b["pnl"] + t.realized_pnl, 2)
            if t.realized_pnl > 0:
                b["wins"] += 1
        return out

    def _subreddit_bucket() -> dict:
        """Attribute each closed reddit trade's P&L to every subreddit that fed
        its signal, so we can see which communities are actually profitable."""
        out: dict[str, dict] = {}
        for t in closed:
            if (t.strategy or "") != "reddit" or t.realized_pnl is None:
                continue
            for s in _thesis_subreddits(t):
                b = out.setdefault(s, {"n": 0, "pnl": 0.0, "wins": 0})
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
            sum(t.max_risk or 0 for t in trades if t.status in DISPLAY_OPEN), 2
        ),
        "by_structure": _bucket("structure"),
        "by_direction": _bucket("direction"),
        "by_conviction": _bucket("conviction"),
        "by_strategy": _bucket("strategy"),
        "by_subreddit": _subreddit_bucket(),
        "by_reddit_instrument": _reddit_instrument_bucket(),
        "by_earnings_instrument": _earnings_instrument_bucket(),
    }

    account = None
    if include_account and client is not None:
        try:
            acct = client.account()
            account = {
                "equity": _f(acct.get("equity")),
                "cash": _f(acct.get("cash")),
                "buying_power": _f(acct.get("buying_power")),
                "status": acct.get("status"),
            }
        except Exception as e:  # noqa: BLE001 - never let account fetch break the page
            logger.warning("Could not fetch Alpaca account: %s", e)

    if client is not None:
        client.close()

    last_run = None
    try:
        from app.services.job_runs import job_run_payload, latest_job_run

        last_run = job_run_payload(latest_job_run(db, "paper"))
    except Exception as e:  # noqa: BLE001 - never let health status break the page
        logger.warning("Could not load last paper run: %s", e)

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "account": account,
        "stats": stats,
        "open": open_trades,
        "closed": closed_dicts,
        "last_run": last_run,
    }


def _f(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
