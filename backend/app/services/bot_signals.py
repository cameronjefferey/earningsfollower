"""Lightweight bot heuristics for ad / auth traffic.

Not a full bot manager — just enough to tag obvious scanners and generic
datacenter probes so Telegram/ops events are actionable.
"""

from __future__ import annotations

import re

_BOT_UA = re.compile(
    r"(bot|crawl|spider|slurp|bytespider|facebookexternalhit|preview|"
    r"headless|phantomjs|selenium|python-requests|curl/|wget/|httpclient)",
    re.I,
)
_GENERIC_UA = re.compile(r"^mozilla/5\.0\s*\(compatible\)\s*$", re.I)


def score_bot(user_agent: str | None, *, ip: str | None = None) -> tuple[int, list[str]]:
    """Return (0–100 score, reason codes). Higher = more bot-like."""
    ua = (user_agent or "").strip()
    reasons: list[str] = []
    score = 0

    if not ua:
        score += 70
        reasons.append("empty_ua")
    elif _GENERIC_UA.match(ua):
        score += 85
        reasons.append("generic_ua")
    elif _BOT_UA.search(ua):
        score += 75
        reasons.append("ua_keyword")

    # Very short "compatible" family without platform details.
    if ua.lower().startswith("mozilla/5.0 (compatible") and "msie" not in ua.lower():
        if "generic_ua" not in reasons:
            score = max(score, 80)
            reasons.append("compatible_ua")

    if ip and _looks_like_aws_ecs_probe(ip) and score >= 50:
        reasons.append("aws_ip")
        score = min(100, score + 5)

    return min(100, score), reasons


def is_bot_suspect(score: int) -> bool:
    return score >= 50


def _looks_like_aws_ecs_probe(ip: str) -> bool:
    """Cheap hint only — not a blocklist. 23.20–23.22 / 52.x / 54.x are common AWS."""
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if a == 23 and 20 <= b <= 23:
        return True
    if a in (52, 54):
        return True
    return False
