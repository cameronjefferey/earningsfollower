from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# FMP retired the legacy /api/v3 and /api/v4 endpoints; the current API
# (and the free tier) lives under /stable.
STABLE = "https://financialmodelingprep.com/stable"


class FMPError(RuntimeError):
    pass


class FMPClient:
    """Thin wrapper over the Financial Modeling Prep `/stable` API.

    Degrades gracefully when no API key is configured: methods return empty
    results and log a warning so ingestion can fall back to yfinance.
    """

    def __init__(self, api_key: str | None = None, timeout: float = 20.0) -> None:
        self.api_key = api_key if api_key is not None else get_settings().fmp_api_key
        self._client = httpx.Client(timeout=timeout)
        self._disabled = False

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and not self._disabled

    def disable(self) -> None:
        """Stop making FMP calls for the rest of this client's life (e.g. after
        hitting the daily quota); ingestion then relies on yfinance."""
        self._disabled = True

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FMPClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.enabled:
            logger.warning("FMP_API_KEY not set; skipping FMP call to %s", path)
            return []
        params = dict(params or {})
        params["apikey"] = self.api_key
        resp = self._client.get(f"{STABLE}/{path}", params=params)
        if resp.status_code == 401:
            raise FMPError("FMP rejected the API key (401). Check FMP_API_KEY.")
        if resp.status_code == 429:
            # True daily-quota / rate limit: signal callers to stop hammering.
            raise FMPError("FMP rate limit hit (429). Free tier is 250 calls/day.")
        if resp.status_code in (402, 403, 404):
            # Premium-gated or unavailable for this symbol on the free tier.
            # Treat as "no data" so ingestion can fall back to yfinance.
            logger.debug("FMP %s for %s -> treating as empty", resp.status_code, path)
            return []
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("Error Message"):
            raise FMPError(str(data["Error Message"]))
        return data

    # --- Earnings ------------------------------------------------------------

    def earnings(self, symbol: str, limit: int = 40) -> list[dict[str, Any]]:
        """Historical + upcoming earnings for a symbol (date, EPS/revenue est & actual).

        The `limit` query param is premium-gated on FMP, so we fetch the full
        series and slice client-side. Rows are returned most-recent first.
        """
        rows = self._get("earnings", {"symbol": symbol}) or []
        return rows[:limit] if limit else rows

    # --- Reference -----------------------------------------------------------

    def stock_peers(self, symbol: str) -> list[str]:
        data = self._get("stock-peers", {"symbol": symbol}) or []
        return [d["symbol"].upper() for d in data if d.get("symbol")]

    def profile(self, symbol: str) -> dict[str, Any] | None:
        data = self._get("profile", {"symbol": symbol}) or []
        return data[0] if isinstance(data, list) and data else None

    # --- Analyst data --------------------------------------------------------

    def price_target_consensus(self, symbol: str) -> dict[str, Any] | None:
        data = self._get("price-target-consensus", {"symbol": symbol}) or []
        return data[0] if isinstance(data, list) and data else None

    def grades_historical(self, symbol: str, limit: int = 12) -> list[dict[str, Any]]:
        """Monthly analyst rating breakdown, most-recent first.

        The `limit` param is premium-gated, so we fetch all and slice locally.
        """
        rows = self._get("grades-historical", {"symbol": symbol}) or []
        return rows[:limit] if limit else rows
