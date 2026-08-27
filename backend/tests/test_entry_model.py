"""Unit tests for the fitted logistic entry model.

Runnable without pytest (``python tests/test_entry_model.py`` from the backend
dir) and also collectable by pytest. In-memory SQLite; no Alpaca/LLM needed.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.models import Base, Company, PaperTrade, PriceBar, TradeDecision  # noqa: E402
from app.services.paper.calibration import compute_calibration  # noqa: E402
from app.services.paper.decisions import attach_context_features  # noqa: E402
from app.services.paper.entry_model import (  # noqa: E402
    fit_entry_model,
    predict_win_prob,
    resolve_entry_probability,
)


@dataclass
class FakeSettings:
    paper_entry_model_enabled: bool = True
    paper_entry_model_min_samples: int = 30
    paper_entry_model_min_class: int = 8
    paper_entry_model_min_prob: float = 0.45
    paper_entry_model_min_auc: float = 0.52
    paper_calibration_enabled: bool = True
    paper_calibration_min_samples: int = 10
    paper_calibration_max_delta: float = 0.15


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _row(i, *, win, market_cap, dollar_volume, dir_score, win_prob=0.55, **kw):
    return TradeDecision(
        decision_date=date(2026, 6, 1),
        strategy=kw.get("strategy", "earnings_equity"),
        ticker=f"T{i}",
        decision="opened",
        label_status="final",
        realized_pnl=100.0 if win else -100.0,
        outcome="win" if win else "loss",
        market_cap=market_cap,
        dollar_volume=dollar_volume,
        avg_volume=dollar_volume / 50.0,
        dir_score=dir_score,
        win_prob=win_prob,
        expected_move_pct=kw.get("expected_move_pct", 0.06),
        richness=kw.get("richness", 1.3),
        direction=kw.get("direction", "bullish"),
        conviction=kw.get("conviction", "high"),
        spot=50.0,
    )


def _seed_separable(db, n=40):
    """Wins cluster on large-cap + heavy dollar-volume + positive dir_score."""
    for i in range(n):
        win = i < n // 2
        db.add(_row(
            i,
            win=win,
            market_cap=80e9 if win else 3e9,
            dollar_volume=5e8 if win else 8e6,
            dir_score=2.4 if win else -0.4,
            win_prob=0.7 if win else 0.45,
        ))
    db.commit()


def test_disabled_is_not_applicable():
    db = _session()
    _seed_separable(db)
    model = fit_entry_model(db, FakeSettings(paper_entry_model_enabled=False))
    assert model.applicable is False
    assert model.reason == "disabled"


def test_too_few_samples_is_not_applicable():
    db = _session()
    _seed_separable(db, n=16)  # below min_samples=30
    model = fit_entry_model(db, FakeSettings())
    assert model.applicable is False
    assert "need 30" in model.reason


def test_one_sided_book_is_not_applicable():
    db = _session()
    for i in range(32):
        db.add(_row(
            i, win=True, market_cap=50e9, dollar_volume=1e8, dir_score=2.0,
        ))
    db.commit()
    model = fit_entry_model(db, FakeSettings())
    assert model.applicable is False
    assert "wins and losses" in model.reason


def test_fit_learns_size_and_history_and_scores_new_names():
    db = _session()
    _seed_separable(db, n=40)
    model = fit_entry_model(db, FakeSettings())
    assert model.applicable is True
    assert model.n == 40
    assert model.cv_auc is not None and model.cv_auc >= 0.7
    # Size / history should carry positive weight (bigger/more-liquid/better
    # prior → more likely to win in this synthetic book).
    by_feat = {c["feature"]: c["weight"] for c in model.coefficients}
    assert by_feat.get("log_market_cap", 0) > 0
    assert by_feat.get("log_dollar_volume", 0) > 0
    assert by_feat.get("dir_score", 0) > 0

    good = {
        "strategy": "earnings_equity",
        "direction": "bullish",
        "conviction": "high",
        "market_cap": 90e9,
        "dollar_volume": 6e8,
        "dir_score": 2.5,
        "win_prob": 0.72,
        "expected_move_pct": 0.06,
        "richness": 1.3,
    }
    bad = {
        **good,
        "market_cap": 2.5e9,
        "dollar_volume": 5e6,
        "dir_score": -0.8,
        "win_prob": 0.4,
    }
    p_good = predict_win_prob(model, good, "earnings_equity")
    p_bad = predict_win_prob(model, bad, "earnings_equity")
    assert p_good is not None and p_bad is not None
    assert p_good > p_bad
    assert p_good > 0.55
    assert p_bad < 0.5


def test_resolve_vetoes_below_floor_and_falls_back_when_unfit():
    db = _session()
    _seed_separable(db, n=40)
    model = fit_entry_model(db, FakeSettings(paper_entry_model_min_prob=0.45))
    assert model.applicable is True
    weak = {
        "strategy": "earnings_equity",
        "direction": "bullish",
        "conviction": "high",
        "market_cap": 2e9,
        "dollar_volume": 4e6,
        "dir_score": -1.2,
        "win_prob": 0.42,
    }
    gate_p, skip, model_p = resolve_entry_probability(
        0.7, weak, "earnings_equity", model, {}, FakeSettings(),
    )
    assert skip is not None and skip.startswith("model reject")
    assert gate_p is None
    assert model_p is not None and model_p < 0.45

    # Unfit model → calibrated heuristic, no veto.
    thin = _session()
    stub = fit_entry_model(thin, FakeSettings())
    assert stub.applicable is False
    calib = compute_calibration(thin, FakeSettings())
    gate_p, skip, model_p = resolve_entry_probability(
        0.6, {"win_prob": 0.6}, "earnings", stub, calib, FakeSettings(),
    )
    assert skip is None
    assert gate_p == 0.6
    assert model_p is None


def test_attach_context_fills_market_cap_and_adv_from_bars():
    db = _session()
    db.add(Company(ticker="ABC", name="Abc", market_cap=12_000_000_000))
    for i in range(20):
        db.add(PriceBar(
            ticker="ABC", date=date(2026, 7, 1 + i % 28),
            close=40.0, volume=1_000_000 + i * 1000,
        ))
    db.commit()
    feats = attach_context_features(db, "ABC", {"spot": 40.0})
    assert feats["market_cap"] == 12_000_000_000
    assert feats["avg_volume"] is not None and feats["avg_volume"] > 0
    assert feats["dollar_volume"] == round(feats["avg_volume"] * 40.0, 2)
    assert feats["rel_volume"] is not None


def _closed_paper(i, *, win: bool) -> tuple[Company, PriceBar, PaperTrade]:
    ticker = f"P{i}"
    company = Company(ticker=ticker, market_cap=80e9 if win else 3e9)
    bar = PriceBar(
        ticker=ticker, date=date(2026, 6, 1), close=50.0,
        volume=10_000_000 if win else 200_000,
    )
    trade = PaperTrade(
        signal_id=f"EE-{i}",
        strategy="earnings",
        ticker=ticker,
        structure="Long shares",
        direction="bullish",
        vol_stance="neutral",
        conviction="high",
        status="closed",
        realized_pnl=80.0 if win else -80.0,
        outcome="win" if win else "loss",
        spot_entry=50.0,
        expected_move_pct=0.06,
        thesis=json.dumps({
            "conviction_basis": {
                "dir_score": 2.4 if win else -0.4,
                "seller_edge": 0.7 if win else 0.45,
                "richness": 1.3,
            }
        }),
    )
    return company, bar, trade


def test_fits_from_closed_paper_trades_with_no_decision_journal():
    """The closed book is the grade — we don't wait for trade_decisions rows."""
    db = _session()
    for i in range(40):
        company, bar, trade = _closed_paper(i, win=i < 20)
        db.add_all([company, bar, trade])
    db.commit()
    assert db.query(TradeDecision).count() == 0
    model = fit_entry_model(db, FakeSettings())
    assert model.applicable is True
    assert model.n == 40
    assert model.cv_auc is not None and model.cv_auc >= 0.7


def test_paper_trades_and_decision_rows_are_not_double_counted():
    db = _session()
    for i in range(40):
        win = i < 20
        company, bar, trade = _closed_paper(i, win=win)
        db.add_all([company, bar, trade])
        td = _row(
            i, win=win, market_cap=80e9 if win else 3e9,
            dollar_volume=5e8 if win else 8e6,
            dir_score=2.4 if win else -0.4,
        )
        td.signal_id = f"EE-{i}"
        db.add(td)
    db.commit()
    model = fit_entry_model(db, FakeSettings())
    assert model.n == 40


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
