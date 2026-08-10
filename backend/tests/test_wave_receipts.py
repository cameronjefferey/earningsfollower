"""Tests for wave receipt aggregation and the honesty proof line."""

from __future__ import annotations

from app.services import wave_receipts


def _receipt(
    target: str,
    *,
    direction: str = "bullish",
    runup: float | None = 0.03,
    followed: bool | None = None,
) -> dict:
    if followed is None and runup is not None:
        followed = runup > 0 if direction == "bullish" else runup < 0
    return {
        "target": target,
        "target_name": None,
        "target_report_date": "2026-08-05",
        "wave_start_date": "2026-07-28",
        "peers": [],
        "peer_count": 2,
        "ripped_count": 1,
        "direction": direction,
        "actual_runup_pct": runup,
        "followed": bool(followed),
    }


def test_summarize_counts_wins_and_directional_edge():
    receipts = [
        _receipt("A", runup=0.05),  # bullish, followed, edge +5%
        _receipt("B", runup=-0.02),  # bullish, missed, edge -2%
        _receipt("C", direction="bearish", runup=-0.04),  # followed, edge +4%
    ]
    s = wave_receipts.summarize_receipts(receipts)
    assert s["count"] == 3
    assert s["followed"] == 2
    assert s["follow_rate"] == round(2 / 3, 3)
    # Edge flips sign for bearish waves: (+5 - 2 + 4) / 3
    assert s["avg_edge_pct"] == round((0.05 - 0.02 + 0.04) / 3, 4)
    assert s["best"]["target"] == "A"


def test_summarize_best_respects_direction():
    receipts = [
        _receipt("UP", runup=0.03),
        _receipt("DOWN", direction="bearish", runup=-0.08),  # edge +8% - the best
    ]
    s = wave_receipts.summarize_receipts(receipts)
    assert s["best"]["target"] == "DOWN"


def test_summarize_empty_is_safe():
    s = wave_receipts.summarize_receipts([])
    assert s["count"] == 0
    assert s["follow_rate"] is None
    assert s["best"] is None


def test_proof_line_needs_a_real_sample():
    thin = wave_receipts._payload([_receipt("A"), _receipt("B")], 30, 14)
    assert wave_receipts.receipts_proof_line(thin) is None
    assert wave_receipts.receipts_proof_line(None) is None


def test_proof_line_reads_honestly():
    receipts = [
        _receipt("A", runup=0.05),
        _receipt("B", runup=0.02),
        _receipt("C", runup=-0.01),
        _receipt("D", runup=0.04),
        _receipt("E", direction="bearish", runup=-0.03),
    ]
    payload = wave_receipts._payload(receipts, 30, 14)
    line = wave_receipts.receipts_proof_line(payload)
    assert line is not None
    assert "5 waves resolved" in line
    assert "right 4 of 5" in line
    assert "Winners and losers both counted." in line
