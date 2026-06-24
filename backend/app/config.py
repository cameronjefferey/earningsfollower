from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    fmp_api_key: str = ""
    database_url: str = "sqlite:///./earningsfollower.db"
    history_years: int = 5
    cors_origins: str = "http://localhost:3000"
    enable_scheduler: bool = True

    # --- Alpaca paper trading -------------------------------------------------
    # Paper accounts get Level 3 (multi-leg) options automatically. These come
    # from a *paper* key pair at https://app.alpaca.markets/paper/dashboard/overview.
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_paper: bool = True
    # Conviction-weighted max-loss per trade, as a fraction of account equity.
    # High conviction risks the most (the ceiling); low risks the least.
    paper_risk_high: float = 0.05
    paper_risk_medium: float = 0.03
    paper_risk_low: float = 0.015
    # Max number of contracts per position (sanity cap).
    paper_max_contracts: int = 25
    # Max simultaneous open paper positions.
    paper_max_open: int = 12
    # Enter a setup only when earnings is within this many calendar days.
    paper_entry_window_days: int = 3
    # Floor on the modeled credit (per share) worth trading.
    paper_min_credit: float = 0.10
    # Proactive loss-cutting. Off to start — we exit only after the print and
    # gather data first; flip on once we know stops would have helped. Loss is
    # measured as a fraction of the trade's max risk, evaluated each run (so it's
    # only as timely as the cron cadence).
    paper_stops_enabled: bool = False
    # Hard stop: close any open position once its unrealized loss hits this.
    paper_stop_loss_frac: float = 0.20
    # Near expiry (<= this many days to expiration) tighten to a smaller stop.
    paper_late_dte: int = 1
    paper_late_stop_frac: float = 0.10

    # --- Waves strategy (directional sympathy drift) --------------------------
    # A separate, directional strategy: when a peer reports, buy a slightly-ITM
    # call/put on a themed name that reports soon, ride the pre-earnings drift,
    # and exit on an underlying-move bracket or the day before its own print.
    paper_waves_enabled: bool = True
    # Bracket on the *underlying's* move from entry (favorable / adverse).
    paper_wave_gain_pct: float = 0.10
    paper_wave_loss_pct: float = 0.05
    # Quality filters on the historical lead-lag before we'll trade a wave.
    paper_wave_min_winrate: float = 0.60
    paper_wave_min_samples: int = 4
    # Need at least this much runway before the target's own earnings (so there's
    # room to drift, and the exit-before-print rule leaves a real holding period).
    paper_wave_min_runway_days: int = 3
    # Premium budget per wave trade, as a fraction of equity, and a position cap.
    paper_wave_risk_frac: float = 0.01
    paper_wave_max_open: int = 6

    # --- Drift (PEAD) strategy ------------------------------------------------
    # Post-earnings announcement drift: after a name reports, beats (or misses)
    # and reacts strongly, it tends to keep drifting in the surprise direction
    # for ~5 trading days. We express that as a directional debit spread (defined
    # risk) and exit on a time horizon, a take-profit, or a broken-thesis stop.
    paper_drift_enabled: bool = True
    # Max-loss budget per drift trade (the net debit), as a fraction of equity.
    paper_drift_risk_frac: float = 0.015
    paper_drift_max_open: int = 8
    # Skip setups weaker than this score (the drift screen's own ranking metric).
    paper_drift_min_score: float = 0.0
    # Close the spread this many calendar days after the report (~5 trading days
    # is the horizon the historical edge is measured over).
    paper_drift_hold_days: int = 7
    # Take profit once the spread is worth this fraction of its max width.
    paper_drift_take_profit: float = 0.75

    def paper_risk_fraction(self, conviction: str) -> float:
        """Map a playbook conviction tier to the fraction of equity to risk."""
        return {
            "high": self.paper_risk_high,
            "medium": self.paper_risk_medium,
            "low": self.paper_risk_low,
        }.get(conviction, self.paper_risk_low)

    @property
    def alpaca_trading_base(self) -> str:
        return (
            "https://paper-api.alpaca.markets"
            if self.alpaca_paper
            else "https://api.alpaca.markets"
        )

    @property
    def alpaca_data_base(self) -> str:
        return "https://data.alpaca.markets"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def universe_path(self) -> Path:
        return BASE_DIR / "config" / "universe.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
