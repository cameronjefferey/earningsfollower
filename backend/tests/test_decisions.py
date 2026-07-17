"""Unit tests for the trade-decision feature/label store.

Runnable without pytest (``python tests/test_decisions.py`` from the backend
dir) and also collectable by pytest. Uses an in-memory SQLite DB and lightweight
fakes so no Alpaca connection is needed.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, PaperTrade, PriceBar, TradeDecision  # noqa: E402
from app.services.paper.decisions import (  # noqa: E402
    PLAYBOOK_VERSION,
    drift_features,
    earnings_features,
    features_from_paper_trade,
    reddit_features,
    record_decision,
    regime_snapshot,
    sync_labels,
    wave_features,
)


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@dataclass
class FakeSpec:
    width: float = 5.0
    net_credit: float | None = None
    net_debit: float | None = None
    max_risk_per_contract: float | None = None
    spot: float | None = None


# --- feature builders --------------------------------------------------------


def test_earnings_features_promote_conviction_basis():
    """Every numeric that set conviction is promoted to a typed column, and the
    win_prob is the strike-level seller edge (the honest EV input)."""
    pb = {
        "direction": "bearish",
        "vol_stance": "sell",
        "structure": "Bear call (call credit) spread",
        "conviction": "high",
        "spot": 100.0,
        "conviction_basis": {
            "exceed_rate": 0.2,
            "seller_edge": 0.8,
            "seller_edge_at_strike": 0.7,
            "edge_sample": 12,
            "richness": 1.4,
            "dir_score": -1.5,
            "data_suspect": False,
            "tier_reason": "seller edge 80% (n=12)",
        },
    }
    im = {"expected_move_pct": 0.08, "underlying_price": 101.0}
    spec = FakeSpec(width=5.0, net_credit=1.2, max_risk_per_contract=380.0)
    feats = earnings_features(pb, im, spec=spec, contracts=2, risk_frac=0.05, equity=100_000)
    assert feats["direction"] == "bearish"
    assert feats["win_prob"] == 0.7  # strike-level, not the full-move 0.8
    assert feats["seller_edge"] == 0.8
    assert feats["edge_sample"] == 12
    assert feats["expected_move_pct"] == 0.08
    assert feats["spot"] == 101.0  # implied-move underlying wins over pb spot
    assert feats["modeled_price"] == 1.2
    assert feats["max_risk"] == 760.0  # 380 * 2
    assert feats["contracts"] == 2


def test_wave_and_drift_features_map_history_to_win_prob():
    wsig = {
        "direction": "bullish",
        "trigger": "NVDA",
        "trigger_move_pct": 0.06,
        "expected_runup_pct": 0.03,
        "stats": {"win_rate": 0.7, "sample_size": 6},
    }
    wf = wave_features(wsig, conviction="medium", spec=FakeSpec(net_debit=1.5, spot=50), contracts=3)
    assert wf["win_prob"] == 0.7 and wf["hist_samples"] == 6
    assert wf["modeled_price"] == 1.5 and wf["max_risk"] == 1.5 * 100 * 3

    setup = {
        "direction": "long",
        "surprise_pct": 0.1,
        "move_pct": 0.05,
        "score": 2.0,
        "history": {"avg_drift_5d_pct": 0.02, "win_rate_5d": 0.65, "sample_size": 8},
    }
    df = drift_features(setup, conviction="high")
    assert df["direction"] == "bullish"
    assert df["drift_edge_5d"] == 0.02 and df["win_prob"] == 0.65
    assert df["hist_samples"] == 8


def test_reddit_features_carry_social_signal():
    sig = {
        "direction": "bullish",
        "conviction": "high",
        "sentiment": 0.6,
        "mention_count": 120,
        "mention_velocity": 4.2,
        "pump_risk": "low",
        "scored_by": "llm",
    }
    rf = reddit_features(sig, conviction="high", win_prob=0.55)
    assert rf["mention_velocity"] == 4.2 and rf["pump_risk"] == "low"
    assert rf["structure"] == "Bull call spread"
    assert rf["win_prob"] == 0.55


# --- recording ---------------------------------------------------------------


def test_record_decision_persists_typed_columns_and_json():
    db = _session()
    pb = {
        "direction": "bullish", "vol_stance": "sell", "structure": "Bull put (put credit) spread",
        "conviction": "medium", "spot": 50.0,
        "conviction_basis": {"seller_edge": 0.7, "edge_sample": 9, "tier_reason": "x"},
    }
    row = record_decision(
        db, strategy="earnings", ticker="ABC", decision="skipped",
        earnings_date=date(2026, 7, 20), skip_reason="credit too thin (0.05)",
        features=earnings_features(pb, {"expected_move_pct": 0.05}),
        regime={"playbook_version": PLAYBOOK_VERSION, "paper_min_credit": 0.10},
    )
    db.commit()
    assert row is not None
    got = db.scalars(select(TradeDecision)).one()
    assert got.strategy == "earnings" and got.decision == "skipped"
    assert got.conviction == "medium" and got.seller_edge == 0.7
    assert got.skip_reason.startswith("credit too thin")
    assert json.loads(got.regime_json)["paper_min_credit"] == 0.10
    assert json.loads(got.features_json)["direction"] == "bullish"


def test_record_decision_bad_value_does_not_break_the_run():
    """A feature that can't be stored must not raise or poison the session — a
    good decision recorded right after still commits."""
    db = _session()
    # edge_sample is an Integer column; a non-coercible value trips the savepoint.
    bad = record_decision(
        db, strategy="earnings", ticker="BAD", decision="skipped",
        features={"edge_sample": {"not": "an int"}},
    )
    good = record_decision(
        db, strategy="waves", ticker="OK", decision="opened",
        signal_id="WV-1", features={"direction": "bullish"},
    )
    db.commit()
    rows = db.scalars(select(TradeDecision)).all()
    tickers = {r.ticker for r in rows}
    assert "OK" in tickers  # the good row survived regardless of the bad one
    assert good is not None


# --- labels ------------------------------------------------------------------


def test_sync_labels_attaches_outcome_and_multi_horizon_moves():
    db = _session()
    opened_at = datetime(2026, 7, 1, 14, 30)
    ref = opened_at.date()
    # A closed, winning bullish trade entered at 100.
    trade = PaperTrade(
        signal_id="EF-1", strategy="earnings", ticker="XYZ",
        structure="Bull put (put credit) spread", direction="bullish",
        vol_stance="sell", conviction="high", status="closed",
        contracts=1, spot_entry=100.0, opened_at=opened_at,
        realized_pnl=123.0, outcome="win", realized_move_pct=0.05,
        breached_short=False,
    )
    db.add(trade)
    # Price bars after entry: +1d = 102 (+2%), +5d = 110 (+10%).
    closes = [102.0, 103.0, 104.0, 106.0, 110.0]
    for i, c in enumerate(closes, start=1):
        db.add(PriceBar(ticker="XYZ", date=ref + timedelta(days=i), close=c))
    db.add(
        TradeDecision(
            decision_date=ref, strategy="earnings", ticker="XYZ",
            decision="opened", signal_id="EF-1", direction="bullish",
            spot=100.0, label_status="pending",
        )
    )
    db.commit()

    n = sync_labels(db)
    db.commit()
    assert n == 1
    row = db.scalars(select(TradeDecision)).one()
    assert row.label_status == "final"
    assert row.outcome == "win" and row.realized_pnl == 123.0
    assert row.move_1d == 0.02 and row.move_5d == 0.10
    # Bullish: favorable move == raw move.
    assert row.fav_move_1d == 0.02 and row.fav_move_5d == 0.10

    # Idempotent: a second pass finds nothing new to finalize.
    assert sync_labels(db) == 0


def test_sync_labels_direction_adjusts_favorable_move_for_shorts():
    db = _session()
    opened_at = datetime(2026, 7, 1, 14, 30)
    ref = opened_at.date()
    trade = PaperTrade(
        signal_id="EE-1", strategy="earnings", ticker="SHT",
        structure="Short shares", direction="bearish", vol_stance="neutral",
        conviction="high", status="open", contracts=10, spot_entry=100.0,
        opened_at=opened_at,
    )
    db.add(trade)
    for i, c in enumerate([98.0, 97.0, 96.0, 95.0, 90.0], start=1):
        db.add(PriceBar(ticker="SHT", date=ref + timedelta(days=i), close=c))
    db.add(
        TradeDecision(
            decision_date=ref, strategy="earnings_equity", ticker="SHT",
            decision="opened", signal_id="EE-1", direction="bearish",
            spot=100.0, label_status="pending",
        )
    )
    db.commit()
    sync_labels(db)
    db.commit()
    row = db.scalars(select(TradeDecision)).one()
    # Stock fell: raw move negative, but favorable (for a short) is positive.
    assert row.move_5d == -0.10 and row.fav_move_5d == 0.10
    # Still open -> not final yet (no realized P&L to attach).
    assert row.label_status == "pending"


# --- backfill ----------------------------------------------------------------


def test_features_from_paper_trade_roundtrips_thesis():
    t = PaperTrade(
        signal_id="DR-1", strategy="drift", ticker="PEAD",
        structure="Bull call spread", direction="bullish", vol_stance="buy",
        conviction="medium", status="closed", contracts=2, width=5.0,
        modeled_credit=2.0, max_risk=400.0, spot_entry=80.0,
        expected_move_pct=None, equity_at_entry=50_000.0,
        thesis=json.dumps({
            "surprise_pct": 0.12, "move_pct": 0.04, "edge_5d": 0.02,
            "win_rate": 0.6, "samples": 7, "stop_level": 78.0,
        }),
    )
    label, feats = features_from_paper_trade(t)
    assert label == "drift"
    assert feats["surprise_pct"] == 0.12 and feats["drift_edge_5d"] == 0.02
    assert feats["win_prob"] == 0.6 and feats["hist_samples"] == 7
    assert feats["max_risk"] == 400.0

    eq = PaperTrade(
        signal_id="EE-9", strategy="earnings", ticker="TWIN",
        structure="Long shares", direction="bullish", vol_stance="neutral",
        conviction="high", status="open", contracts=5, spot_entry=20.0,
        thesis=json.dumps({"instrument": "equity", "conviction_basis": {"dir_score": 2.0}}),
    )
    label2, feats2 = features_from_paper_trade(eq)
    assert label2 == "earnings_equity"
    assert feats2["dir_score"] == 2.0 and feats2["structure"] == "Long shares"


def test_regime_snapshot_carries_version_and_knobs():
    settings = SimpleNamespace(
        paper_entry_window_days=10, paper_min_credit=0.10, reddit_min_conviction="high",
    )
    snap = regime_snapshot(settings)
    assert snap["playbook_version"] == PLAYBOOK_VERSION
    assert snap["paper_entry_window_days"] == 10
    assert snap["reddit_min_conviction"] == "high"


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
