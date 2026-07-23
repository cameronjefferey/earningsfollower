"""Shared sample-size honesty helpers for research boards."""

from __future__ import annotations

import math
from typing import Literal

SampleTier = Literal["thin", "ok", "solid"]


def sample_tier(n: int | None) -> SampleTier:
    """thin (<5), ok (5–8), solid (9+)."""
    size = int(n or 0)
    if size < 5:
        return "thin"
    if size < 9:
        return "ok"
    return "solid"


def wilson_low(win_rate: float | None, n: int | None, z: float = 1.96) -> float | None:
    """Lower bound of a 95% Wilson interval for a binomial win rate."""
    if win_rate is None or not n or n <= 0:
        return None
    phat = max(0.0, min(1.0, float(win_rate)))
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return round(max(0.0, centre - half), 4)


def annotate_history(sample_size: int | None, win_rate: float | None) -> dict:
    return {
        "sample_tier": sample_tier(sample_size),
        "win_rate_ci_low": wilson_low(win_rate, sample_size),
    }
