"""Read-only impact report for widening ``paper_entry_window_days``.

Simulates the earnings sell-vol entry scan at one or more candidate windows
WITHOUT submitting any orders or writing to the database, so we can see which
names a wider window would newly surface -- and, critically, whether each of
those names would actually clear the guardrails or just get rejected the same
way the in-window names are today.

It reuses the exact production decision path -- ``company_detail`` (the
playbook), ``build_trade_spec`` (the width-fitting / credit-ratio search), and
``_gate_entry`` (the marketable-cross economics gate) -- so the verdicts match
what the live trader in ``app.services.paper.executor`` would do. Alpaca is used
only for option quotes; no order is ever placed.

Per-name eligibility only: portfolio-state checks that the live scan also applies
(max open positions, one-trade-per-ticker, per-run dedupe) are intentionally
skipped here, since the question is "which names *could* trade at a wider
window", not "which would fill given today's book".

Examples:
    python -m app.research.entry_window_impact                 # windows 7, 14
    python -m app.research.entry_window_impact --windows 7,10,14
    python -m app.research.entry_window_impact --equity 100000
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select

from app.clients.alpaca import AlpacaClient
from app.config import get_settings
from app.db.models import EarningsEvent
from app.db.session import SessionLocal
from app.services.dashboard import company_detail
from app.services.paper.contracts import build_trade_spec
from app.services.paper.executor import SELLING_STRUCTURES, _gate_entry

FLAG_TICKERS = {"MXL"}  # names to always call out in the output


@dataclass
class Decision:
    ticker: str
    report_date: date
    days_out: int
    structure: str | None
    conviction: str | None
    would_open: bool
    reason: str


def _evaluate(
    db, client: AlpacaClient, equity: float, settings, ticker: str, ev_date: date
) -> tuple[bool, str, str | None, str | None]:
    """Return (would_open, reason, structure, conviction) for one name, mirroring
    the per-name path of ``_scan_entries`` up to and including the entry gate."""
    detail = company_detail(db, ticker)
    pb = (detail or {}).get("playbook")
    if not pb:
        return False, "no playbook", None, None

    structure = pb.get("structure")
    conviction = pb.get("conviction")
    if pb["vol_stance"] != "sell" or pb["structure"] not in SELLING_STRUCTURES:
        return False, f"not a sell-vol setup ({structure})", structure, conviction

    risk_frac = settings.paper_risk_fraction(conviction)
    budget = equity * risk_frac

    spec, reason = build_trade_spec(
        client, ticker, pb, ev_date,
        risk_budget=budget,
        min_credit_ratio=settings.paper_min_credit_width_ratio,
    )
    if spec is None:
        return False, reason, structure, conviction
    if spec.net_credit < settings.paper_min_credit:
        return False, f"credit too thin ({spec.net_credit})", structure, conviction

    contracts = min(
        int(budget // spec.max_risk_per_contract) if spec.max_risk_per_contract else 0,
        settings.paper_max_contracts,
    )
    if contracts < 1:
        return (
            False,
            f"spread too wide for {conviction} budget "
            f"({risk_frac:.1%}=${budget:.0f}; risk ${spec.max_risk_per_contract:.0f}/ct)",
            structure,
            conviction,
        )

    order_legs = [
        {
            "symbol": l.symbol,
            "ratio_qty": "1",
            "side": l.side,
            "position_intent": l.position_intent,
        }
        for l in spec.legs
    ]
    # Match the live gate: use the win-probability recomputed at the (closer)
    # short strike we actually sell, falling back to the full-move seller edge.
    basis = pb.get("conviction_basis") or {}
    win_prob = basis.get("seller_edge_at_strike") or basis.get("seller_edge")
    limit, greason = _gate_entry(
        client, order_legs, is_credit=True, mid=spec.net_credit,
        width=spec.width, win_prob=win_prob, settings=settings,
    )
    if limit is None:
        return False, greason or "gate rejected", structure, conviction

    return (
        True,
        f"WOULD OPEN (credit {spec.net_credit:.2f} on {spec.width:.0f}-wide x{contracts})",
        structure,
        conviction,
    )


def _collect(max_window: int, equity: float | None) -> list[Decision]:
    """Evaluate every unique name reporting within the largest window once."""
    settings = get_settings()
    today = date.today()
    window_end = today + timedelta(days=max_window)

    decisions: list[Decision] = []
    with SessionLocal() as db:
        client = AlpacaClient()
        if not client.enabled:
            print(
                "WARNING: Alpaca credentials not configured -- spread/gate checks "
                "cannot run; only playbook-level verdicts will be accurate.\n"
            )
        eq = equity if equity is not None else (client.equity() if client.enabled else 100_000.0)
        print(f"Account equity used for sizing: ${eq:,.0f}\n")

        events = db.scalars(
            select(EarningsEvent)
            .where(EarningsEvent.date >= today, EarningsEvent.date <= window_end)
            .order_by(EarningsEvent.date.asc())
        ).all()

        seen: set[str] = set()
        for ev in events:
            if ev.ticker in seen:
                continue
            seen.add(ev.ticker)
            would_open, reason, structure, conviction = _evaluate(
                db, client, eq, settings, ev.ticker, ev.date
            )
            decisions.append(
                Decision(
                    ticker=ev.ticker,
                    report_date=ev.date,
                    days_out=(ev.date - today).days,
                    structure=structure,
                    conviction=conviction,
                    would_open=would_open,
                    reason=reason,
                )
            )
        client.close()
    return decisions


def _print_table(rows: list[Decision]) -> None:
    if not rows:
        print("  (none)")
        return
    for d in sorted(rows, key=lambda r: (not r.would_open, r.days_out, r.ticker)):
        mark = "OPEN " if d.would_open else "skip "
        flag = " *" if d.ticker in FLAG_TICKERS else "  "
        conv = (d.conviction or "-")[:6]
        struct = (d.structure or "-")[:28]
        print(
            f"  {mark}{flag}{d.ticker:<6} {d.report_date} "
            f"({d.days_out:>2}d) {conv:<6} {struct:<28} {d.reason}"
        )


def _report(windows: list[int], decisions: list[Decision]) -> None:
    baseline = min(windows)
    for w in windows:
        in_window = [d for d in decisions if 0 <= d.days_out <= w]
        opens = [d for d in in_window if d.would_open]
        print("=" * 100)
        print(f"WINDOW = {w} days  |  {len(in_window)} names reporting in range, "
              f"{len(opens)} would open, {len(in_window) - len(opens)} gated")
        print("=" * 100)

        if w == baseline:
            print(f"\nAll names within {w}d:")
            _print_table(in_window)
        else:
            already = [d for d in in_window if d.days_out <= baseline]
            newly = [d for d in in_window if d.days_out > baseline]
            new_opens = [d for d in newly if d.would_open]
            print(f"\nAlready in the {baseline}d window ({len(already)}):")
            _print_table(already)
            print(f"\nNewly added by widening {baseline}d -> {w}d "
                  f"({len(newly)} names, {len(new_opens)} would actually open):")
            _print_table(newly)
        print()

    flagged = [d for d in decisions if d.ticker in FLAG_TICKERS]
    if flagged:
        print("-" * 100)
        print("Flagged names:")
        _print_table(flagged)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only impact report for widening the earnings entry window."
    )
    parser.add_argument(
        "--windows",
        default="7,14",
        help="Comma-separated candidate windows in days (default: 7,14).",
    )
    parser.add_argument(
        "--equity",
        type=float,
        default=None,
        help="Override account equity for sizing (default: live Alpaca equity).",
    )
    args = parser.parse_args()

    windows = sorted({int(w) for w in args.windows.split(",") if w.strip()})
    if not windows:
        parser.error("provide at least one window, e.g. --windows 7,14")

    decisions = _collect(max(windows), args.equity)
    _report(windows, decisions)


if __name__ == "__main__":
    main()
