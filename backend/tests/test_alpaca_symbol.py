"""Alpaca share-class symbol normalization (BRK-B → BRK.B)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients.alpaca import normalize_alpaca_symbol  # noqa: E402


def test_share_class_hyphen_becomes_dot():
    assert normalize_alpaca_symbol("BRK-B") == "BRK.B"
    assert normalize_alpaca_symbol("bf-a") == "BF.A"
    assert normalize_alpaca_symbol(" HEI-A ") == "HEI.A"


def test_plain_tickers_unchanged():
    assert normalize_alpaca_symbol("AAPL") == "AAPL"
    assert normalize_alpaca_symbol("brk.b") == "BRK.B"
    assert normalize_alpaca_symbol("SPY") == "SPY"


def test_non_class_hyphens_left_alone():
    # Don't invent mappings for multi-segment or numeric suffixes.
    assert normalize_alpaca_symbol("FOO-BAR") == "FOO-BAR"
    assert normalize_alpaca_symbol("ABC-12") == "ABC-12"
