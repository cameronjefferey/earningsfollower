"""Static demo payloads for unpaid / preview visitors.

These skip expensive live computation so Waves/Drift/Reddit load instantly,
and they never expose the live book — the UI blurs key numbers on top.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

_THEME_AI = {"key": "ai_tech", "label": "AI / Tech"}
_THEME_SEMI = {"key": "semis_hardware", "label": "Semis / Hardware"}

PREVIEW_NOTE = (
    "Demo preview — layout and features are real; key numbers are sample data. "
    "Subscribe for the live board."
)


def demo_waves(recent_days: int = 14, upcoming_days: int = 21) -> dict:
    today = date.today()
    signals = [
        {
            "trigger": "SNOW",
            "trigger_name": "Snowflake Inc.",
            "trigger_report_date": (today - timedelta(days=5)).isoformat(),
            "trigger_move_pct": 0.084,
            "trigger_beat": True,
            "target": "ORCL",
            "target_name": "Oracle Corporation",
            "target_report_date": (today + timedelta(days=9)).isoformat(),
            "shared_themes": [_THEME_AI],
            "direction": "bullish",
            "expected_runup_pct": 0.041,
            "stats": {
                "trigger": "SNOW",
                "target": "ORCL",
                "avg_runup_pct": 0.041,
                "win_rate": 0.67,
                "sample_size": 6,
                "avg_runup_when_trigger_up_pct": 0.052,
                "avg_runup_when_trigger_down_pct": 0.01,
                "score": 0.72,
            },
        },
        {
            "trigger": "DDOG",
            "trigger_name": "Datadog, Inc.",
            "trigger_report_date": (today - timedelta(days=8)).isoformat(),
            "trigger_move_pct": 0.062,
            "trigger_beat": True,
            "target": "ORCL",
            "target_name": "Oracle Corporation",
            "target_report_date": (today + timedelta(days=9)).isoformat(),
            "shared_themes": [_THEME_AI],
            "direction": "bullish",
            "expected_runup_pct": 0.028,
            "stats": {
                "trigger": "DDOG",
                "target": "ORCL",
                "avg_runup_pct": 0.028,
                "win_rate": 0.58,
                "sample_size": 5,
                "avg_runup_when_trigger_up_pct": 0.035,
                "avg_runup_when_trigger_down_pct": -0.005,
                "score": 0.61,
            },
        },
        {
            "trigger": "NVDA",
            "trigger_name": "NVIDIA Corporation",
            "trigger_report_date": (today - timedelta(days=3)).isoformat(),
            "trigger_move_pct": 0.112,
            "trigger_beat": True,
            "target": "AMD",
            "target_name": "Advanced Micro Devices",
            "target_report_date": (today + timedelta(days=14)).isoformat(),
            "shared_themes": [_THEME_SEMI, _THEME_AI],
            "direction": "bullish",
            "expected_runup_pct": 0.055,
            "stats": {
                "trigger": "NVDA",
                "target": "AMD",
                "avg_runup_pct": 0.055,
                "win_rate": 0.71,
                "sample_size": 7,
                "avg_runup_when_trigger_up_pct": 0.068,
                "avg_runup_when_trigger_down_pct": 0.012,
                "score": 0.81,
            },
        },
        {
            "trigger": "AVGO",
            "trigger_name": "Broadcom Inc.",
            "trigger_report_date": (today - timedelta(days=10)).isoformat(),
            "trigger_move_pct": -0.045,
            "trigger_beat": False,
            "target": "AMD",
            "target_name": "Advanced Micro Devices",
            "target_report_date": (today + timedelta(days=14)).isoformat(),
            "shared_themes": [_THEME_SEMI],
            "direction": "bearish",
            "expected_runup_pct": -0.019,
            "stats": {
                "trigger": "AVGO",
                "target": "AMD",
                "avg_runup_pct": -0.019,
                "win_rate": 0.55,
                "sample_size": 4,
                "avg_runup_when_trigger_up_pct": 0.008,
                "avg_runup_when_trigger_down_pct": -0.031,
                "score": 0.52,
            },
        },
    ]
    return {
        "recent_days": recent_days,
        "upcoming_days": upcoming_days,
        "limit": len(signals),
        "count": len(signals),
        "has_more": False,
        "signals": signals,
        "preview": True,
        "preview_note": PREVIEW_NOTE,
    }


def demo_drift(lookback_days: int = 12) -> dict:
    today = date.today()
    setups = [
        {
            "ticker": "CRWD",
            "name": "CrowdStrike Holdings",
            "sector": "Technology",
            "market_cap": 78_000_000_000,
            "themes": [_THEME_AI],
            "direction": "long",
            "score": 0.78,
            "report_date": (today - timedelta(days=2)).isoformat(),
            "timing": "amc",
            "beat": True,
            "surprise_pct": 0.12,
            "revenue_beat": True,
            "move_pct": 0.091,
            "gap_pct": 0.064,
            "held_gap": True,
            "history": {
                "sample_size": 8,
                "avg_drift_5d_pct": 0.038,
                "win_rate_5d": 0.75,
                "avg_drift_10d_pct": 0.051,
                "win_rate_10d": 0.62,
            },
            "live": {
                "anchor_date": (today - timedelta(days=1)).isoformat(),
                "anchor_open": 312.4,
                "anchor_close": 318.1,
                "last_date": today.isoformat(),
                "last_close": 324.6,
                "drift_so_far_pct": 0.020,
                "trading_days_in": 1,
                "trading_days_left": 4,
                "stop_level": 318.1,
            },
            "plan": None,
            "why": [
                "Beat + strong print historically continues for ~5 trading days.",
                "Gap held into the first post-earnings close.",
                "Sample edge is above our minimum win-rate floor.",
            ],
        },
        {
            "ticker": "SHOP",
            "name": "Shopify Inc.",
            "sector": "Technology",
            "market_cap": 110_000_000_000,
            "themes": [_THEME_AI],
            "direction": "long",
            "score": 0.66,
            "report_date": (today - timedelta(days=4)).isoformat(),
            "timing": "bmo",
            "beat": True,
            "surprise_pct": 0.08,
            "revenue_beat": True,
            "move_pct": 0.057,
            "gap_pct": 0.041,
            "held_gap": True,
            "history": {
                "sample_size": 6,
                "avg_drift_5d_pct": 0.029,
                "win_rate_5d": 0.67,
                "avg_drift_10d_pct": 0.034,
                "win_rate_10d": 0.58,
            },
            "live": {
                "anchor_date": (today - timedelta(days=3)).isoformat(),
                "anchor_open": 78.2,
                "anchor_close": 80.1,
                "last_date": today.isoformat(),
                "last_close": 81.4,
                "drift_so_far_pct": 0.016,
                "trading_days_in": 3,
                "trading_days_left": 2,
                "stop_level": 80.1,
            },
            "plan": None,
            "why": [
                "Clean beat with continuation history on this name.",
                "Still inside the 5-day drift window.",
            ],
        },
        {
            "ticker": "PATH",
            "name": "UiPath Inc.",
            "sector": "Technology",
            "market_cap": 7_500_000_000,
            "themes": [_THEME_AI],
            "direction": "short",
            "score": 0.61,
            "report_date": (today - timedelta(days=1)).isoformat(),
            "timing": "amc",
            "beat": False,
            "surprise_pct": -0.15,
            "revenue_beat": False,
            "move_pct": -0.102,
            "gap_pct": -0.078,
            "held_gap": True,
            "history": {
                "sample_size": 5,
                "avg_drift_5d_pct": -0.042,
                "win_rate_5d": 0.80,
                "avg_drift_10d_pct": -0.055,
                "win_rate_10d": 0.60,
            },
            "live": {
                "anchor_date": today.isoformat(),
                "anchor_open": 14.8,
                "anchor_close": 13.9,
                "last_date": today.isoformat(),
                "last_close": 13.7,
                "drift_so_far_pct": -0.014,
                "trading_days_in": 0,
                "trading_days_left": 5,
                "stop_level": 13.9,
            },
            "plan": None,
            "why": [
                "Miss + down print with historically strong negative drift.",
                "Fresh entry — day 0 of the window.",
            ],
        },
    ]
    return {
        "lookback_days": lookback_days,
        "limit": len(setups),
        "count": len(setups),
        "has_more": False,
        "setups": setups,
        "preview": True,
        "preview_note": PREVIEW_NOTE,
    }


def demo_reddit() -> dict:
    today = date.today().isoformat()
    signals = [
        {
            "scan_date": today,
            "ticker": "PLTR",
            "mention_count": 142,
            "mention_velocity": 3.4,
            "score": 0.72,
            "sentiment": 0.61,
            "direction": "bullish",
            "conviction": "high",
            "pump_risk": "medium",
            "is_noise": False,
            "scored_by": "heuristic",
            "rationale": "Mentions accelerated past baseline with a bullish lean; pump-risk elevated on meme spillover.",
            "subreddits": ["stocks", "options", "wallstreetbets"],
            "samples": [
                "https://www.reddit.com/r/stocks/comments/demo1",
                "https://www.reddit.com/r/options/comments/demo2",
            ],
        },
        {
            "scan_date": today,
            "ticker": "SMCI",
            "mention_count": 88,
            "mention_velocity": 2.1,
            "score": 0.48,
            "sentiment": -0.22,
            "direction": "bearish",
            "conviction": "medium",
            "pump_risk": "high",
            "is_noise": False,
            "scored_by": "heuristic",
            "rationale": "Velocity cleared the floor but sentiment is mixed and pump-risk is high.",
            "subreddits": ["wallstreetbets", "stocks"],
            "samples": ["https://www.reddit.com/r/wallstreetbets/comments/demo3"],
        },
        {
            "scan_date": today,
            "ticker": "ARM",
            "mention_count": 64,
            "mention_velocity": 1.8,
            "score": 0.55,
            "sentiment": 0.34,
            "direction": "bullish",
            "conviction": "medium",
            "pump_risk": "low",
            "is_noise": False,
            "scored_by": "heuristic",
            "rationale": "Steady acceleration in quality subs with modest bullish sentiment.",
            "subreddits": ["stocks", "investing"],
            "samples": ["https://www.reddit.com/r/investing/comments/demo4"],
        },
        {
            "scan_date": today,
            "ticker": "IONQ",
            "mention_count": 51,
            "mention_velocity": 2.6,
            "score": 0.41,
            "sentiment": 0.18,
            "direction": "neutral",
            "conviction": "low",
            "pump_risk": "high",
            "is_noise": True,
            "scored_by": "heuristic",
            "rationale": "Noise flag — thin quality mentions despite velocity spike.",
            "subreddits": ["wallstreetbets"],
            "samples": ["https://www.reddit.com/r/wallstreetbets/comments/demo5"],
        },
    ]
    return {
        "source": "journal",
        "count": len(signals),
        "signals": signals,
        "preview": True,
        "preview_note": PREVIEW_NOTE,
    }


def _fake_pct(seed: int, lo: float, hi: float) -> float:
    """Deterministic pseudo-random in [lo, hi] from an integer seed."""
    x = (seed * 1103515245 + 12345) & 0x7FFFFFFF
    t = (x % 1000) / 999.0
    return lo + (hi - lo) * t


def preview_company(detail: dict) -> dict:
    """Keep the company shell; replace sensitive numbers with demo-looking values."""
    out = deepcopy(detail)
    ticker = (out.get("ticker") or "DEMO").upper()
    seed = sum(ord(c) for c in ticker)

    out["playbook"] = None
    out["preview"] = True
    out["preview_note"] = PREVIEW_NOTE

    # Implied move — shape stays, numbers are demo.
    im = out.get("implied_move")
    if im:
        hist = _fake_pct(seed + 1, 0.04, 0.11)
        expected = _fake_pct(seed + 2, 0.035, 0.13)
        out["implied_move"] = {
            **im,
            "expected_move_pct": expected,
            "historical_avg_abs_move_pct": hist,
            "richness": round(expected / hist, 2) if hist else None,
            "underlying_price": round(40 + _fake_pct(seed + 3, 0, 200), 2),
            "straddle_price": round(_fake_pct(seed + 4, 1.5, 12), 2),
            "verdict": "rich" if expected > hist else "cheap",
        }

    reactions = out.get("reactions") or {}
    events = list(reactions.get("events") or [])[:6]
    fake_events = []
    for i, e in enumerate(events):
        s = seed + 10 + i * 7
        move = _fake_pct(s, -0.12, 0.14)
        fake_events.append(
            {
                **e,
                "eps_estimate": round(_fake_pct(s + 1, 0.2, 3.5), 2),
                "eps_actual": round(_fake_pct(s + 2, 0.2, 3.8), 2),
                "surprise_pct": _fake_pct(s + 3, -0.2, 0.25),
                "beat": move > 0,
                "move_pct": move,
                "gap_pct": move * 0.7,
                "drift_pct": move * 0.35,
                "drift_1d_pct": move * 0.15,
                "drift_10d_pct": move * 0.5,
            }
        )

    abs_moves = [abs(e["move_pct"]) for e in fake_events] or [0.06]
    up = sum(1 for e in fake_events if (e.get("move_pct") or 0) > 0)
    n = len(fake_events) or 1
    out["reactions"] = {
        "summary": {
            "sample_size": n,
            "avg_abs_move_pct": sum(abs_moves) / len(abs_moves),
            "median_abs_move_pct": sorted(abs_moves)[len(abs_moves) // 2],
            "avg_move_pct": sum(e["move_pct"] for e in fake_events) / n if fake_events else 0.02,
            "up_rate": up / n if fake_events else 0.55,
            "last_move_pct": fake_events[-1]["move_pct"] if fake_events else 0.04,
            "beat_rate": 0.62,
            "beat_streak": 2 + (seed % 3),
            "avg_move_on_beat_pct": 0.045,
            "avg_move_on_miss_pct": -0.038,
            "avg_drift_pct": 0.012,
            "avg_drift_after_beat_pct": 0.021,
            "avg_drift_after_miss_pct": -0.018,
            "continuation_rate": 0.58,
        },
        "events": fake_events,
    }

    prices = list(out.get("price_history") or [])[-60:]
    if prices:
        base = 50 + _fake_pct(seed + 50, 0, 150)
        fake_prices = []
        px = base
        for i, p in enumerate(prices):
            px *= 1 + _fake_pct(seed + 60 + i, -0.025, 0.028)
            fake_prices.append({**p, "close": round(px, 2), "open": round(px * 0.995, 2)})
        out["price_history"] = fake_prices
    else:
        out["price_history"] = []

    peers = list(out.get("peers") or [])[:3]
    fake_peers = []
    for i, p in enumerate(peers):
        s = seed + 200 + i * 11
        fake_peers.append(
            {
                **p,
                "target": ticker,
                "avg_runup_pct": _fake_pct(s, -0.04, 0.08),
                "win_rate": _fake_pct(s + 1, 0.45, 0.8),
                "sample_size": 3 + (s % 6),
                "avg_runup_when_trigger_up_pct": _fake_pct(s + 3, -0.02, 0.09),
                "avg_runup_when_trigger_down_pct": _fake_pct(s + 4, -0.06, 0.03),
                "score": _fake_pct(s + 2, 0.4, 0.9),
            }
        )
    # Pad with demo peers if the name has none.
    if not fake_peers:
        fake_peers = [
            {
                "trigger": "PEER",
                "target": ticker,
                "avg_runup_pct": 0.032,
                "win_rate": 0.64,
                "sample_size": 5,
                "avg_runup_when_trigger_up_pct": 0.045,
                "avg_runup_when_trigger_down_pct": -0.01,
                "score": 0.7,
            },
            {
                "trigger": "RIVAL",
                "target": ticker,
                "avg_runup_pct": -0.015,
                "win_rate": 0.5,
                "sample_size": 4,
                "avg_runup_when_trigger_up_pct": 0.01,
                "avg_runup_when_trigger_down_pct": -0.03,
                "score": 0.48,
            },
        ]
    out["peers"] = fake_peers

    analyst = out.get("analyst")
    if analyst:
        pt = round(40 + _fake_pct(seed + 300, 0, 200), 2)
        out["analyst"] = {
            **analyst,
            "price_target": pt,
            "price_target_high": round(pt * 1.25, 2),
            "price_target_low": round(pt * 0.75, 2),
            "upside_pct": _fake_pct(seed + 301, -0.1, 0.35),
            "bullish_pct": _fake_pct(seed + 302, 0.4, 0.85),
            "eps_estimate_next": round(_fake_pct(seed + 303, 0.3, 4.0), 2),
        }

    return out
