"""Narrator — turn the signal-attribution numbers into a plain-English read.

This is the *communication* half of the learning loop (phase 3): given the
attribution report (and the current calibration state), produce a short, honest
post-mortem — what's working, what isn't, whether the model is well-calibrated,
whether the gate is rejecting winners, and a few hypotheses to test next.

An LLM is used only to *narrate* numbers it's handed — never to judge edge or
invent statistics. If no LLM key is configured (``LLMClient.enabled`` is False)
or the call fails, a deterministic heuristic writes the same-shaped narrative, so
this always works without an LLM bill (mirroring the Reddit scorer's fallback).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from app.clients.llm import LLMClient

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a disciplined quant trading analyst writing a weekly post-mortem for "
    "a paper options-trading bot. You are handed pre-computed statistics (cohort "
    "win rates with confidence intervals, feature-vs-outcome correlations, "
    "calibration, and an opened-vs-skipped gate check). Your job is ONLY to "
    "explain and prioritize what the numbers say — never invent figures, never "
    "claim certainty a small sample can't support, and always respect confidence "
    "intervals and sample sizes (a wide interval or tiny n means 'inconclusive'). "
    "Be concrete and brief. Reply with a single JSON object with keys: "
    "headline (string), sections (array of {title, points:[string]}), "
    "hypotheses (array of string), caveats (array of string)."
)


def build_narrative(report: dict, calibration: dict | None = None) -> dict:
    """Return a narrative dict. Tries the LLM first, falls back to the heuristic."""
    graded = report.get("graded_trades", 0)
    if not graded:
        return {
            "source": "empty",
            "generated_at": datetime.utcnow().isoformat(),
            "headline": "No graded trades yet — nothing to narrate.",
            "sections": [],
            "hypotheses": [],
            "caveats": [
                "The decision journal is recording entries (and skips); this "
                "read appears once trades close and their outcomes are labeled."
            ],
        }

    llm_result = _try_llm(report, calibration)
    if llm_result is not None:
        return llm_result
    return _heuristic(report, calibration)


# --- LLM path ----------------------------------------------------------------


def _compact(report: dict, calibration: dict | None) -> dict:
    """A trimmed, token-cheap view of the report for the prompt."""
    def top(rows: list[dict], k: int = 4) -> list[dict]:
        return [
            {
                "key": r["key"], "n": r["n"], "win_rate": r["win_rate"],
                "win_rate_ci": r["win_rate_ci"], "avg_pnl": r["avg_pnl"],
                "total_pnl": r["total_pnl"], "calibration_gap": r.get("calibration_gap"),
            }
            for r in rows[:k]
        ]

    cohorts = {k: top(v) for k, v in report.get("cohorts", {}).items() if v}
    feats = [
        {
            "label": f["label"], "n": f["n"],
            "corr_pnl": f.get("corr_pnl"), "corr_win": f.get("corr_win"),
        }
        for f in report.get("numeric_features", [])[:8]
    ]
    return {
        "graded_trades": report.get("graded_trades"),
        "overall": report.get("overall"),
        "cohort_labels": report.get("cohort_labels"),
        "cohorts": cohorts,
        "numeric_features": feats,
        "calibration": report.get("calibration"),
        "counterfactual": report.get("counterfactual"),
        "calibration_feedback": calibration,
    }


def _try_llm(report: dict, calibration: dict | None) -> dict | None:
    with LLMClient() as client:
        if not client.enabled:
            return None
        user = (
            "Write the post-mortem from these statistics. Prioritize the most "
            "decisive, best-sampled findings; call out anything with a tiny sample "
            "or a confidence interval spanning zero as inconclusive.\n\n"
            + json.dumps(_compact(report, calibration), default=str)
        )
        data = client.score_json(_SYSTEM, user, max_tokens=900)
    if not isinstance(data, dict) or "headline" not in data:
        return None
    sections = data.get("sections")
    if not isinstance(sections, list):
        sections = []
    return {
        "source": "llm",
        "generated_at": datetime.utcnow().isoformat(),
        "headline": str(data.get("headline", "")),
        "sections": [
            {
                "title": str(s.get("title", "")),
                "points": [str(p) for p in (s.get("points") or [])],
            }
            for s in sections
            if isinstance(s, dict)
        ],
        "hypotheses": [str(h) for h in (data.get("hypotheses") or [])],
        "caveats": [str(c) for c in (data.get("caveats") or [])]
        or report.get("notes", []),
    }


# --- heuristic path ----------------------------------------------------------


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def _money(v) -> str:
    if v is None:
        return "—"
    sign = "-" if v < 0 else "+" if v > 0 else ""
    return f"{sign}${abs(v):,.0f}"


def _best_worst_cohorts(report: dict) -> tuple[list[str], list[str]]:
    """Scan every cohort dimension for the strongest positive / negative rows,
    tagging thin samples so we don't overstate them."""
    labels = report.get("cohort_labels", {})
    winners: list[tuple[float, str]] = []
    losers: list[tuple[float, str]] = []
    for dim, rows in report.get("cohorts", {}).items():
        dim_label = labels.get(dim, dim)
        for r in rows:
            lo, hi = r["win_rate_ci"]
            tag = " (thin sample)" if r["n"] < 8 else ""
            line = (
                f"{dim_label} · {r['key']}: {_money(r['avg_pnl'])}/trade, "
                f"{_pct(r['win_rate'])} win [{_pct(lo)}–{_pct(hi)}], n={r['n']}{tag}"
            )
            (winners if r["avg_pnl"] > 0 else losers).append((r["avg_pnl"], line))
    winners.sort(key=lambda x: x[0], reverse=True)
    losers.sort(key=lambda x: x[0])
    return [l for _, l in winners[:4]], [l for _, l in losers[:4]]


def _feature_points(report: dict) -> list[str]:
    out: list[str] = []
    for f in report.get("numeric_features", []):
        cp = f.get("corr_pnl") or {}
        if not cp.get("significant"):
            continue
        direction = "higher" if cp["r"] > 0 else "lower"
        out.append(
            f"{f['label']}: {direction} values track better P&L "
            f"(r={cp['r']:+.2f}, CI {cp['ci']}, n={f['n']})."
        )
    return out[:5] or ["No entry feature yet shows a statistically clear link to P&L."]


def _calibration_points(report: dict) -> list[str]:
    c = report.get("calibration") or {}
    pred, real = c.get("avg_predicted"), c.get("realized_win_rate")
    if pred is None or real is None:
        return []
    gap = real - pred
    if abs(gap) < 0.05:
        verdict = "well-calibrated"
    elif gap > 0:
        verdict = "under-confident (winning more than it predicts)"
    else:
        verdict = "over-confident (winning less than it predicts)"
    return [
        f"Overall the model predicts {_pct(pred)} and realizes {_pct(real)} "
        f"— {verdict} across {c.get('n', 0)} graded trades."
    ]


def _gate_points(report: dict) -> list[str]:
    out: list[str] = []
    for c in report.get("counterfactual", []):
        opened, skipped = c.get("opened"), c.get("skipped")
        if not opened or not skipped:
            continue
        if skipped["up_rate"] >= opened["up_rate"]:
            out.append(
                f"{c['strategy']}: skipped setups moved favorably {_pct(skipped['up_rate'])} "
                f"of the time vs {_pct(opened['up_rate'])} for the ones we traded "
                "— the gate may be rejecting winners; worth a look."
            )
        else:
            out.append(
                f"{c['strategy']}: the gate is earning its keep — traded setups "
                f"moved favorably {_pct(opened['up_rate'])} vs {_pct(skipped['up_rate'])} "
                "for skips."
            )
    return out


def _calibration_feedback_points(calibration: dict | None) -> list[str]:
    if not calibration:
        return []
    if not calibration.get("enabled"):
        return ["Calibration feedback is off — predictions feed the gate as-is."]
    out: list[str] = []
    for e in calibration.get("strategies", []):
        if not e.get("applicable"):
            continue
        m = e["multiplier"]
        lean = "up" if m > 1 else "down"
        out.append(
            f"{e['strategy']}: recalibrating win-prob {lean} (x{m:.2f}; predicted "
            f"{_pct(e['predicted'])} vs realized {_pct(e['realized'])}, n={e['n']})."
        )
    return out


def _heuristic(report: dict, calibration: dict | None) -> dict:
    overall = report.get("overall") or {}
    winners, losers = _best_worst_cohorts(report)

    headline = (
        f"{overall.get('n', 0)} graded trades: {_money(overall.get('total_pnl'))} net, "
        f"{_pct(overall.get('win_rate'))} win rate."
    )

    sections = [
        {"title": "What's working", "points": winners or ["Nothing profitable clears the sample floor yet."]},
        {"title": "What's not", "points": losers or ["No clearly losing cohort above the sample floor."]},
        {"title": "Feature signal", "points": _feature_points(report)},
        {"title": "Calibration", "points": _calibration_points(report) + _calibration_feedback_points(calibration)},
        {"title": "Gate check (opened vs skipped)", "points": _gate_points(report) or ["Not enough labeled skips yet to grade the gate."]},
    ]

    hypotheses: list[str] = []
    if winners:
        hypotheses.append(
            f"Lean into the best cohort ({winners[0].split(':')[0]}) — confirm it "
            "holds as more of those trades close before sizing up."
        )
    if losers:
        hypotheses.append(
            f"Tighten or drop the worst cohort ({losers[0].split(':')[0]}) if the "
            "sample keeps growing against it."
        )
    gate_concerns = [p for p in _gate_points(report) if "rejecting winners" in p]
    if gate_concerns:
        hypotheses.append(
            "Revisit the entry gate on the flagged strategy — it may be too strict."
        )

    return {
        "source": "heuristic",
        "generated_at": datetime.utcnow().isoformat(),
        "headline": headline,
        "sections": [s for s in sections if s["points"]],
        "hypotheses": hypotheses,
        "caveats": report.get("notes", []),
    }
