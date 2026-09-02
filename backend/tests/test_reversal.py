"""Unit tests for the 5-day-loser weekly reversal book.

Runnable without pytest (``python tests/test_reversal.py`` from the backend
dir) and via pytest. No network: ranking uses an in-memory panel.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.paper.reversal import (  # noqa: E402
    hold_elapsed,
    rank_from_panel,
    reaction_dates,
    reversal_exit_reason,
    shadow_hold_due,
    shadow_vs_live,
    trading_days_between,
)


def _sessions(start: date, n: int) -> list[date]:
    """n weekdays starting at ``start`` (must be a weekday)."""
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _panel(tickers: dict[str, list[float]], sessions: list[date], volume: float = 2_000_000) -> pd.DataFrame:
    rows = []
    for t, closes in tickers.items():
        assert len(closes) == len(sessions)
        for d, c in zip(sessions, closes):
            rows.append({"ticker": t, "date": d, "close": c, "volume": volume})
    return pd.DataFrame(rows)


def test_trading_days_monday_to_next_monday_is_five():
    assert trading_days_between(date(2026, 8, 24), date(2026, 8, 31)) == 5
    assert hold_elapsed(date(2026, 8, 24), date(2026, 8, 31)) == 5
    assert hold_elapsed(date(2026, 8, 24), date(2026, 8, 24)) == 0


def test_rank_picks_worst_five_liquid_names():
    # 10 sessions so pct_change(5) is defined. Last 5 closes drive the rank.
    sessions = _sessions(date(2026, 8, 17), 10)
    # A dumps 20% over the last 5, B 15%, C 10%, D 5%, E 1%, F up 2%.
    def path(start, ret):
        # 5 flats, then geometrically apply `ret` over the last 5.
        first = [start] * 5
        step = (1 + ret) ** (1 / 5)
        last = [start]
        for _ in range(5):
            last.append(last[-1] * step)
        return first + last[1:]

    tickers = {
        "LOSE1": path(50, -0.20),
        "LOSE2": path(50, -0.15),
        "LOSE3": path(50, -0.10),
        "LOSE4": path(50, -0.05),
        "LOSE5": path(50, -0.02),
        "WIN1": path(50, 0.08),
        "CHEAP": path(8, -0.30),  # under $10
        "THIN": path(50, -0.25),  # will override volume
    }
    df = _panel(tickers, sessions, volume=2_000_000)  # $100M dollar vol at $50
    df.loc[df["ticker"] == "THIN", "volume"] = 100  # ~$5k, below $50M
    picks, skipped, pool = rank_from_panel(df, top_n=5, min_price=10, min_dollar_vol=50_000_000)
    assert skipped == []
    assert [c.ticker for c in picks] == ["LOSE1", "LOSE2", "LOSE3", "LOSE4", "LOSE5"]
    assert [c.ticker for c in pool[:5]] == ["LOSE1", "LOSE2", "LOSE3", "LOSE4", "LOSE5"]
    assert all(c.ret_5 < 0 for c in picks)
    assert picks[0].ret_5 < picks[-1].ret_5


def test_earnings_window_drops_a_loser():
    sessions = _sessions(date(2026, 8, 17), 10)
    as_of = sessions[-1]

    def dump(start, ret):
        first = [start] * 5
        step = (1 + ret) ** (1 / 5)
        last = [start]
        for _ in range(5):
            last.append(last[-1] * step)
        return first + last[1:]

    tickers = {
        "EARN": dump(40, -0.22),
        "OK1": dump(40, -0.12),
        "OK2": dump(40, -0.10),
        "OK3": dump(40, -0.08),
        "OK4": dump(40, -0.06),
        "OK5": dump(40, -0.04),
    }
    df = _panel(tickers, sessions)
    # EARN printed BMO on as_of — reaction is as_of, inside ±5.
    earn = {("EARN", as_of)}
    picks, skipped, pool = rank_from_panel(df, earn_reaction=earn, top_n=5)
    assert "EARN" not in [c.ticker for c in picks]
    assert any(c.ticker == "EARN" and c.skipped_earn for c in skipped)
    assert any(c.ticker == "EARN" and c.skipped_earn for c in pool)
    assert pool[0].ticker == "EARN"
    assert [c.ticker for c in picks] == ["OK1", "OK2", "OK3", "OK4", "OK5"]


def test_gappy_lookback_does_not_rank_as_a_five_day_loser():
    """A missing session must not turn a 4-day drop into a 5-day rank."""
    sessions = _sessions(date(2026, 8, 17), 10)
    as_of = sessions[-1]

    def dump(start, ret):
        first = [start] * 5
        step = (1 + ret) ** (1 / 5)
        last = [start]
        for _ in range(5):
            last.append(last[-1] * step)
        return first + last[1:]

    tickers = {
        "GAP": dump(50, -0.20),  # will drop the bar 5 sessions before as_of
        "OK1": dump(50, -0.10),
        "OK2": dump(50, -0.08),
        "OK3": dump(50, -0.06),
        "OK4": dump(50, -0.04),
        "OK5": dump(50, -0.02),
    }
    df = _panel(tickers, sessions)
    hole = sessions[-6]  # 5 sessions before as_of
    df = df[~((df["ticker"] == "GAP") & (df["date"] == hole))]
    picks, skipped, pool = rank_from_panel(df, top_n=5, as_of=as_of)
    assert "GAP" not in [c.ticker for c in picks]
    assert "GAP" not in [c.ticker for c in pool]
    assert [c.ticker for c in picks] == ["OK1", "OK2", "OK3", "OK4", "OK5"]


def test_amc_print_reacts_next_session():
    sessions = _sessions(date(2026, 8, 17), 6)
    friday = sessions[-2]
    monday = sessions[-1]
    react = reaction_dates([("XYZ", friday, "amc")], all_sessions=sessions)
    assert ("XYZ", monday) in react
    assert ("XYZ", friday) not in react


def test_exit_after_five_sessions_not_sooner():
    settings = SimpleNamespace(
        paper_force_close_id_set=set(),
        paper_reversal_hold_days=5,
        paper_reversal_take_profit_pct=0.10,
    )
    t = SimpleNamespace(
        signal_id="RV-1",
        note=None,
        opened_at=datetime(2026, 8, 24, 14, 0),  # Monday
        created_at=None,
        entry_credit=50.0,
        spot_entry=50.0,
    )
    assert reversal_exit_reason(t, date(2026, 8, 25), settings, 51.0) is None  # Tue
    assert reversal_exit_reason(t, date(2026, 8, 28), settings, 52.0) is None  # Fri
    reason = reversal_exit_reason(t, date(2026, 8, 31), settings, 52.0)  # next Mon
    assert reason is not None and "hold" in reason


def test_take_profit_at_ten_percent_beats_the_hold():
    settings = SimpleNamespace(
        paper_force_close_id_set=set(),
        paper_reversal_hold_days=5,
        paper_reversal_take_profit_pct=0.10,
    )
    t = SimpleNamespace(
        signal_id="RV-TP",
        note=None,
        opened_at=datetime(2026, 8, 24, 14, 0),
        created_at=None,
        entry_credit=50.0,
        spot_entry=50.0,
    )
    assert reversal_exit_reason(t, date(2026, 8, 25), settings, 54.9) is None
    reason = reversal_exit_reason(t, date(2026, 8, 25), settings, 55.0)
    assert reason is not None and reason.startswith("take-profit")


def test_live_hold_does_not_clip_at_ten_percent():
    settings = SimpleNamespace(
        paper_force_close_id_set=set(),
        paper_reversal_hold_days=5,
        paper_reversal_take_profit_pct=0.0,
    )
    t = SimpleNamespace(
        signal_id="RV-HOLD",
        note=None,
        opened_at=datetime(2026, 8, 24, 14, 0),
        created_at=None,
        entry_credit=50.0,
        spot_entry=50.0,
    )
    assert reversal_exit_reason(t, date(2026, 8, 25), settings, 55.0) is None
    reason = reversal_exit_reason(t, date(2026, 8, 31), settings, 55.0)
    assert reason is not None and "hold" in reason


def test_force_close_and_bad_fill_beat_the_hold():
    settings = SimpleNamespace(
        paper_force_close_id_set={"RV-X"},
        paper_reversal_hold_days=5,
    )
    t = SimpleNamespace(
        signal_id="RV-X",
        note=None,
        opened_at=datetime(2026, 8, 31, 14, 0),
        created_at=None,
    )
    assert reversal_exit_reason(t, date(2026, 8, 31), settings) == "manual close"
    t2 = SimpleNamespace(
        signal_id="RV-Y",
        note="bad fill: slipped",
        opened_at=datetime(2026, 8, 31, 14, 0),
        created_at=None,
    )
    settings.paper_force_close_id_set = set()
    assert reversal_exit_reason(t2, date(2026, 8, 31), settings) == "flatten: bad entry fill"


def test_flatten_when_discovered_inside_earnings_window():
    settings = SimpleNamespace(
        paper_force_close_id_set=set(),
        paper_reversal_hold_days=5,
        paper_reversal_take_profit_pct=0.10,
    )
    t = SimpleNamespace(
        signal_id="RV-1",
        note=None,
        opened_at=datetime(2026, 9, 1, 14, 0),
        created_at=None,
        entry_credit=100.0,
        spot_entry=100.0,
    )
    assert reversal_exit_reason(
        t, date(2026, 9, 2), settings, 101.0, in_earn_window=True,
    ) == "flatten: earnings window"
    assert reversal_exit_reason(
        t, date(2026, 9, 2), settings, 101.0, in_earn_window=False,
    ) is None


def test_shadow_hold_due_after_five_sessions():
    assert not shadow_hold_due(date(2026, 8, 24), date(2026, 8, 28), 5)
    assert shadow_hold_due(date(2026, 8, 24), date(2026, 8, 31), 5)
    assert not shadow_hold_due(None, date(2026, 8, 31), 5)


def test_shadow_vs_live_hold_beats_early_clip():
    cmp = shadow_vs_live(entry_px=50.0, live_exit_px=55.0, hold_px=58.0, shares=10)
    assert cmp["live_pnl"] == 50.0
    assert cmp["hold_pnl"] == 80.0
    assert cmp["hold_minus_live"] == 30.0
    assert cmp["live_ret"] == 0.1
    assert cmp["hold_ret"] == 0.16


if __name__ == "__main__":
    tests = [
        test_trading_days_monday_to_next_monday_is_five,
        test_rank_picks_worst_five_liquid_names,
        test_earnings_window_drops_a_loser,
        test_gappy_lookback_does_not_rank_as_a_five_day_loser,
        test_amc_print_reacts_next_session,
        test_exit_after_five_sessions_not_sooner,
        test_take_profit_at_ten_percent_beats_the_hold,
        test_live_hold_does_not_clip_at_ten_percent,
        test_force_close_and_bad_fill_beat_the_hold,
        test_flatten_when_discovered_inside_earnings_window,
        test_shadow_hold_due_after_five_sessions,
        test_shadow_vs_live_hold_beats_early_clip,
    ]
    for fn in tests:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(tests)} passed")
