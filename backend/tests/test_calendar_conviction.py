"""Calendar conviction mirrors playbook tiers without the full playbook payload."""

from app.services.playbook import calendar_conviction


def test_calendar_conviction_none_when_thin_history():
    assert calendar_conviction({"sample_size": 2}, None) is None


def test_calendar_conviction_high_on_strong_seller_edge():
    summary = {
        "sample_size": 12,
        "avg_move_pct": 0.0,
        "last_move_pct": 0.0,
        "avg_move_on_beat_pct": 0.0,
    }
    implied = {
        "expected_move_pct": 0.08,
        "historical_avg_abs_move_pct": 0.04,
        "richness": 2.0,
        "exceed_rate": 0.15,
        "edge_verdict": "seller_edge",
        "edge_sample": 12,
    }
    assert calendar_conviction(summary, implied) == "high"


def test_calendar_conviction_low_without_edge_sample():
    summary = {
        "sample_size": 12,
        "avg_move_pct": 0.0,
        "last_move_pct": 0.0,
        "avg_move_on_beat_pct": 0.0,
    }
    implied = {
        "expected_move_pct": 0.08,
        "historical_avg_abs_move_pct": 0.04,
        "richness": 2.0,
        "exceed_rate": 0.15,
        "edge_verdict": "seller_edge",
        "edge_sample": 3,
    }
    assert calendar_conviction(summary, implied) == "low"
