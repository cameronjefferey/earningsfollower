"""Narrator - turn the signal-attribution numbers into a plain-English read.

This is the *communication* half of the learning loop (phase 3): given the
attribution report (and the current calibration state), produce a short, honest
post-mortem - what's working, what isn't, whether the model is well-calibrated,
whether the gate is rejecting winners, and a few hypotheses to test next.

An LLM is used only to *narrate* numbers it's handed - never to judge edge or
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
    "You are a trading coach writing a weekly post-mortem a retail trader can "
    "actually use. You are handed pre-computed statistics (cohort win rates with "
    "confidence intervals, feature-vs-outcome correlations, calibration, and an "
    "opened-vs-skipped entry-filter check). Explain ONLY what the numbers say - "
    "never invent figures, never claim certainty a small sample can't support, "
    "and always respect confidence intervals and sample sizes (wide interval or "
    "tiny n = 'inconclusive'). Write in plain English a trader would say out loud: "
    "avoid jargon like 'calibration gap', 'significant feature', 'EV gate', "
    "'alpha/beta'. Prefer 'our odds were off', 'this setup type is working', "
    "'we're passing on trades that then worked'. Hypotheses must be actionable "
    "for the reader's own book (what to lean into, size down, or skip). Be "
    "concrete and brief. Reply with a single JSON object with keys: "
    "headline (string), sections (array of {title, points:[string]}), "
    "hypotheses (array of string), caveats (array of string). Prefer section "
    "titles: \"What's working\", \"What's hurting\", \"Clues at entry\", "
    "\"Are the odds honest?\", \"Are we passing on good trades?\"."
)


def build_narrative(
    report: dict,
    calibration: dict | None = None,
    *,
    stop_policy: dict | None = None,
    exit_policy: dict | None = None,
) -> dict:
    """Return a narrative dict. Tries the LLM first, falls back to the heuristic."""
    graded = report.get("graded_trades", 0)
    if not graded:
        return {
            "source": "empty",
            "generated_at": datetime.utcnow().isoformat(),
            "headline": "No graded trades yet - nothing to narrate.",
            "sections": [],
            "hypotheses": [],
            "caveats": [
                "The decision journal is recording entries (and skips); this "
                "read appears once trades close and their outcomes are labeled."
            ],
        }

    llm_result = _try_llm(report, calibration, stop_policy, exit_policy)
    if llm_result is not None:
        return _attach_risk_caveats(llm_result, stop_policy, exit_policy)
    return _attach_risk_caveats(
        _heuristic(report, calibration, stop_policy, exit_policy),
        stop_policy,
        exit_policy,
    )


def _attach_risk_caveats(
    narrative: dict,
    stop_policy: dict | None,
    exit_policy: dict | None,
) -> dict:
    """Ensure the live risk rules are always visible in the post-mortem."""
    extras: list[str] = []
    if stop_policy is not None:
        if stop_policy.get("enabled"):
            extras.append(
                f"Hard stops are ON for earnings credit trades: cut at "
                f"{_pct(stop_policy.get('stop_loss_frac'))} of max risk"
                f" (tighten to {_pct(stop_policy.get('late_stop_frac'))} inside "
                f"{stop_policy.get('late_dte')} DTE)."
            )
        else:
            extras.append(
                "Hard stops are OFF for earnings credit trades - losers can run "
                "to full defined risk while take-profits clip winners."
            )
    if exit_policy is not None and exit_policy.get("enabled"):
        extras.append(
            f"Take-profit is ON around a {_pct(exit_policy.get('effective_pct'))} "
            "underlying move on the directional books."
        )
    if extras:
        caveats = list(narrative.get("caveats") or [])
        # Put risk rules first so they aren't buried.
        narrative["caveats"] = extras + [
            c for c in caveats if c not in extras
        ]
    return narrative


# --- LLM path ----------------------------------------------------------------


def _compact(
    report: dict,
    calibration: dict | None,
    stop_policy: dict | None = None,
    exit_policy: dict | None = None,
) -> dict:
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
        "live_stop_policy": stop_policy,
        "live_exit_policy": exit_policy,
    }


def _try_llm(
    report: dict,
    calibration: dict | None,
    stop_policy: dict | None = None,
    exit_policy: dict | None = None,
) -> dict | None:
    with LLMClient() as client:
        if not client.enabled:
            return None
        user = (
            "Write the post-mortem from these statistics. Prioritize the most "
            "decisive, best-sampled findings; call out anything with a tiny sample "
            "or a confidence interval spanning zero as inconclusive. Mention whether "
            "hard stops and take-profits are currently armed - that changes how to "
            "read win rate vs average win/loss.\n\n"
            + json.dumps(
                _compact(report, calibration, stop_policy, exit_policy), default=str
            )
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
    return "-" if v is None else f"{v * 100:.0f}%"


def _money(v) -> str:
    if v is None:
        return "-"
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
            tag = " - small sample, take lightly" if r["n"] < 8 else ""
            line = (
                f"{dim_label} · {r['key']}: about {_money(r['avg_pnl'])} per trade, "
                f"{_pct(r['win_rate'])} wins (likely range {_pct(lo)}–{_pct(hi)}), "
                f"{r['n']} trades{tag}"
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
            f"When {f['label']} is {direction}, trades have tended to make more money "
            f"({f['n']} trades)."
        )
    return out[:5] or [
        "No entry clue yet clearly lines up with winners - still early."
    ]


def _calibration_points(report: dict) -> list[str]:
    c = report.get("calibration") or {}
    pred, real = c.get("avg_predicted"), c.get("realized_win_rate")
    if pred is None or real is None:
        return []
    gap = real - pred
    if abs(gap) < 0.05:
        verdict = "roughly honest about its odds"
    elif gap > 0:
        verdict = "winning more often than it expected"
    else:
        verdict = "winning less often than it expected"
    return [
        f"It figured about a {_pct(pred)} chance of winning and actually won "
        f"{_pct(real)} of the time - {verdict} "
        f"({c.get('n', 0)} closed trades)."
    ]


def _gate_points(report: dict) -> list[str]:
    out: list[str] = []
    for c in report.get("counterfactual", []):
        opened, skipped = c.get("opened"), c.get("skipped")
        if not opened or not skipped:
            continue
        if skipped["up_rate"] >= opened["up_rate"]:
            out.append(
                f"{c['strategy']}: setups we passed on still moved our way "
                f"{_pct(skipped['up_rate'])} of the time vs {_pct(opened['up_rate'])} "
                "for the ones we took - we may be skipping good trades."
            )
        else:
            out.append(
                f"{c['strategy']}: the trades we took moved our way "
                f"{_pct(opened['up_rate'])} of the time vs {_pct(skipped['up_rate'])} "
                "for skips - the filter is helping."
            )
    return out


def _calibration_feedback_points(calibration: dict | None) -> list[str]:
    if not calibration:
        return []
    if not calibration.get("enabled"):
        return ["Odds adjustment is off - new trades use the raw model odds."]
    out: list[str] = []
    for e in calibration.get("strategies", []):
        if not e.get("applicable"):
            continue
        lean = "a bit more willing" if e["multiplier"] > 1 else "a bit more cautious"
        out.append(
            f"{e['strategy']}: now {lean} after seeing predicted {_pct(e['predicted'])} "
            f"vs real {_pct(e['realized'])} ({e['n']} trades)."
        )
    return out


def _risk_points(
    stop_policy: dict | None, exit_policy: dict | None
) -> list[str]:
    out: list[str] = []
    if stop_policy is not None:
        if stop_policy.get("enabled"):
            out.append(
                f"Hard stops ON for earnings credits: exit at "
                f"{_pct(stop_policy.get('stop_loss_frac'))} of max risk "
                f"(or {_pct(stop_policy.get('late_stop_frac'))} inside "
                f"{stop_policy.get('late_dte')} DTE)."
            )
        else:
            out.append(
                "Hard stops OFF for earnings credits - that lets losers run while "
                "take-profits bank small wins (bad payoff shape at ~50% wins)."
            )
    if exit_policy is not None:
        if exit_policy.get("enabled"):
            out.append(
                f"Take-profit ON around {_pct(exit_policy.get('effective_pct'))} "
                "underlying move on directional books."
            )
        else:
            out.append("Take-profit is off on the directional books.")
    return out


def _heuristic(
    report: dict,
    calibration: dict | None,
    stop_policy: dict | None = None,
    exit_policy: dict | None = None,
) -> dict:
    overall = report.get("overall") or {}
    winners, losers = _best_worst_cohorts(report)

    headline = (
        f"{overall.get('n', 0)} closed trades: {_money(overall.get('total_pnl'))} net, "
        f"{_pct(overall.get('win_rate'))} win rate."
    )

    sections = [
        {
            "title": "What's working",
            "points": winners
            or ["Nothing clearly profitable with a big enough sample yet."],
        },
        {
            "title": "What's hurting",
            "points": losers
            or ["No clearly losing bucket with a big enough sample yet."],
        },
        {"title": "Clues at entry", "points": _feature_points(report)},
        {
            "title": "Are the odds honest?",
            "points": _calibration_points(report)
            + _calibration_feedback_points(calibration),
        },
        {
            "title": "Are we passing on good trades?",
            "points": _gate_points(report)
            or ["Not enough skipped setups yet to judge the entry filter."],
        },
        {
            "title": "Risk exits live now",
            "points": _risk_points(stop_policy, exit_policy)
            or ["No live risk-policy snapshot attached."],
        },
    ]

    hypotheses: list[str] = []
    if winners:
        hypotheses.append(
            f"In your own book, lean toward setups like {winners[0].split(':')[0]} - "
            "confirm it keeps working before you size up."
        )
    if losers:
        hypotheses.append(
            f"Size down or skip setups like {losers[0].split(':')[0]} if that bucket "
            "keeps losing as more trades close."
        )
    gate_concerns = [p for p in _gate_points(report) if "skipping good trades" in p]
    if gate_concerns:
        hypotheses.append(
            "On the flagged strategy, consider taking a few more borderline setups - "
            "we may be passing on winners."
        )

    return {
        "source": "heuristic",
        "generated_at": datetime.utcnow().isoformat(),
        "headline": headline,
        "sections": [s for s in sections if s["points"]],
        "hypotheses": hypotheses,
        "caveats": report.get("notes", []),
    }
