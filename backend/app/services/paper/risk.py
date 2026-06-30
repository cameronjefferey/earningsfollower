"""Canonical defined-risk max-loss math, shared by the executor (recompute on
fill) and the startup backfill (heal historical rows). Kept dependency-free so
low-level modules like the DB session can import it without a cycle."""

from __future__ import annotations

DEBIT_STRATEGIES = ("waves", "drift", "reddit")


def defined_risk_max_loss(
    strategy: str | None,
    width: float | None,
    entry_credit: float | None,
    contracts: int | None,
) -> float | None:
    """Total dollars at risk for a defined-risk options position, derived from
    the *booked* entry price so it always matches the credit/debit on the card.

    - Credit spreads / iron condors: max loss = (width - credit) per share.
    - Directional debit spreads (waves/drift/reddit): max loss = the debit paid
      (held in ``entry_credit``), which is the entire position.

    Returns None when the inputs needed for that structure aren't present, so
    callers can leave the stored value untouched."""
    if entry_credit is None or not contracts:
        return None
    if (strategy or "earnings") in DEBIT_STRATEGIES:
        return round(entry_credit * 100 * contracts, 2)
    if width:
        return round(max(width - entry_credit, 0.0) * 100 * contracts, 2)
    return None
