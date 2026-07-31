"""Waves board must not fan out a single peer print across an industry."""

from app.services.waves import filter_by_min_peers, page_wave_signals


def _sig(trigger: str, target: str, score: float = 1.0) -> dict:
    return {
        "trigger": trigger,
        "target": target,
        "expected_runup_pct": 0.01,
        "stats": {"score": score, "sample_size": 10, "win_rate": 0.6},
    }


def test_filter_by_min_peers_drops_single_peer_fanout():
    signals = [
        _sig("ABBV", "VRTX"),
        _sig("ABBV", "MRK"),
        _sig("ABBV", "BNTX"),
        _sig("SNOW", "ORCL"),
        _sig("DDOG", "ORCL"),
    ]
    kept = filter_by_min_peers(signals)
    assert {s["target"] for s in kept} == {"ORCL"}
    assert len(kept) == 2


def test_page_wave_signals_keeps_target_groups_intact():
    signals = [
        _sig("A", "T1", 3),
        _sig("B", "T1", 2),
        _sig("C", "T2", 1.5),
        _sig("D", "T2", 1.4),
        _sig("E", "T3", 1.0),
        _sig("F", "T3", 0.9),
    ]
    # Limit 3 can't fit two groups of 2 without orphaning — keep first group only.
    page, has_more = page_wave_signals(signals, limit=3)
    assert {s["target"] for s in page} == {"T1"}
    assert len(page) == 2
    assert has_more is True
