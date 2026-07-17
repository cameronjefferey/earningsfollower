"""Unit tests for the narrator's heuristic fallback (learning loop phase 3).

The LLM path is exercised only when a key is configured; in the test env
``LLMClient.enabled`` is False, so ``build_narrative`` deterministically takes the
heuristic path — which is exactly what we assert here.

Runnable without pytest (``python tests/test_narrator.py``) and via pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper.narrator import build_narrative  # noqa: E402


def _report(**over) -> dict:
    base = {
        "graded_trades": 28,
        "overall": {"n": 28, "wins": 14, "win_rate": 0.5, "total_pnl": 1120.0, "avg_pnl": 40.0},
        "cohort_labels": {"by_strategy": "Strategy", "by_direction": "Direction"},
        "cohorts": {
            "by_strategy": [
                {"key": "earnings", "n": 14, "win_rate": 1.0, "win_rate_ci": [0.78, 1.0],
                 "avg_pnl": 206.0, "total_pnl": 2884.0, "calibration_gap": 0.4},
                {"key": "reddit", "n": 14, "win_rate": 0.0, "win_rate_ci": [0.0, 0.22],
                 "avg_pnl": -126.0, "total_pnl": -1764.0, "calibration_gap": -0.55},
            ],
            "by_direction": [],
        },
        "numeric_features": [
            {"label": "Model win prob", "feature": "win_prob", "n": 28,
             "corr_pnl": {"r": 0.9, "ci": [0.8, 0.95], "n": 28, "significant": True},
             "corr_win": None, "terciles": []},
        ],
        "calibration": {"n": 28, "avg_predicted": 0.57, "realized_win_rate": 0.5, "buckets": []},
        "counterfactual": [
            {"strategy": "earnings",
             "opened": {"n": 8, "avg_fav_move_5d": 0.03, "up_rate": 0.75},
             "skipped": {"n": 8, "avg_fav_move_5d": 0.04, "up_rate": 0.9}},
        ],
        "notes": ["Small sample — directional only."],
    }
    base.update(over)
    return base


def test_empty_report_is_narrated_gracefully():
    n = build_narrative({"graded_trades": 0})
    assert n["source"] == "empty"
    assert "No graded trades" in n["headline"]
    assert n["sections"] == []


def test_heuristic_headline_and_sections():
    n = build_narrative(_report())
    assert n["source"] == "heuristic"
    assert "28 graded trades" in n["headline"]
    titles = [s["title"] for s in n["sections"]]
    assert "What's working" in titles and "What's not" in titles
    working = next(s for s in n["sections"] if s["title"] == "What's working")
    assert any("earnings" in p for p in working["points"])
    losing = next(s for s in n["sections"] if s["title"] == "What's not")
    assert any("reddit" in p for p in losing["points"])


def test_heuristic_flags_overconfidence_and_gate_risk():
    n = build_narrative(_report())
    cal = next(s for s in n["sections"] if s["title"] == "Calibration")
    assert any("over-confident" in p for p in cal["points"])
    gate = next(s for s in n["sections"] if s["title"].startswith("Gate check"))
    # Skipped up-rate (0.9) > opened (0.75) -> flag the gate may reject winners.
    assert any("rejecting winners" in p for p in gate["points"])
    assert any("gate" in h.lower() for h in n["hypotheses"])


def test_calibration_feedback_summarized_when_enabled():
    n = build_narrative(
        _report(),
        calibration={
            "enabled": True, "min_samples": 20, "max_delta": 0.15,
            "strategies": [
                {"strategy": "earnings", "n": 14, "predicted": 0.6, "realized": 1.0,
                 "multiplier": 1.67, "applicable": True},
            ],
        },
    )
    cal = next(s for s in n["sections"] if s["title"] == "Calibration")
    assert any("recalibrating win-prob up" in p for p in cal["points"])


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
