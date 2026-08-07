"""Cross-board ranked setups — the decision layer for the morning brief.

Quality over quantity: prefer solid samples and nearer catalysts. Thin history
can appear, but never as the day's focus when something better exists.

Each setup carries a structured `plan` (thesis, trigger status, target, window,
invalidation, sizing) and a `conviction` score so the brief can read like a desk
note instead of a mail-merge. Waves are clustered by their trigger so one macro
event (e.g. a single peer printing) surfaces as ONE idea with its best
expression, not the same bet fanned across three names.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services import board_snapshots
from app.services.sample_stats import sample_tier
from app.services.waves import filter_by_min_peers

TIER_BOOST = {"solid": 1.25, "ok": 1.0, "thin": 0.45}
TIER_BASE_CONVICTION = {"solid": 60.0, "ok": 46.0, "thin": 28.0}


def _parse_day(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _urgency_boost(report_day: date | None, today: date) -> float:
    """Nearer catalysts rank up; stale / far-out names rank down."""
    if report_day is None:
        return 0.85
    delta = (report_day - today).days
    if delta < -5:
        return 0.55  # drift window mostly spent
    if delta < 0:
        return 1.05  # live post-report drift
    if delta <= 2:
        return 1.2
    if delta <= 7:
        return 1.1
    if delta <= 14:
        return 1.0
    return 0.75


def _pct(value: Any, digits: int = 1, signed: bool = False) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    s = f"{value * 100:+.{digits}f}%" if signed else f"{value * 100:.{digits}f}%"
    return s


def _conviction(
    tier: str,
    win_floor: float | None,
    win_rate: float | None,
    edge: float | None,
    urgency: float,
    n: int,
) -> tuple[int, str]:
    """A 0–100 read on how much to trust the setup today.

    Built from sample tier, the Wilson floor of the win rate (how bad it plausibly
    is, not the rosy point estimate), edge magnitude, catalyst proximity, and n.
    Deliberately conservative: a thin sample can't score 'High'.
    """
    score = TIER_BASE_CONVICTION.get(tier, 40.0)
    floor = win_floor if isinstance(win_floor, (int, float)) else None
    if floor is None and isinstance(win_rate, (int, float)):
        floor = win_rate - 0.12
    if floor is not None:
        score += (floor - 0.5) * 55.0  # reward a floor above a coin flip
    if isinstance(edge, (int, float)):
        score += min(abs(edge) * 100.0, 12.0)
    score += min(n, 30) * 0.2
    score *= urgency
    score = max(5.0, min(97.0, score))
    value = int(round(score))

    if tier == "thin":
        label = "Speculative"
    elif value >= 70:
        label = "High"
    elif value >= 52:
        label = "Medium"
    else:
        label = "Low"
    return value, label


def _sizing(tier: str, n: int, win_floor: float | None) -> str:
    if tier == "thin":
        return f"Starter size only — thin history (n={n})."
    floor_txt = (
        f", floor {win_floor:.0%}" if isinstance(win_floor, (int, float)) else ""
    )
    if tier == "solid":
        return f"Standard size — solid sample (n={n}{floor_txt})."
    return f"Half size — usable but not deep (n={n}{floor_txt})."


def _wave_rows(signals: list[dict], today: date) -> list[dict]:
    """Collapse peer-wave signals to one card per target (best peer)."""
    best: dict[str, dict] = {}
    for s in signals:
        target = (s.get("target") or "").upper()
        if not target:
            continue
        score = float((s.get("stats") or {}).get("score") or 0)
        prev = best.get(target)
        if prev is not None and score <= float(prev.get("_raw_score") or 0):
            continue
        n = int((s.get("stats") or {}).get("sample_size") or 0)
        tier = s.get("sample_tier") or sample_tier(n)
        wr = (s.get("stats") or {}).get("win_rate")
        expected = s.get("expected_runup_pct")
        trigger = s.get("trigger")
        trig_move = s.get("trigger_move_pct")
        trig_beat = s.get("trigger_beat")
        report_day = _parse_day(s.get("target_report_date"))
        ci_low = s.get("win_rate_ci_low")
        direction = s.get("direction") or "bullish"
        side = "long" if direction != "bearish" else "short"
        report_txt = report_day.isoformat() if report_day else "its report"

        why = [
            f"{trigger} already reported; historically {target} drifts into its own report.",
        ]
        if isinstance(wr, (int, float)) and isinstance(ci_low, (int, float)):
            why.append(f"Win rate {wr:.0%} (Wilson floor {ci_low:.0%}) on n={n}.")
        elif isinstance(wr, (int, float)):
            why.append(f"Win rate {wr:.0%} on n={n}.")
        else:
            why.append(f"Sample n={n}.")
        if tier == "thin":
            why.append("Thin history — exploratory only.")

        # Live trigger status: the whole wave thesis hinges on the trigger's move.
        if isinstance(trig_move, (int, float)):
            beat_txt = (
                " (beat)" if trig_beat is True else " (miss)" if trig_beat is False else ""
            )
            trigger_status = f"{trigger} {_pct(trig_move, 1, signed=True)} on its report{beat_txt}"
        else:
            trigger_status = f"{trigger} already reported"

        thesis = (
            f"{trigger_status}. Peers like {target} have historically run "
            f"{_pct(expected, 1, signed=True)} into their own reports "
            f"(win {wr:.0%}, n={n})."
            if isinstance(wr, (int, float))
            else f"{trigger_status}. {target} has historically drifted into its own report."
        )

        action = (
            f"Bias {side} {target} into {report_txt} while the {trigger} move holds."
        )
        invalidation = (
            f"{trigger} gives back its post-report move, or {target} front-runs most "
            f"of the {_pct(expected, 1, signed=True)} before {report_txt}."
        )
        conviction, conv_label = _conviction(
            tier, ci_low, wr, expected, _urgency_boost(report_day, today), n
        )

        best[target] = {
            "id": f"wave:{target}:{trigger}",
            "kind": "wave",
            "ticker": target,
            "name": s.get("target_name"),
            "direction": direction,
            "trigger": trigger,
            "trigger_move_pct": trig_move,
            "trigger_beat": trig_beat,
            "headline": (
                f"{trigger} → {target}"
                + (
                    f" · hist {expected * 100:+.1f}%"
                    if isinstance(expected, (int, float))
                    else ""
                )
            ),
            "action": action,
            "score": round(
                score * TIER_BOOST.get(tier, 1.0) * _urgency_boost(report_day, today),
                6,
            ),
            "_raw_score": score,
            "conviction": conviction,
            "conviction_label": conv_label,
            "sample_tier": tier,
            "sample_size": n,
            "win_rate": wr,
            "win_rate_ci_low": ci_low,
            "edge_pct": expected,
            "report_date": s.get("target_report_date"),
            "themes": s.get("shared_themes") or [],
            "why": why,
            "watch": (
                f"Hold the lean while {trigger}'s post-report move stays intact and "
                f"{target} hasn't reported yet"
                + (f" ({report_day.isoformat()})" if report_day else "")
                + "."
            ),
            "invalidation": invalidation,
            "plan": {
                "thesis": thesis,
                "trigger_status": trigger_status,
                "target": f"{_pct(expected, 1, signed=True)} into {report_txt}",
                "window": (
                    f"Reports {report_day.isoformat()}"
                    if report_day
                    else "Report date TBD"
                ),
                "invalidation": invalidation,
                "sizing": _sizing(tier, n, ci_low),
            },
            "href": f"/company/{target}",
            "board_href": "/waves",
        }
    return list(best.values())


def _drift_rows(setups: list[dict], today: date) -> list[dict]:
    out: list[dict] = []
    for s in setups:
        ticker = (s.get("ticker") or "").upper()
        if not ticker:
            continue
        hist = s.get("history") or {}
        live = s.get("live") or {}
        n = int(hist.get("sample_size") or 0)
        tier = s.get("sample_tier") or sample_tier(n)
        raw = float(s.get("score") or 0)
        wr = hist.get("win_rate_5d")
        edge = hist.get("avg_drift_5d_pct")
        ci_low = s.get("win_rate_ci_low")
        direction = s.get("direction") or "long"
        report_day = _parse_day(s.get("report_date"))
        days_left = live.get("trading_days_left")
        days_in = live.get("trading_days_in")
        side = "long" if direction == "long" else "short"

        why = list(s.get("why") or [])[:2]
        if not why:
            why = ["Post-earnings drift historically continued after similar reports."]
        if isinstance(wr, (int, float)):
            why.append(f"5d continuation {wr:.0%} on n={n}.")
        if tier == "thin" and not any("thin" in w.lower() for w in why):
            why.append("Thin history — size conviction down.")

        action = f"Stay {side} {ticker} for the remaining PEAD window"
        if isinstance(days_left, (int, float)):
            action += f" (~{int(days_left)} sessions left)"
        action += "."

        left_txt = (
            f"~{int(days_left)} sessions left"
            if isinstance(days_left, (int, float))
            else "window open"
        )
        day_txt = str(days_in) if days_in is not None else "?"
        trigger_status = f"Day {day_txt} of the drift window, {left_txt}"
        thesis = (
            f"{ticker} already reported. Similar reports historically drifted "
            f"{_pct(edge, 1, signed=True)} over the next 5 sessions "
            f"(continuation {wr:.0%}, n={n})."
            if isinstance(wr, (int, float))
            else f"{ticker} already reported; history shows continuation after similar reports."
        )
        invalidation = (
            "A close back through the earnings-day pivot (post-report open/close band) "
            "ends the drift."
        )
        conviction, conv_label = _conviction(
            tier, ci_low, wr, edge, _urgency_boost(report_day, today), n
        )

        out.append(
            {
                "id": f"drift:{ticker}:{s.get('report_date')}",
                "kind": "drift",
                "ticker": ticker,
                "name": s.get("name"),
                "direction": "bullish" if direction == "long" else "bearish",
                "headline": (
                    f"PEAD {side} {ticker}"
                    + (
                        f" · hist 5d {edge * 100:+.1f}%"
                        if isinstance(edge, (int, float))
                        else ""
                    )
                ),
                "action": action,
                "score": round(
                    raw * TIER_BOOST.get(tier, 1.0) * _urgency_boost(report_day, today),
                    6,
                ),
                "_raw_score": raw,
                "conviction": conviction,
                "conviction_label": conv_label,
                "sample_tier": tier,
                "sample_size": n,
                "win_rate": wr,
                "win_rate_ci_low": ci_low,
                "edge_pct": edge,
                "report_date": s.get("report_date"),
                "themes": s.get("themes") or [],
                "why": why,
                "watch": (
                    f"Day {day_txt} of the drift window"
                    + (
                        f"; ~{int(days_left)} sessions left."
                        if isinstance(days_left, (int, float))
                        else "."
                    )
                ),
                "invalidation": invalidation,
                "plan": {
                    "thesis": thesis,
                    "trigger_status": trigger_status,
                    "target": f"{_pct(edge, 1, signed=True)} over the 5-session window",
                    "window": left_txt.capitalize(),
                    "invalidation": invalidation,
                    "sizing": _sizing(tier, n, ci_low),
                },
                "href": f"/company/{ticker}",
                "board_href": "/drift",
            }
        )
    return out


def _cluster_waves(rows: list[dict]) -> list[dict]:
    """Collapse same-trigger waves into one representative + peer list.

    Fixes the failure mode where 'UNP printed' produced three near-identical
    industrials cards. The best expression carries the idea; the rest ride along
    as `cluster_peers` so breadth on the board reflects distinct drivers.
    """
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for r in rows:
        key = str(r.get("trigger") or r["ticker"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    out: list[dict] = []
    for key in order:
        members = sorted(groups[key], key=lambda r: r["score"], reverse=True)
        rep = members[0]
        peers = members[1:]
        if peers:
            rep["cluster_size"] = len(members)
            rep["cluster_peers"] = [
                {
                    "ticker": p["ticker"],
                    "name": p.get("name"),
                    "edge_pct": p.get("edge_pct"),
                    "win_rate": p.get("win_rate"),
                    "sample_size": p.get("sample_size"),
                    "href": p.get("href"),
                }
                for p in peers
            ]
        out.append(rep)
    return out


# Fixed placeholders for unpaid brief preview — identity + edge stats of the
# live lean must not leave the server. Kind/direction stay so the card chrome
# still looks like a real brief.
_PREVIEW_TICKERS = ("ORCL", "AMD")
_PREVIEW_NAMES = ("Sample focus name", "Sample secondary name")


def _demo_preview_setup(row: dict[str, Any], index: int) -> dict[str, Any]:
    """Strip the live lean; keep card shape for the blurred teaser."""
    r = dict(row)
    i = index % len(_PREVIEW_TICKERS)
    r["ticker"] = _PREVIEW_TICKERS[i]
    r["name"] = _PREVIEW_NAMES[i]
    r["href"] = "/pricing"
    r["board_href"] = "/pricing"
    r["trigger"] = "PEER"
    r["edge_pct"] = 0.045 if i == 0 else 0.028
    r["win_rate"] = 0.67 if i == 0 else 0.58
    r["win_rate_ci_low"] = 0.38
    r["win_rate_ci_high"] = 0.88
    r["sample_size"] = 6
    r["sample_tier"] = "ok"
    r["conviction"] = 72 if i == 0 else 58
    r["conviction_label"] = "Medium"
    r["headline"] = "Demo example — not today's live book."
    r["why"] = ["Placeholder pattern for layout only (not live)."]
    r["action"] = "Pro unlocks today's live action / watch note."
    r["invalidation"] = "Pro unlocks live invalidation framing."
    r.pop("cluster_peers", None)
    r["plan"] = {
        "thesis": "Demo thesis for layout — not today's live lean.",
        "trigger_status": "Demo trigger (sample)",
        "target": "Pro",
        "window": "a few sessions",
        "invalidation": "Pro",
        "sizing": "Pro",
    }
    r["rank"] = index + 1
    r.pop("_raw_score", None)
    return r


def ranked_setups(db: Session, *, limit: int = 12, preview: bool = False) -> dict[str, Any]:
    today = date.today()
    waves = board_snapshots.get_snapshot(db, "waves", "14:21") or {}
    drift = board_snapshots.get_snapshot(db, "drift", "12") or {}

    wave_signals = filter_by_min_peers(list(waves.get("signals") or []))
    wave_rows = _cluster_waves(_wave_rows(wave_signals, today))
    drift_rows = _drift_rows(list(drift.get("setups") or []), today)
    rows = wave_rows + drift_rows

    # Prefer non-thin when we have enough; never let thin dominate the top.
    solidish = [r for r in rows if r.get("sample_tier") != "thin"]
    pool = solidish if len(solidish) >= max(3, limit // 2) else rows
    pool.sort(key=lambda r: r["score"], reverse=True)

    cap = max(2, (limit * 2) // 3)
    picked: list[dict] = []
    kind_counts = {"wave": 0, "drift": 0}
    deferred: list[dict] = []
    for r in pool:
        k = r["kind"]
        if kind_counts.get(k, 0) >= cap:
            deferred.append(r)
            continue
        picked.append(r)
        kind_counts[k] = kind_counts.get(k, 0) + 1
        if len(picked) >= limit:
            break
    if len(picked) < limit:
        for r in deferred:
            picked.append(r)
            if len(picked) >= limit:
                break

    # If #1 would be thin but a solid name exists lower, promote the best solid.
    if picked and picked[0].get("sample_tier") == "thin":
        for i, r in enumerate(picked[1:], start=1):
            if r.get("sample_tier") != "thin":
                picked.insert(0, picked.pop(i))
                break

    for i, r in enumerate(picked, start=1):
        r["rank"] = i
        r.pop("_raw_score", None)

    note = None
    if preview:
        # Never ship the live lean to unpaid callers — ticker / edge / win /
        # conviction / thesis are the product. Keep kind + direction so the
        # layout still reads as a real brief card; swap identity + numbers for
        # fixed demo placeholders (UI also blurs them).
        picked = [_demo_preview_setup(r, i) for i, r in enumerate(picked[:2])]
        note = (
            "Sample brief — demo data only, not today's live lean. "
            "Pro unlocks the real focus, plan, and boards."
        )

    updated = waves.get("updated_at") or drift.get("updated_at")
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "as_of": today.isoformat(),
        "updated_at": updated,
        "count": len(picked),
        "setups": picked,
        "focus": picked[0] if picked else None,
        "preview": preview,
        "preview_note": note,
    }
