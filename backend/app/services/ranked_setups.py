"""Cross-board ranked setups — the decision layer for the morning brief.

Quality over quantity: prefer solid samples and nearer catalysts. Thin history
can appear, but never as the day's focus when something better exists.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services import board_snapshots
from app.services.sample_stats import sample_tier

TIER_BOOST = {"solid": 1.25, "ok": 1.0, "thin": 0.45}


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
        return 1.05  # live post-print drift
    if delta <= 2:
        return 1.2
    if delta <= 7:
        return 1.1
    if delta <= 14:
        return 1.0
    return 0.75


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
        report_day = _parse_day(s.get("target_report_date"))
        ci_low = s.get("win_rate_ci_low")
        why = [
            f"{trigger} already printed; historically {target} drifts into its own report.",
        ]
        if isinstance(wr, (int, float)) and isinstance(ci_low, (int, float)):
            why.append(f"Win rate {wr:.0%} (Wilson floor {ci_low:.0%}) on n={n}.")
        elif isinstance(wr, (int, float)):
            why.append(f"Win rate {wr:.0%} on n={n}.")
        else:
            why.append(f"Sample n={n}.")
        if tier == "thin":
            why.append("Thin history — exploratory only.")

        action = (
            f"Bias long {target} into {report_day.isoformat() if report_day else 'the print'} "
            f"while the {trigger} move holds."
            if (s.get("direction") or "bullish") != "bearish"
            else (
                f"Bias short {target} into "
                f"{report_day.isoformat() if report_day else 'the print'} "
                f"while the {trigger} move holds."
            )
        )
        best[target] = {
            "id": f"wave:{target}:{trigger}",
            "kind": "wave",
            "ticker": target,
            "name": s.get("target_name"),
            "direction": s.get("direction") or "bullish",
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
            "sample_tier": tier,
            "sample_size": n,
            "win_rate": wr,
            "win_rate_ci_low": ci_low,
            "edge_pct": expected,
            "report_date": s.get("target_report_date"),
            "themes": s.get("shared_themes") or [],
            "why": why,
            "watch": (
                f"Hold the lean while {trigger}'s post-print move stays intact and "
                f"{target} hasn't printed yet"
                + (f" ({report_day.isoformat()})" if report_day else "")
                + "."
            ),
            "invalidation": (
                f"Drop it if {trigger} fully mean-reverts, or if {target} gaps "
                "through the peer move before the report."
            ),
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
        direction = s.get("direction") or "long"
        report_day = _parse_day(s.get("report_date"))
        days_left = live.get("trading_days_left")
        days_in = live.get("trading_days_in")
        why = list(s.get("why") or [])[:2]
        if not why:
            why = [
                f"Post-earnings drift historically continued after similar prints.",
            ]
        if isinstance(wr, (int, float)):
            why.append(f"5d continuation {wr:.0%} on n={n}.")
        if tier == "thin" and not any("thin" in w.lower() for w in why):
            why.append("Thin history — size conviction down.")

        side = "long" if direction == "long" else "short"
        action = f"Stay {side} {ticker} for the remaining PEAD window"
        if isinstance(days_left, (int, float)):
            action += f" (~{int(days_left)} sessions left)"
        action += "."

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
                "sample_tier": tier,
                "sample_size": n,
                "win_rate": wr,
                "win_rate_ci_low": s.get("win_rate_ci_low"),
                "edge_pct": edge,
                "report_date": s.get("report_date"),
                "themes": s.get("themes") or [],
                "why": why,
                "watch": (
                    f"Day {days_in if days_in is not None else '?'} of the drift window"
                    + (
                        f"; ~{int(days_left)} sessions left."
                        if isinstance(days_left, (int, float))
                        else "."
                    )
                ),
                "invalidation": (
                    "Thesis breaks on a close back through the earnings-day pivot "
                    "(post-print open/close band)."
                ),
                "href": f"/company/{ticker}",
                "board_href": "/drift",
            }
        )
    return out


def ranked_setups(db: Session, *, limit: int = 12, preview: bool = False) -> dict[str, Any]:
    today = date.today()
    waves = board_snapshots.get_snapshot(db, "waves", "14:21") or {}
    drift = board_snapshots.get_snapshot(db, "drift", "12") or {}
    rows = _wave_rows(list(waves.get("signals") or []), today) + _drift_rows(
        list(drift.get("setups") or []), today
    )

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
        picked = picked[:3]
        for r in picked:
            r["why"] = (r.get("why") or [])[:1]
            r["action"] = "Unlock Pro for the full action / watch note."
            r["invalidation"] = "Unlock Pro for invalidation framing."
        note = (
            "Preview — a taste of today's ranked setups. Pro unlocks the full "
            "morning brief with action, watch, and invalidation."
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
